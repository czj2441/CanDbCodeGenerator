"""
ws_router.py — 消息路由层 + Handler 基类

按消息 type 分发到对应 Handler。Handler 不接触 ws/transport，只返回 HandlerResult。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import websockets.exceptions

logger = logging.getLogger(__name__)


@dataclass
class HandlerResult:
    """Handler 统一返回结构。Router 负责 reply + broadcast。"""
    data: dict
    events: list[dict] = field(default_factory=list)
    new_version: int = 0
    session_id: str = ""
    new_session_id: Optional[str] = None  # new_file/import_file 切换时设此字段
    changed_msg_ids: Optional[list[int]] = None


class HandlerError(Exception):
    """Handler 业务错误。Router 转为 error 响应。"""

    def __init__(self, code: str, message: str = "", details: dict = None):
        self.code = code
        self.message = message or code
        self.details = details or {}
        super().__init__(message or code)


# 信号可编辑字段白名单（防止写入非法字段）
EDITABLE_SIGNAL_FIELDS = {
    'name', 'start_bit', 'length', 'byte_order',
    'factor', 'offset', 'min_val', 'max_val', 'unit', 'comment',
    'value_table_name',
}

# ── 权限常量 ──
# 需要写权限的操作（仅文件 owner 可执行）
WRITE_OPERATIONS = frozenset({
    'edit_signal', 'add_signal', 'delete_signal',
    'batch_add_signals', 'batch_edit_signals', 'batch_delete_signals',
    'edit_message', 'add_message', 'delete_message',
    'batch_edit_messages', 'batch_delete_messages',
    'edit_database', 'undo', 'redo', 'save',
    'delete_file',
    'add_value_table', 'update_value_table', 'delete_value_table', 'rename_value_table',
})
# 文件创建操作（任何登录用户均可，创建后自动设 owner）
FILE_CREATE_TYPES = frozenset({'new_file', 'create_file'})
# 文件导入（仅创建新文件，不允许覆盖已有文件）
FILE_IMPORT_TYPES = frozenset({'import_file'})
# 免除写权限检查的操作
WRITE_EXEMPT = frozenset({'save_as'})
# 仅 admin 可执行的操作
ADMIN_ONLY_OPERATIONS = frozenset({'change_file_owner'})
# 仅 owner 可执行的操作
OWNER_ONLY_OPERATIONS = frozenset({'steal_lock'})
# 需要提取 file_name 的操作（用于权限检查）
_FILE_NAME_OPERATIONS = WRITE_OPERATIONS | OWNER_ONLY_OPERATIONS | WRITE_EXEMPT | FILE_IMPORT_TYPES


class MessageRouter:
    """消息路由器 — type → handler"""

    def __init__(self, transport, session_mgr, auth_service=None):
        self._transport = transport
        self._session_mgr = session_mgr
        self._auth = auth_service
        self._handlers: dict[str, callable] = {}

    def register(self, msg_type: str, handler):
        """注册消息类型对应的 handler。"""
        self._handlers[msg_type] = handler

    async def dispatch(self, ws, msg: dict):
        """入口：从 _handler 协程调用，一条消息进来 → 找 handler → 执行 → 回复。
    
        handler 是同步函数（内部加锁操作 db），用 asyncio.to_thread 包装执行，
        避免阻塞 asyncio event loop。
    
        Returns:
            HandlerResult 或 None（handler 无返回值时）
        """
        msg_type = msg.get("type")
        req_id = msg.get("requestId")
        data = msg.get("data", {})
        sid = data.get("session_id", "")[:8]
        t0 = time.monotonic()
    
        handler = self._handlers.get(msg_type)
        if not handler:
            logger.warning("WS <<< type=%s UNKNOWN_TYPE", msg_type)
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg.get("requestId"),
                "code": "UNKNOWN_TYPE",
                "message": f"Unknown message type: {msg_type}"
            })
            return None
    
        logger.info("WS >>> type=%s requestId=%s session=%s", msg_type, req_id, sid)

        # ── Viewer session 服务端写保护 ──
        if msg_type in WRITE_OPERATIONS or msg_type in WRITE_EXEMPT:
            session_id = data.get("session_id", "")
            if session_id and self._session_mgr.is_viewer(session_id):
                elapsed = (time.monotonic() - t0) * 1000
                logger.warning("WS <<< type=%s VIEWER_WRITE_DENIED elapsed=%.1fms", msg_type, elapsed)
                try:
                    await self._transport.reply(ws, {
                        "type": "error",
                        "requestId": msg.get("requestId"),
                        "code": "read_only",
                        "message": "只读会话不允许执行此操作",
                    })
                except websockets.exceptions.ConnectionClosed:
                    pass
                return None

        # ── 权限拦截 ──
        if self._auth:
            perm_error = self._check_permission(msg_type, data)
            if perm_error:
                elapsed = (time.monotonic() - t0) * 1000
                logger.warning("WS <<< type=%s PERMISSION_DENIED elapsed=%.1fms", msg_type, elapsed)
                try:
                    await self._transport.reply(ws, {
                        "type": "error",
                        "requestId": msg.get("requestId"),
                        "code": "permission_denied",
                        "message": perm_error["message"],
                        "details": perm_error.get("details", {}),
                    })
                except websockets.exceptions.ConnectionClosed:
                    pass
                return None
    
        try:
            # handler 是同步函数，用 to_thread 在线程池中执行
            result = await asyncio.to_thread(handler, data)
    
            elapsed = (time.monotonic() - t0) * 1000
            logger.info("WS <<< type=%s OK version=%d elapsed=%.1fms",
                        msg_type, result.new_version, elapsed)

            # ── 文件创建后自动设置 owner ──
            if self._auth and result and msg_type in (FILE_CREATE_TYPES | FILE_IMPORT_TYPES):
                username = data.get("_username", "")
                file_name = self._extract_file_name(msg_type, data, result)
                if username and file_name:
                    self._auth.set_file_permission(file_name, username)
    
            # 回复请求者
            await self._transport.reply(ws, {
                "type": "ok",
                "requestId": msg["requestId"],
                "data": result.data,
                "new_version": result.new_version
            })
    
            # 广播事件
            for event in result.events:
                self._transport.broadcast(result.session_id, event)
    
            return result
    
        except HandlerError as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("WS <<< type=%s ERROR code=%s msg=%s elapsed=%.1fms",
                           msg_type, e.code, e.message, elapsed)
            try:
                await self._transport.reply(ws, {
                    "type": "error",
                    "requestId": msg.get("requestId"),
                    "code": e.code,
                    "message": e.message,
                    "details": e.details
                })
            except websockets.exceptions.ConnectionClosed:
                pass  # 客户端已断连，忽略响应发送失败
            return None
    
        except websockets.exceptions.ConnectionClosed:
            # 客户端断连（如 bfcache/page unload）时响应发送失败，属于正常行为
            elapsed = (time.monotonic() - t0) * 1000
            logger.debug("WS <<< type=%s client disconnected during response elapsed=%.1fms",
                         msg_type, elapsed)
            return None

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            # 兜底：Handler bug 不应断开 WS 连接
            logger.error("WS <<< type=%s EXCEPTION %s: %s elapsed=%.1fms",
                         msg_type, type(e).__name__, e, elapsed, exc_info=True)
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg.get("requestId"),
                "code": "INTERNAL_ERROR",
                "message": str(e)
            })
            return None

    # ── 权限检查辅助方法 ──

    def _check_permission(self, msg_type: str, data: dict) -> dict | None:
        """检查消息权限。返回错误 dict 或 None（通过）。

        权限模型：
        - WRITE_OPERATIONS：仅文件 owner 可执行
        - ADMIN_ONLY_OPERATIONS：仅 admin 可执行
        - OWNER_ONLY_OPERATIONS：仅文件 owner 可执行
        - WRITE_EXEMPT (save_as)：免除写权限检查
        - FILE_CREATE_TYPES / FILE_IMPORT_TYPES：任何登录用户均可
        - 其他操作：无额外权限检查
        """
        if not self._auth:
            return None

        username = data.get("_username", "")
        if not username:
            return {"message": "未认证", "details": {}}

        # save_as 免除写权限检查
        if msg_type in WRITE_EXEMPT:
            return None

        # 文件创建操作：任何登录用户均可
        if msg_type in FILE_CREATE_TYPES:
            return None

        # import_file：仅允许创建新文件
        if msg_type in FILE_IMPORT_TYPES:
            file_name = data.get("file_name", "")
            if file_name:
                # 检查文件是否已存在
                import os
                from app.auth.service import DATA_DIR
                target = os.path.join(DATA_DIR, file_name)
                if os.path.isfile(target):
                    return {"message": "import_file 仅允许创建新文件，不允许覆盖已有文件"}
            return None

        # admin-only 操作
        if msg_type in ADMIN_ONLY_OPERATIONS:
            if not self._auth.is_admin(username):
                return {"message": "仅管理员可执行此操作"}
            return None

        # owner-only 操作 (steal_lock)
        if msg_type in OWNER_ONLY_OPERATIONS:
            file_name = self._get_session_file_name(data)
            if file_name and not self._auth.is_owner(file_name, username):
                perm = self._auth.get_file_permission(file_name)
                return {
                    "message": "仅文件所有者可执行此操作",
                    "details": {"owner": perm.get("owner", "") if perm else ""}
                }
            return None

        # 写操作：仅 owner
        if msg_type in WRITE_OPERATIONS:
            file_name = self._get_session_file_name(data)
            if file_name and not self._auth.can_write(file_name, username):
                perm = self._auth.get_file_permission(file_name)
                return {
                    "message": "无写入权限，仅文件所有者可编辑",
                    "details": {"owner": perm.get("owner", "") if perm else ""}
                }
            return None

        return None

    def _get_session_file_name(self, data: dict) -> str:
        """从 session_id 反查文件名。"""
        session_id = data.get("session_id", "")
        if not session_id:
            return ""
        session = self._session_mgr.get(session_id)
        if not session:
            return ""
        import os
        return os.path.basename(session.file_path)

    def _extract_file_name(self, msg_type: str, data: dict, result) -> str:
        """从 handler 结果中提取新创建的文件名。"""
        # new_session_id 表示切换到了新文件
        if result.new_session_id:
            session = self._session_mgr.get(result.new_session_id)
            if session:
                import os
                return os.path.basename(session.file_path)
        # 从 data 中获取
        file_name = data.get("file_name", "")
        if file_name:
            return file_name
        return ""
