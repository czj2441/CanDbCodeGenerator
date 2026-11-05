"""MCP 服务器 — MCPServer 实例、PAT 身份中间件、ASGI 应用组装与工具注册。"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp, Receive, Scope, Send

from app.mcp.auth_context import require_user, set_current_pat
from app.mcp.tools_history import register_tools as _register_history
from app.mcp.tools_messages import register_tools as _register_messages
from app.mcp.tools_session import register_tools as _register_session
from app.mcp.tools_signals import register_tools as _register_signals
from app.mcp.tools_value_tables import register_tools as _register_value_tables

mcp = MCPServer("candb_codegenerator_mcp")


class PatIdentityMiddleware:
    """ASGI 中间件 — 从 Authorization: Bearer 提取 PAT 写入 contextvar。

    头缺失或不含 Bearer 令牌 → 401 {"error": "unauthorized"}；
    非 http 作用域（如 lifespan）直接透传。
    """

    def __init__(self, app: ASGIApp):
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        auth = ""
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                auth = value.decode("latin-1")
                break
        token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
        if not token:
            body = json.dumps({"error": "unauthorized"}).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})
            return
        set_current_pat(token)
        await self._app(scope, receive, send)


def build_app() -> ASGIApp:
    """构建 ASGI 应用：mcp.streamable_http_app() 外包 PAT 身份中间件。

    显式关闭 DNS rebinding 防护：MCP 走 PAT 认证、面向非浏览器 AI 客户端，
    且需允许局域网设备直接以 IP 访问（Host 头非 localhost），
    故不启用 Host/Origin 白名单校验。
    """
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return PatIdentityMiddleware(mcp.streamable_http_app(transport_security=transport_security))


@mcp.tool(description="返回当前令牌对应的用户名与角色", annotations=ToolAnnotations(read_only_hint=True))
async def candb_whoami() -> dict:
    """返回当前令牌对应的用户名与角色。"""
    return await require_user()


# 注册文件/会话工具（Task 7）
_register_session(mcp)
# 注册报文/信号/值表/校验历史工具（Task 8-11）
_register_messages(mcp)
_register_signals(mcp)
_register_value_tables(mcp)
_register_history(mcp)
