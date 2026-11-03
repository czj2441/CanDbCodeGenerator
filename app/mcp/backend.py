"""HTTP 后端客户端 — MCP 服务器以 PAT 身份调用 CanMatrix 后端 API。

HTTP 请求走 request()；编辑操作走 WS 会话层（control/open_session/get_session/
close_session，见 app/mcp/ws.py）。
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from app.mcp.errors import BackendError
from app.mcp.ws import CallResult, WsConnection, get_session_pool

# 后端 API 默认地址（可用环境变量 CANMATRIX_BACKEND_URL 覆盖）。
DEFAULT_BACKEND_URL = "http://127.0.0.1:8080"

# PAT → 用户名缓存（/api/me 解析一次即可）
_PAT_USERNAME_CACHE: dict[str, str] = {}


def _derive_ws_url(base_url: str) -> str:
    """由 HTTP 地址推导 WS 地址（WS 端口 = HTTP 端口 + 1，见 app/server/lifecycle.py）。"""
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    port = (parsed.port or (443 if parsed.scheme == "https" else 80)) + 1
    return f"{scheme}://{parsed.hostname}:{port}"


class BackendClient:
    """后端 HTTP API 客户端 — 所有请求带 Authorization: Bearer <PAT>。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._transport = transport
        self._ws_url = _derive_ws_url(self.base_url)

    async def request(
        self, method: str, path: str, body: dict | None = None, timeout: float = 30.0
    ) -> dict:
        """发起后端请求，成功时返回完整响应体（{"success": true, "data": ...}，调用方取 data）。

        HTTP 非 2xx 或 {"success": false} → BackendError(code=f"HTTP_{status}",
        message=error 文案, details=details)；连接失败/超时 → BackendError(code="HTTP_0")。
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, transport=self._transport, timeout=timeout
            ) as client:
                resp = await client.request(
                    method,
                    path,
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=body,
                )
        except httpx.RequestError as exc:
            raise BackendError(code="HTTP_0", message=f"无法连接后端：{exc}", details={}) from exc

        try:
            resp_body = resp.json()
        except ValueError:
            resp_body = None
        if not isinstance(resp_body, dict):
            resp_body = {}
        if 200 <= resp.status_code < 300 and resp_body.get("success"):
            return resp_body
        raise BackendError(
            code=f"HTTP_{resp.status_code}",
            message=resp_body.get("error") or f"后端返回 HTTP {resp.status_code}",
            details=resp_body.get("details") or {},
        )

    # ── WS 会话层（编辑操作走 WS，见 app/mcp/ws.py） ──

    async def _username(self) -> str:
        """解析当前 PAT 对应的用户名（GET /api/me，按 token 缓存）。"""
        cached = _PAT_USERNAME_CACHE.get(self.token)
        if cached is not None:
            return cached
        resp = await self.request("GET", "/api/me")
        username = (resp.get("data") or {}).get("username", "")
        if not username:
            raise BackendError("AUTH_REQUIRED", "无法识别当前 PAT 的用户身份")
        _PAT_USERNAME_CACHE[self.token] = username
        return username

    async def control(self) -> WsConnection:
        """每用户共享一条无 session 控制连接（供 get_sessions 等）。"""
        pool = get_session_pool()
        return await pool.get_control(self._ws_url, await self._username(), self.token)

    async def open_session(self, msg_type: str, data: dict) -> tuple[WsConnection, CallResult]:
        """新建连接执行创建类消息（load_file/import_file/create_file/new_file），
        按 CallResult.new_session_id 登记入池（key=(username, session_id)）。

        调用失败或未产生新会话 ID 时关闭新建连接并抛错，不入池。
        """
        pool = get_session_pool()
        username = await self._username()
        conn = await pool.connect(self._ws_url, self.token)
        try:
            result = await conn.call(msg_type, data)
        except BaseException:
            await conn.close()
            raise
        if not result.new_session_id:
            await conn.close()
            raise BackendError("SESSION_NOT_CREATED", f"{msg_type} 未返回新会话 ID，无法登记会话池")
        pool.put(username, result.new_session_id, conn)
        return conn, result

    async def get_session(self, session_id: str) -> WsConnection:
        """查池返回该用户绑定该会话的连接（按 (username, session_id) 隔离）；
        未命中/已过期抛 BackendError("SESSION_NOT_FOUND", ...)。"""
        pool = get_session_pool()
        return await pool.get(await self._username(), session_id)

    async def close_session(self, session_id: str) -> None:
        """关闭会话：发 WS release_lock（abort: False）→ 关连接出池。"""
        pool = get_session_pool()
        username = await self._username()
        conn = pool.pop(username, session_id)
        if conn is None:
            raise BackendError("SESSION_NOT_FOUND", "会话不存在或已过期，请重新 canmatrix_open_file")
        try:
            await conn.call("release_lock", {"session_id": session_id, "abort": False})
        finally:
            await conn.close()


def get_backend() -> BackendClient:
    """构造当前请求对应的后端客户端（当前 PAT + 环境变量 CANMATRIX_BACKEND_URL）。"""
    # 延迟导入：auth_context 顶层导入本模块的 get_backend，避免循环依赖。
    from app.mcp.auth_context import get_current_pat

    return BackendClient(
        base_url=os.environ.get("CANMATRIX_BACKEND_URL", DEFAULT_BACKEND_URL),
        token=get_current_pat() or "",
    )
