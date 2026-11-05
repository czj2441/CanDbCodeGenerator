"""PAT HTTP 集成测试 — 双认证、/api/tokens 端点、PAT 权限收口。

覆盖 Task 2 的 HTTP 层行为：
- _authenticate 双认证（Bearer 会话 token 或 PAT），返回 auth_type
- /api/tokens 自助端点（GET 列表 / POST 创建 / DELETE 吊销），仅会话 token
- PAT 权限收口：/api/admin/*、/api/file-permission、/api/change-password、
  /api/logout、/api/tokens* 拒绝 PAT → 403 "此操作不支持个人MCP访问令牌"
- /api/me 接受两种 token
- 改密码只吊销会话 token，绝不吊销 PAT
- 会话 token 滑动续期不回归
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app.auth import service as auth_service
from app.auth.service import AuthService
from app.server import http_handler
from app.server.http_handler import ApiHandler

PAT_REJECT_ERROR = "此操作不支持个人MCP访问令牌"


@pytest.fixture
def server(tmp_path, monkeypatch):
    """tmp 配置的 AuthService + 临时端口上的 ThreadingHTTPServer(ApiHandler)。"""
    monkeypatch.setattr(auth_service, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(auth_service, "USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setattr(auth_service, "USERS_DEFAULT_FILE", str(tmp_path / "users.json.default"))
    monkeypatch.setattr(auth_service, "PATS_FILE", str(tmp_path / "pats.json"))
    monkeypatch.setattr(auth_service, "DATA_DIR", str(tmp_path))
    auth = AuthService()
    monkeypatch.setattr(http_handler, "AUTH_SERVICE", auth)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield auth, f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _req(base, method, path, token=None, body=None):
    """发 HTTP 请求，返回 (status, json_body)。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _login(base, username="admin", password="admin"):
    """登录并返回会话 token。"""
    status, body = _req(base, "POST", "/api/login",
                        body={"username": username, "password": password})
    assert status == 200
    return body["data"]["token"]


def _create_pat(base, session_token, name="ci-bot", expires_days=None):
    """通过 POST /api/tokens 创建 PAT，返回 create_pat 结果（含明文 token）。"""
    payload = {"name": name, "expires_days": expires_days}
    status, body = _req(base, "POST", "/api/tokens", token=session_token, body=payload)
    assert status == 200
    return body["data"]


def test_token_lifecycle_over_http(server):
    """login → POST /api/tokens → GET 列表含新条目 → PAT 调 /api/me 成功 → DELETE → PAT 401。"""
    auth, base = server
    st = _login(base)

    # 创建 PAT
    created = _create_pat(base, st, "ci-bot")
    assert set(created) == {"id", "name", "username", "token", "created_at", "expires_at"}
    pat_token = created["token"]
    assert pat_token.startswith("pat_")
    assert created["username"] == "admin"

    # GET 列表包含新条目（不暴露明文 token）
    status, body = _req(base, "GET", "/api/tokens", token=st)
    assert status == 200
    assert body["success"] is True
    entries = body["data"]
    assert created["id"] in [e["id"] for e in entries]
    assert all("token" not in e and "token_hash" not in e for e in entries)

    # PAT 调 /api/me 成功
    status, body = _req(base, "GET", "/api/me", token=pat_token)
    assert status == 200

    # DELETE 吊销（会话 token）
    status, body = _req(base, "DELETE", f"/api/tokens/{created['id']}", token=st)
    assert status == 200
    assert body["success"] is True

    # 吊销后 PAT 调 /api/me → 401
    status, body = _req(base, "GET", "/api/me", token=pat_token)
    assert status == 401


def test_tokens_endpoints_reject_pat(server):
    """PAT 调 GET/POST/DELETE /api/tokens → 403 且 error 为指定文案；
    未认证调用三端点 → 401（均需会话 token）。"""
    auth, base = server
    st = _login(base)
    created = _create_pat(base, st, "ci-bot")
    pat = created["token"]

    # 未认证 → 401
    for method, path, body in [
        ("GET", "/api/tokens", None),
        ("POST", "/api/tokens", {"name": "anon"}),
        ("DELETE", f"/api/tokens/{created['id']}", None),
    ]:
        status, resp = _req(base, method, path, body=body)
        assert status == 401, f"{method} {path} → {status}"

    # PAT → 403
    for method, path, body in [
        ("GET", "/api/tokens", None),
        ("POST", "/api/tokens", {"name": "evil"}),
        ("DELETE", f"/api/tokens/{created['id']}", None),
    ]:
        status, resp = _req(base, method, path, token=pat, body=body)
        assert status == 403, f"{method} {path} → {status}"
        assert resp["success"] is False
        assert resp["error"] == PAT_REJECT_ERROR

    # PAT 未吊销任何令牌（POST/DELETE 均被拒，无副作用）
    status, body = _req(base, "GET", "/api/tokens", token=st)
    assert status == 200
    assert [e["id"] for e in body["data"]] == [created["id"]]


