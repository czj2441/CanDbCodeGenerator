"""PAT（个人访问令牌）— 单元测试。

验证 AuthService 的 PAT 生命周期：
- create_pat：明文 token 仅返回一次，pats.json 只落盘 SHA-256 哈希
- list_pats：隐藏 token 明文与哈希
- revoke_pat：仅本人可吊销，吊销后失效
- validate_pat：过期/未知 token 拒绝
- validate_token_or_pat：会话 token 优先（保留滑动续期），PAT 无滑动续期
- change_password：只吊销会话 token，PAT 保持有效
- delete_user：清空该用户全部 PAT 记录
"""

import hashlib
import time

import pytest

from app.auth import service as auth_service
from app.auth.service import AuthService


@pytest.fixture
def auth(tmp_path, monkeypatch):
    """构造隔离到 tmp_path 的 AuthService（不触碰仓库 config/data）。"""
    monkeypatch.setattr(auth_service, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(auth_service, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(auth_service, "USERS_DEFAULT_FILE", str(tmp_path / "users.json.default"))
    monkeypatch.setattr(auth_service, "PATS_FILE", str(tmp_path / "pats.json"))
    monkeypatch.setattr(auth_service, "DATA_DIR", str(tmp_path))
    return AuthService()


def test_create_pat_returns_plaintext_once_and_stores_hash(auth, tmp_path):
    pat = auth.create_pat("admin", "ci-bot")
    token = pat["token"]

    assert set(pat) == {"id", "name", "username", "token", "created_at", "expires_at"}
    assert token.startswith("pat_")
    assert len(token) == 68
    assert pat["expires_at"] is None  # 未指定 expires_days → 永不过期

    raw = (tmp_path / "pats.json").read_text(encoding="utf-8")
    assert hashlib.sha256(token.encode()).hexdigest() in raw
    assert token not in raw


def test_list_pats_hides_secrets(auth):
    auth.create_pat("admin", "ci-bot", expires_days=30)
    items = auth.list_pats("admin")

    assert len(items) == 1
    assert set(items[0]) == {"id", "name", "created_at", "expires_at", "last_used_at"}


def test_revoke_pat_only_own_and_effective(auth):
    auth.create_user("alice", "pw-alice")
    pat = auth.create_pat("alice", "bot")
    token = pat["token"]

    # 他人 revoke → False 且不生效
    assert auth.revoke_pat("admin", pat["id"]) is False
    assert auth.validate_pat(token) == {"username": "alice", "role": "user"}

    # 本人 revoke → True 且立即失效
    assert auth.revoke_pat("alice", pat["id"]) is True
    assert auth.validate_pat(token) is None


def test_validate_pat_rejects_expired_and_unknown(auth):
    pat = auth.create_pat("admin", "expiring", expires_days=30)
    token = pat["token"]
    assert auth.validate_pat(token) == {"username": "admin", "role": "admin"}

    # 将 store 中 expires_at 改为过去 → 过期拒绝
    record = next(p for p in auth._pats if p["id"] == pat["id"])
    record["expires_at"] = time.time() - 1
    assert auth.validate_pat(token) is None

    # 未知 token → None
    assert auth.validate_pat("pat_bogus") is None


def test_validate_token_or_pat_prefers_session_token_and_keeps_sliding_renewal(auth):
    # 会话 token：auth_type == "session"，且滑动续期保留
    st = auth.create_token("admin")
    auth._tokens[st]["expires_at"] = time.time() + 60
    result = auth.validate_token_or_pat(st)
    assert result == {"username": "admin", "role": "admin", "auth_type": "session"}
    assert auth._tokens[st]["expires_at"] > time.time() + 60  # 被延长

    # PAT：auth_type == "pat"，无滑动续期
    pat = auth.create_pat("admin", "bot", expires_days=30)
    expires_at = auth.list_pats("admin")[0]["expires_at"]
    result = auth.validate_token_or_pat(pat["token"])
    assert result == {"username": "admin", "role": "admin", "auth_type": "pat"}
    assert auth.list_pats("admin")[0]["expires_at"] == expires_at  # 未被延长


def test_change_password_keeps_pat_valid(auth):
    auth.create_user("bob", "old-pw")
    pat = auth.create_pat("bob", "bot")
    st = auth.create_token("bob")

    assert auth.change_password("bob", "old-pw", "new-pw") is True

    # 只吊销会话 token
    assert auth.validate_token(st) is None
    # PAT 绝不被吊销
    assert auth.validate_pat(pat["token"]) == {"username": "bob", "role": "user"}


def test_delete_user_purges_pats(auth):
    auth.create_user("carol", "pw-carol")
    pat = auth.create_pat("carol", "bot")

    assert auth.delete_user("carol") == {"success": True}

    assert auth.list_pats("carol") == []
    assert auth.validate_pat(pat["token"]) is None
