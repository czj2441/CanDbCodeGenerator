"""MCP WS 会话层测试 — 往返/错误映射、会话池按用户隔离、ping 后端续期、空闲 TTL、锁释放。

覆盖 Task 6 的 WS 会话层行为（真实后端，live_backend 夹具）：
- CallResult 往返与错误映射（ok → CallResult；error → BackendError）
- SessionPool 按 (username, session_id) 隔离：A 用户拿不到 B 用户的连接
- ping 的职责是后端侧续期：有 ping 后端会话存活、无 ping 被后端心跳超时回收
- 空闲 TTL 只认 call()：有调用不触发；无调用超过 TTL（心跳照跑）→ 连接关闭且池中消失
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
    """ping 的职责是后端侧续期：有 ping 后端会话存活，无 ping 被后端心跳超时回收。

    注入短后端心跳超时（30s → 0.5s，检查 30s → 0.2s）并观察 1.5s（3 倍超时）：
    - 有 ping 的连接（心跳 0.1s）：会话心跳持续续期 → get_status 成功（会话/锁存活）；
    - 无 ping 的连接（心跳 600s，窗口内不发）：会话心跳断供 → 被后端心跳清理回收
      （get_status → SESSION_NOT_FOUND）。
    会话池空闲 TTL 注入 60s（长）以免干扰本测试（TTL 只认 call()，
    见 test_idle_ttl_closes_connection）。
    """
    monkeypatch.setattr(session_manager_mod, "HEARTBEAT_TIMEOUT", 0.5)
    monkeypatch.setattr(session_manager_mod, "HEARTBEAT_CHECK_INTERVAL", 0.2)
    mgr = get_session_manager()
    mgr._stop_heartbeat_checker()
    mgr._start_heartbeat_checker()  # 以短间隔重启心跳清理

    async def run():
        pool = init_session_pool(idle_ttl=60.0, ping_interval=0.1)
        conn_b = None
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            conn_a, result_a = await client.open_session("new_file", {"name": "keepalive", "session_id": ""})
            sid_a = result_a.new_session_id
            assert sid_a

            # 对照组：无 ping 的连接（心跳间隔 600s，窗口内不发心跳）
            conn_b = await WsConnection.connect(
                live_backend["ws_url"], live_backend["pat_bob"], ping_interval=600.0)
            result_b = await conn_b.call("new_file", {"name": "nopong", "session_id": ""})
            sid_b = result_b.new_session_id
            assert sid_b

            await asyncio.sleep(1.5)  # > 后端心跳超时 0.5s 的 3 倍（窗口内两连接均无调用）

            # 有 ping：后端会话/锁存活（心跳已由 ping 续期）
            assert conn_a.closed is False
            status_a = await conn_a.call("get_status", {"session_id": sid_a})
            assert status_a.data.get("session_id") == sid_a

            # 无 ping：后端会话被心跳清理回收
            with pytest.raises(BackendError) as exc_info:
                await conn_b.call("get_status", {"session_id": sid_b})
            assert exc_info.value.code == "SESSION_NOT_FOUND"
        finally:
            if conn_b is not None:
                await conn_b.close()
            await pool.aclose_all()

    asyncio.run(run())


def test_idle_ttl_closes_connection(live_backend):
    """无调用超过 TTL → 连接关闭且池中消失；TTL 只认 call()（有调用则不触发）。

    心跳间隔注入 0.1s（心跳照常在跑、不影响计时），空闲 TTL=1.0s：
    - t≈0.6s 补一次调用 → TTL 不触发，t≈1.2s 连接仍在池中（有调用则 TTL 不触发）；
    - 此后无任何工具调用 → TTL 到期自动关连接出池。
    """

    async def run():
        pool = init_session_pool(idle_ttl=1.0, ping_interval=0.1)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            conn, result = await client.open_session("create_file", {"name": "idle_ttl"})
            sid = result.new_session_id
            assert sid

            await asyncio.sleep(0.6)
            await conn.call("get_status", {"session_id": sid})  # 调用刷新空闲计时（TTL 只认 call()）

            await asyncio.sleep(0.6)  # 距上次调用 0.6s < TTL 1.0s
            assert conn.closed is False                # 有调用则 TTL 不触发
            assert await client.get_session(sid) is conn

            await asyncio.sleep(1.5)  # 无调用超过 TTL（心跳照常在跑，但不刷新计时）
            assert conn.closed is True                 # 连接关闭
            with pytest.raises(BackendError) as exc_info:
                await client.get_session(sid)          # 池中消失
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
