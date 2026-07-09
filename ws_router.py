"""
ws_router.py — 消息路由层 + Handler 基类

按消息 type 分发到对应 Handler。Handler 不接触 ws/transport，只返回 HandlerResult。
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional


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


# 信号可编辑字段白名单（防止写入 uuid 等不可变字段）
EDITABLE_SIGNAL_FIELDS = {
    'name', 'start_bit', 'length', 'byte_order',
    'factor', 'offset', 'min_val', 'max_val', 'unit', 'comment'
}


class MessageRouter:
    """消息路由器 — type → handler"""

    def __init__(self, transport, session_mgr):
        self._transport = transport
        self._session_mgr = session_mgr
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
        handler = self._handlers.get(msg_type)
        if not handler:
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg.get("requestId"),
                "code": "UNKNOWN_TYPE",
                "message": f"Unknown message type: {msg_type}"
            })
            return None

        try:
            # handler 是同步函数，用 to_thread 在线程池中执行
            data = msg.get("data", {})
            result = await asyncio.to_thread(handler, data)

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
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg.get("requestId"),
                "code": e.code,
                "message": e.message,
                "details": e.details
            })
            return None

        except Exception as e:
            # 兜底：Handler bug 不应断开 WS 连接
            print(f"[WS] handler exception: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await self._transport.reply(ws, {
                "type": "error",
                "requestId": msg.get("requestId"),
                "code": "INTERNAL_ERROR",
                "message": str(e)
            })
            return None
