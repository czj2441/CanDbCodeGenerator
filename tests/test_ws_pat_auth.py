"""WS hello 握手接受 PAT — 单元测试。

验证 app.ws.server._authenticate_ws_token：
- PAT → {"username", "role", "auth_type": "pat"}
- 坏 token → None
- 会话 token → auth_type == "session"（滑动续期语义由 Task 1 保证）
"""

import pytest

from app.auth import service as auth_service
from app.auth.service import AuthService
from app.ws import server as ws_server


@pytest.fixture
def auth(tmp_path, monkeypatch):
    """构造隔离到 tmp_path 的 AuthService，并注入 WS server 使用。"""
    monkeypatch.setattr(auth_service, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(auth_service, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(auth_service, "USERS_DEFAULT_FILE", str(tmp_path / "users.json.default"))
    monkeypatch.setattr(auth_service, "PATS_FILE", str(tmp_path / "pats.json"))
    monkeypatch.setattr(auth_service, "DATA_DIR", str(tmp_path))
    svc = AuthService()
    monkeypatch.setattr(ws_server, "get_auth_service", lambda: svc)
    return svc


def test_ws_hello_accepts_pat_and_rejects_bad_token(auth):
    pat = auth.create_pat("admin", "ci-bot")["token"]

    info = ws_server._authenticate_ws_token(pat)
    assert info == {"username": "admin", "role": "admin", "auth_type": "pat"}

    assert ws_server._authenticate_ws_token("garbage") is None


def test_ws_hello_session_token_unchanged(auth):
    token = auth.create_token("admin")

    info = ws_server._authenticate_ws_token(token)
    assert info is not None
    assert info["username"] == "admin"
    assert info["auth_type"] == "session"
