"""MCP 身份链路测试 — ASGI 中间件、require_user 校验缓存、canmatrix_whoami 工具。

覆盖 Task 5 的身份链路行为：
- build_app() 中间件：无 Authorization 头 → 401 {"error": "unauthorized"}
- 带 Authorization: Bearer <PAT> 时 contextvar 取到 PAT
- canmatrix_whoami 经 require_user 返回 {"username", "role"}（httpx.MockTransport 桩 /api/me）
- 同一 PAT 60 秒内两次 require_user 仅打一次 /api/me
"""

import asyncio

import httpx
import pytest

from app.mcp import auth_context
from app.mcp.auth_context import get_current_pat, require_user, set_current_pat
from app.mcp.backend import BackendClient
from app.mcp.server import build_app, canmatrix_whoami

ME_OK = {"success": True, "data": {"username": "alice", "role": "user"}}


@pytest.fixture(autouse=True)
def _clear_me_cache():
    """清空 /api/me 身份缓存，避免跨测试串扰。"""
    auth_context._me_cache.clear()
    yield
    auth_context._me_cache.clear()


def _stub_backend(monkeypatch, pat, handler):
    """把 auth_context.get_backend 换成带 httpx.MockTransport 的 BackendClient（不打真实后端）。"""
    client = BackendClient(
        base_url="http://backend.test",
        token=pat,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(auth_context, "get_backend", lambda: client)
    return client


def test_middleware_rejects_missing_header():
    """ASGI 请求无 Authorization → 401 {"error": "unauthorized"}。"""

    async def run():
        transport = httpx.ASGITransport(app=build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
            return await client.get("/mcp")

    resp = asyncio.run(run())
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_middleware_sets_pat():
    """带 Authorization: Bearer <PAT> 时 contextvar 取到 PAT。

    走中性路径：中间件对所有 http 路径一致处理，内层 /mcp 处理器依赖会话管理器
    生命周期（生产由 uvicorn 启动），不在本测试范围。
    """

    async def run():
        transport = httpx.ASGITransport(app=build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp.test") as client:
            await client.get("/", headers={"Authorization": "Bearer tok-middleware"})
        return get_current_pat()

    assert asyncio.run(run()) == "tok-middleware"


def test_whoami_returns_username(monkeypatch):
    """httpx.MockTransport 桩 /api/me → canmatrix_whoami 返回 {"username", "role"}。"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ME_OK)

    _stub_backend(monkeypatch, "tok-whoami", handler)

    async def run():
        set_current_pat("tok-whoami")
        return await canmatrix_whoami()

    assert asyncio.run(run()) == {"username": "alice", "role": "user"}
    assert [r.url.path for r in seen] == ["/api/me"]
    assert seen[0].headers["Authorization"] == "Bearer tok-whoami"


def test_require_user_caches_me_calls(monkeypatch):
    """同一 PAT 60 秒内两次 require_user 仅打一次 /api/me。"""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ME_OK)

    _stub_backend(monkeypatch, "tok-cache", handler)

    async def run():
        set_current_pat("tok-cache")
        first = await require_user()
        second = await require_user()
        return first, second

    first, second = asyncio.run(run())
    assert first == {"username": "alice", "role": "user"}
    assert second == {"username": "alice", "role": "user"}
    assert len(seen) == 1