def test_pat_rejected_on_admin_and_token_endpoints(server):
    """PAT 调 GET /api/admin/users、GET /api/file-permission、POST /api/change-password、
    POST /api/logout → 均 403。"""
    auth, base = server
    st = _login(base)
    pat = _create_pat(base, st, "ci-bot")["token"]

    for method, path, body in [
        ("GET", "/api/admin/users", None),
        ("GET", "/api/file-permission?file=test.dbc", None),
        ("POST", "/api/change-password", {"old_password": "admin", "new_password": "x-new-1"}),
        ("POST", "/api/logout", None),
    ]:
        status, resp = _req(base, method, path, token=pat, body=body)
        assert status == 403, f"{method} {path} → {status}"
        assert resp["success"] is False
        assert resp["error"] == PAT_REJECT_ERROR


def test_me_accepts_pat_and_returns_username(server):
    """PAT 调 /api/me → {"username": ..., "role": ...}。"""
    auth, base = server
    st = _login(base)
    pat = _create_pat(base, st, "ci-bot")["token"]

    status, body = _req(base, "GET", "/api/me", token=pat)
    assert status == 200
    assert body["data"]["username"] == "admin"
    assert body["data"]["role"] == "admin"


def test_change_password_keeps_pat_valid(server):
    """创建 PAT → 会话 token 改密码 → PAT 调 /api/me 仍 200（改密码不吊销 PAT）。"""
    auth, base = server
    st = _login(base)
    pat = _create_pat(base, st, "ci-bot")["token"]

    status, body = _req(base, "POST", "/api/change-password", token=st,
                        body={"old_password": "admin", "new_password": "new-pw-123"})
    assert status == 200

    # PAT 绝不被吊销
    status, body = _req(base, "GET", "/api/me", token=pat)
    assert status == 200
    assert body["data"]["username"] == "admin"


def test_session_token_still_slides(server):
    """会话 token 连续调 /api/me 不失效（滑动续期旧行为不回归）。"""
    auth, base = server
    st = _login(base)

    # 缩短有效期到 60s 后发起请求，滑动续期应将其延长到 TTL
    auth._tokens[st]["expires_at"] = time.time() + 60
    status, body = _req(base, "GET", "/api/me", token=st)
    assert status == 200
    assert auth._tokens[st]["expires_at"] > time.time() + 60  # 被续期

    # 连续调用不失效
    for _ in range(3):
        status, body = _req(base, "GET", "/api/me", token=st)
        assert status == 200


def test_tokens_post_validates_body(server):
    """POST /api/tokens 参数校验：name 1..64 字符串；expires_days null 或 int 1..3650；
    DELETE 未命中 → 404。"""
    auth, base = server
    st = _login(base)

    for body in (
        {"name": "", "expires_days": None},            # name 为空
        {"name": "x" * 65, "expires_days": None},      # name 超长
        {"name": 123, "expires_days": None},           # name 非字符串
        {"name": "ok", "expires_days": 0},             # expires_days 下界外
        {"name": "ok", "expires_days": 3651},          # expires_days 上界外
        {"name": "ok", "expires_days": "30"},          # expires_days 非整数
    ):
        status, resp = _req(base, "POST", "/api/tokens", token=st, body=body)
        assert status == 400, f"{body} → {status}"
        assert resp["success"] is False

    # 边界值合法
    for body in (
        {"name": "x" * 64, "expires_days": 3650},
        {"name": "ok", "expires_days": 1},
    ):
        status, resp = _req(base, "POST", "/api/tokens", token=st, body=body)
        assert status == 200, f"{body} → {status}"
        assert resp["data"]["token"].startswith("pat_")

    # DELETE 未命中 → 404
    status, resp = _req(base, "DELETE", "/api/tokens/nonexistent", token=st)
    assert status == 404
    assert resp["success"] is False
