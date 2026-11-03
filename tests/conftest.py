"""pytest 公共夹具 — live_backend：进程内真实后端（HTTP + WS + 认证 + 会话管理）。

按 app/server/lifecycle.py 的启动序列在临时端口上组装真实后端，供 MCP 层
集成测试复用。所有会写盘的路径（auth 配置 / 会话数据 / 快照）均隔离到 tmp_path，
避免测试写真实仓库（Task 1 的教训：USERS_DEFAULT_FILE 漏掉就会写真实 config/）。
"""

import socket
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from app.auth import service as auth_service
from app.models import CanDatabase
from app.server import http_handler
from app.server.http_handler import ApiHandler
from app.services import session_manager as session_manager_mod
from app.services import snapshot as snapshot_mod


def _find_port_pair() -> int:
    """找一个端口 P 使 P 与 P+1 同时空闲（HTTP 用 P、WS 用 P+1，与生产一致）。"""
    for _ in range(100):
        s1 = socket.socket()
        try:
            s1.bind(("127.0.0.1", 0))
            port = s1.getsockname()[1]
        finally:
            s1.close()
        s2 = socket.socket()
        try:
            s2.bind(("127.0.0.1", port + 1))
            return port
        except OSError:
            continue
        finally:
            s2.close()
    raise RuntimeError("未找到可用的连续端口对")


@pytest.fixture
def live_backend(tmp_path, monkeypatch):
    """进程内真实后端：按 lifecycle 启动序列组装，预置 alice/bob 各一个 PAT。

    yield: {"base_url", "ws_url", "pat_alice", "pat_bob", "auth"}。
    """
    # ── 路径隔离：五个 auth 路径都要（漏 USERS_DEFAULT_FILE 会写真实仓库），
    #    另隔离会话数据目录与快照目录（WS 断连/销毁会写快照） ──
    monkeypatch.setattr(auth_service, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(auth_service, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(auth_service, "USERS_DEFAULT_FILE", str(tmp_path / "users.json.default"))
    monkeypatch.setattr(auth_service, "PATS_FILE", str(tmp_path / "pats.json"))
    monkeypatch.setattr(auth_service, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(session_manager_mod, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(snapshot_mod, "SNAPSHOT_DIR", str(tmp_path / "snapshots"))

    # ── 按 lifecycle 启动序列组装（延迟导入：lifecycle 导入时会初始化全局服务，
    #    必须在路径隔离之后进行） ──
    from app.server.lifecycle import _register_all_handlers

    auth = auth_service.init_auth_service()
    monkeypatch.setattr(auth_service, "_auth_service", auth)  # teardown 自动还原
    mgr = session_manager_mod.init_session_manager(data_dir=str(tmp_path / "data"))
    mgr.set_model_factory(CanDatabase)
    monkeypatch.setattr(session_manager_mod, "_session_manager", mgr)

    # ── 预置用户 alice 与 bob，各发一个 PAT ──
    auth.create_user("alice", "alice-pass-123", role="user")
    auth.create_user("bob", "bob-pass-123", role="user")
    pat_alice = auth.create_pat("alice", "test-alice")["token"]
    pat_bob = auth.create_pat("bob", "test-bob")["token"]

    # ── HTTP 服务（临时端口） ──
    monkeypatch.setattr(http_handler, "SESSION_MGR", mgr)
    monkeypatch.setattr(http_handler, "AUTH_SERVICE", auth)
    port = _find_port_pair()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), ApiHandler)
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()

    # ── WS 服务（HTTP 端口 + 1，与生产一致） ──
    from app.ws.router import MessageRouter
    from app.ws.server import WsServer
    from app.ws.transport import WsTransport

    ws_transport = WsTransport(host="127.0.0.1", port=port + 1)
    ws_router = MessageRouter(ws_transport, mgr, auth_service=auth)
    _register_all_handlers(ws_router, mgr, ws_transport)
    ws_server = WsServer(ws_transport, ws_router)
    ws_server.start_in_thread()
    monkeypatch.setattr(ApiHandler, "_ws_transport", ws_transport, raising=False)

    # 等 WS 服务就绪（websockets.serve 就绪后 _ws_server 才非 None）
    deadline = time.monotonic() + 5
    while getattr(ws_server, "_ws_server", None) is None:
        if time.monotonic() > deadline:
            raise RuntimeError("WS 服务启动超时")
        time.sleep(0.01)

    try:
        yield {
            "base_url": f"http://127.0.0.1:{port}",
            "ws_url": f"ws://127.0.0.1:{port + 1}",
            "pat_alice": pat_alice,
            "pat_bob": pat_bob,
            "auth": auth,
        }
    finally:
        ws_server.shutdown()
        httpd.shutdown()
        httpd.server_close()
        http_thread.join(timeout=5)
        mgr._stop_heartbeat_checker()
