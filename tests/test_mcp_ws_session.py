"""MCP WS 会话层测试 — 往返/错误映射、会话池按用户隔离、心跳保活、空闲 TTL、锁释放。

覆盖 Task 6 的 WS 会话层行为（真实后端，live_backend 夹具）：
- CallResult 往返与错误映射（ok → CallResult；error → BackendError）
- SessionPool 按 (username, session_id) 隔离：A 用户拿不到 B 用户的连接
- ping 保活：短 TTL 环境下连接因心跳保持，空闲 TTL 不误杀
- 空闲 TTL：无活动超过 TTL → 连接关闭且池中消失
- close_session：release_lock 后同一文件可再 open（无 FILE_LOCKED）

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_identity.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest

import app.services.session_manager as session_manager_mod
from app.mcp.backend import BackendClient
from app.mcp.errors import BackendError
from app.mcp.ws import CallResult, WsConnection, init_session_pool
from app.services import get_session_manager


def test_call_roundtrip_and_error_mapping(live_backend):
    """用 alice PAT 调 get_sessions 成功（CallResult 往返）；
    edit 不存在 session → BackendError.code == "SESSION_NOT_FOUND"。"""

    async def run():
        pool = init_session_pool(idle_ttl=60.0, ping_interval=0.2)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            assert isinstance(ctrl, WsConnection)

            # 往返：ok 响应 → CallResult
            result = await ctrl.call("get_sessions", {"current_session_id": ""})
            assert isinstance(result, CallResult)
            assert isinstance(result.data, list)          # list_history 返回条目列表
            assert result.new_session_id is None          # 非创建类消息不产生新会话

            # 错误映射：error 响应 → BackendError（语义码透传）
            with pytest.raises(BackendError) as exc_info:
                await ctrl.call("edit_signal", {"session_id": "no-such-session"})
            assert exc_info.value.code == "SESSION_NOT_FOUND"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_session_pool_isolates_users(live_backend):
    """bob 用 alice 的 session_id 调用 → 报错（(username, session_id) 隔离）；
    两用户连接对象互不相同。"""

    async def run():
        pool = init_session_pool(idle_ttl=60.0, ping_interval=0.2)
        try:
            alice = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            bob = BackendClient(live_backend["base_url"], live_backend["pat_bob"])

            conn_a, result = await alice.open_session("new_file", {"name": "iso_a", "session_id": ""})
            sid = result.new_session_id
            assert sid

            # alice 查自己的会话 → 命中同一连接对象
            assert await alice.get_session(sid) is conn_a

            # bob 用 alice 的 session_id 查池 → 报错（池 key 含 username）
            with pytest.raises(BackendError) as exc_info:
                await bob.get_session(sid)
            assert exc_info.value.code == "SESSION_NOT_FOUND"

            # bob 即使绕过池、用自己的连接操作 alice 的会话 → 后端权限拦截
            bob_ctrl = await bob.control()
            with pytest.raises(BackendError) as exc_info:
                await bob_ctrl.call("edit_signal", {
                    "session_id": sid, "msg_id": 1,
                    "sig_name": "s", "field": "comment", "value": "x",
                })
            assert exc_info.value.code == "permission_denied"

            # 两用户控制连接互不相同
            alice_ctrl = await alice.control()
            assert isinstance(alice_ctrl, WsConnection)
            assert isinstance(bob_ctrl, WsConnection)
            assert alice_ctrl is not bob_ctrl
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_ping_keeps_connection_alive(live_backend, monkeypatch):
    """短 TTL 环境下 45s 内连接因 ping 保持（空闲 TTL 不误杀）。

    - 空闲 TTL 注入 1.5s（短 TTL 环境），观察窗口 4.5s（45s 语义窗口 ×0.1 缩放），
      窗口内无任何调用，仅靠 0.1s 心跳保活；因活动（调用+心跳）刷新空闲计时，
      连接不被空闲 TTL 误杀。
    - 后端心跳 TTL 同步缩到 0.5s（30s → 0.5s）：无心跳的会话会被心跳清理回收，
      本连接的会话因 ping 续期而存活（保活 + 后端锁续期）。
    """
    monkeypatch.setattr(session_manager_mod, "HEARTBEAT_TIMEOUT", 0.5)
    monkeypatch.setattr(session_manager_mod, "HEARTBEAT_CHECK_INTERVAL", 0.2)
    mgr = get_session_manager()
    mgr._stop_heartbeat_checker()
    mgr._start_heartbeat_checker()  # 以短间隔重启心跳清理

    async def run():
        pool = init_session_pool(idle_ttl=1.5, ping_interval=0.1)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            conn, result = await client.open_session("new_file", {"name": "keepalive", "session_id": ""})
            sid = result.new_session_id
            assert sid

            await asyncio.sleep(4.5)  # 语义 45s 窗口：> 空闲 TTL 3 倍、> 心跳 TTL 9 倍

            # 连接因 ping 保持（未被关闭）
            assert conn.closed is False
            # 空闲 TTL 不误杀（仍在池中，get_session 命中同一连接）
            assert await client.get_session(sid) is conn
            # 后端会话/锁仍在：心跳已由 ping 续期，未被心跳清理回收
            status = await conn.call("get_status", {"session_id": sid})
            assert status.data.get("session_id") == sid
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_idle_ttl_closes_connection(live_backend):
    """无调用超过 TTL → 连接关闭且池中消失。

    空闲计时按连接活动（调用 + 心跳）刷新，故心跳间隔注入 600s（窗口内不发心跳），
    模拟彻底闲置：idle_ttl=0.4s 内无任何活动 → 自动关连接出池。
    """

    async def run():
        pool = init_session_pool(idle_ttl=0.4, ping_interval=600.0)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            conn, result = await client.open_session("create_file", {"name": "idle_ttl"})
            sid = result.new_session_id
            assert sid

            await asyncio.sleep(1.2)  # 无活动超过 TTL 的 3 倍

            assert conn.closed is True  # 连接关闭
            with pytest.raises(BackendError) as exc_info:
                await client.get_session(sid)  # 池中消失
            assert exc_info.value.code == "SESSION_NOT_FOUND"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_close_session_releases_lock(live_backend):
    """close_session 后 bob 可 open 同一文件（无 FILE_LOCKED）。

    bob 自己的会话持锁期间再 open 同一文件 → FILE_LOCKED；
    close_session 发 release_lock（abort: False）后文件锁释放，可重新 open。
    """

    async def run():
        pool = init_session_pool(idle_ttl=60.0, ping_interval=0.2)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_bob"])
            conn1, result1 = await client.open_session("new_file", {"name": "lockfile", "session_id": ""})
            sid1 = result1.new_session_id
            assert sid1

            # 锁被 sid1 持有期间，bob 再 open 同一文件 → FILE_LOCKED
            with pytest.raises(BackendError) as exc_info:
                await client.open_session("load_file", {"file_name": "lockfile.properties"})
            assert exc_info.value.code == "FILE_LOCKED"

            await client.close_session(sid1)

            # close_session 后 bob 可 open 同一文件（无 FILE_LOCKED）
            conn2, result2 = await client.open_session("load_file", {"file_name": "lockfile.properties"})
            assert result2.new_session_id
            assert await client.get_session(result2.new_session_id) is conn2
        finally:
            await pool.aclose_all()

    asyncio.run(run())
