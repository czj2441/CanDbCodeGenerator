"""请求身份上下文 — PAT 存取与用户校验。

身份中间件经 set_current_pat 把 Authorization: Bearer 中的 PAT 写入 contextvar；
工具经 require_user 取 {"username", "role"}（后端 /api/me 校验 + 60 秒缓存）。
"""
from __future__ import annotations

import time
from contextvars import ContextVar

from mcp.server.mcpserver.exceptions import ToolError

from app.mcp.backend import get_backend
from app.mcp.errors import BackendError

# 未认证时统一抛出的工具错误文案。
AUTH_ERROR_MESSAGE = "未认证：请在 Authorization: Bearer <PAT> 中提供个人访问令牌"

# 同一 PAT 的 /api/me 校验结果缓存时长（秒）。
_ME_CACHE_TTL = 60.0

_current_pat: ContextVar[str | None] = ContextVar("canmatrix_mcp_current_pat", default=None)
_me_cache: dict[str, tuple[float, dict]] = {}


def set_current_pat(pat: str | None) -> None:
    """记录当前请求的 PAT（身份中间件调用；None 表示清除）。"""
    _current_pat.set(pat)


def get_current_pat() -> str | None:
    """返回当前请求的 PAT；未认证则 None。"""
    return _current_pat.get()


async def require_user() -> dict:
    """校验当前 PAT 并返回 {"username", "role"}。

    调后端 GET /api/me 校验，同一 PAT 的结果缓存 60 秒。
    无 PAT 或令牌被拒（HTTP 401 / 2xx 但 {"success": false}）→ ToolError「未认证：…」；
    其余后端故障（HTTP_5xx、连接失败、超时等）原样传播 BackendError，保留 code/message/details。
    """
    pat = get_current_pat()
    if not pat:
        raise ToolError(AUTH_ERROR_MESSAGE)
    now = time.monotonic()
    cached = _me_cache.get(pat)
    if cached is not None and cached[0] > now:
        return dict(cached[1])
    try:
        resp_body = await get_backend().request("GET", "/api/me")
    except BackendError as exc:
        status = exc.status
        if status == 401 or (status is not None and 200 <= status < 300):
            raise ToolError(AUTH_ERROR_MESSAGE) from exc
        raise
    data = resp_body["data"]
    user = {"username": data["username"], "role": data["role"]}
    _me_cache[pat] = (now + _ME_CACHE_TTL, user)
    return dict(user)
