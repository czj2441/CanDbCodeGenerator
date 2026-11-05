"""MCP 端到端集成测试 — 全链路（streamable HTTP）验收。

用官方 mcp SDK 的 streamable-http 客户端 + ClientSession，驱动 uvicorn 起的
``build_app()``（临时端口，Authorization: Bearer <PAT>），走一遍完整工作流：

    whoami → create_file → add_message → add_signal → get_data_errors
    → export properties（含信号名）→ save → close_session → list_files 显示文件

另覆盖两条身份拒止路径：
- 无 Authorization 头 → 连接/调用失败（中间件 401）
- PAT 被吊销后 → 工具调用返回「未认证」错误

说明：
- 仓库未装 pytest-asyncio，沿用 tests/test_mcp_tools_session.py 的 asyncio.run() 约定。
- MCP 服务器在后台线程用 uvicorn 起（``port=0`` 取临时端口），与 live_backend
  夹具（进程内真实后端）分属不同事件循环；工具层的 WS 会话池连接在 uvicorn
  线程的事件循环内创建，随该线程关闭而回收，测试不再显式 aclose。
- 官方 SDK 的 ``streamable_http_client`` 不带 headers 参数，改为传入带
  Authorization 默认头的 ``httpx2.AsyncClient``（``create_mcp_http_client``）。
"""

import asyncio
import json
import threading
import time

import pytest

from app.mcp import auth_context
from app.mcp import backend as backend_mod
from app.mcp.server import build_app
from app.mcp.ws import init_session_pool
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


# ── uvicorn 起停 ──


class _McpServer:
    """在后台线程里跑一个 uvicorn 实例（port=0 临时端口）。"""

    def __init__(self):
        import uvicorn

        self._config = uvicorn.Config(app=build_app(), host="127.0.0.1", port=0, log_level="error")
        self._server = uvicorn.Server(self._config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> str:
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn 启动超时")
            time.sleep(0.01)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture
def mcp_server():
    """起一个 MCP 服务器（临时端口），yield base_url，测试后关闭。"""
    server = _McpServer()
    url = server.start()
    try:
        yield url
    finally:
        server.stop()


def _fresh_pool_and_caches():
    """每个测试用干净的会话池与身份缓存，避免跨测试串扰。"""
    init_session_pool()
    auth_context._me_cache.clear()
    backend_mod._PAT_USERNAME_CACHE.clear()


# ── 结果解析 ──


def _text(result) -> str:
    """取工具返回的文本（content 里的 text 块拼接）。"""
    parts = [getattr(block, "text", "") for block in result.content if getattr(block, "text", None)]
    return "\n".join(parts)


def _json(result) -> dict:
    """解析工具返回的 JSON 文本（dict 返回值 → JSON 字符串块）。"""
    return json.loads(_text(result).strip())


# ── 三个测试 ──


def test_full_workflow_over_mcp(live_backend, monkeypatch, mcp_server):
    """完整工作流：whoami → create_file → add_message → add_signal → get_data_errors
    → export properties（含信号名）→ save → close_session → list_files 显示文件。"""

    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    _fresh_pool_and_caches()
    pat = live_backend["pat_alice"]

    async def run():
        http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {pat}"})
        async with http_client:
            async with streamable_http_client(f"{mcp_server}/mcp", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # 1. whoami
                    who = _json(await session.call_tool("candb_whoami", {}))
                    assert who == {"username": "alice", "role": "user"}

                    # 2. create_file
                    created = _json(await session.call_tool("candb_create_file", {"name": "e2e_wf"}))
                    sid = created["session_id"]
                    assert sid
                    assert created["file_name"] == "e2e_wf.properties"

                    # 3. add_message
                    added = _json(await session.call_tool(
                        "candb_add_message",
                        {"session_id": sid, "message": {"id": 291, "name": "EngineData", "dlc": 8}},
                    ))
                    assert added["id"] == 291

                    # 4. add_signal
                    sig = _json(await session.call_tool(
                        "candb_add_signal",
                        {"session_id": sid, "msg_id": 291,
                         "signal": {"name": "EngineSpeed", "start_bit": 0, "length": 16,
                                    "byte_order": "intel", "factor": 0.5, "unit": "rpm"}},
                    ))
                    assert sig["name"] == "EngineSpeed"

                    # 5. get_data_errors（干净数据 → 无错误）
                    errors = _json(await session.call_tool(
                        "candb_get_data_errors", {"session_id": sid}))
                    assert errors["total"] == 0

                    # 6. export properties（含信号名）
                    exported = _json(await session.call_tool(
                        "candb_export", {"session_id": sid, "format": "properties"}))
                    assert exported["format"] == "properties"
                    assert "EngineSpeed" in exported["content"]
                    assert "EngineData" in exported["content"]

                    # 7. save
                    saved = _json(await session.call_tool("candb_save", {"session_id": sid}))
                    assert saved["message"] == "保存成功"

                    # 8. close_session
                    closed = _json(await session.call_tool("candb_close_session", {"session_id": sid}))
                    assert closed == {"closed": True}

                    # 9. list_files 显示该文件
                    listing = _json(await session.call_tool("candb_list_files", {}))
                    assert listing["total"] >= 1
                    names = [item["file_name"] for item in listing["items"]]
                    assert "e2e_wf.properties" in names

    asyncio.run(run())


def test_mcp_rejects_request_without_pat(live_backend, monkeypatch, mcp_server):
    """无 Authorization 头 → 连接/调用失败（中间件 401 拦截）。"""

    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    _fresh_pool_and_caches()

    async def run():
        # 不带 Authorization 头 → 中间件对首个请求回 401，连接阶段即失败
        http_client = create_mcp_http_client()
        try:
            async with http_client:
                async with streamable_http_client(f"{mcp_server}/mcp", http_client=http_client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
        except Exception as exc:  # 连接/初始化阶段被 401 拦下
            assert isinstance(exc, Exception)
            return
        pytest.fail("无 PAT 的请求应被 401 拒绝，却成功完成了初始化")

    asyncio.run(run())


def test_mcp_rejects_revoked_pat(live_backend, monkeypatch, mcp_server):
    """PAT 被吊销后 → 工具调用返回「未认证」错误。"""

    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    _fresh_pool_and_caches()
    pat = live_backend["pat_alice"]
    auth = live_backend["auth"]

    # 先吊销 alice 的 PAT（后端 /api/me 校验将 401）
    token_id = auth.list_pats("alice")[0]["id"]
    assert auth.revoke_pat("alice", token_id) is True
    auth_context._me_cache.clear()  # 确保不命中缓存

    async def run():
        http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {pat}"})
        async with http_client:
            async with streamable_http_client(f"{mcp_server}/mcp", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("candb_whoami", {})
                    assert result.is_error is True
                    assert "未认证" in _text(result)

    asyncio.run(run())
