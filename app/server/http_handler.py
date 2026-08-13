"""
http_handler.py — ApiHandler（静态文件 + HTTP 路由）
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any

from app.version import VERSION

logger = logging.getLogger(__name__)

# SESSION_MGR 由 lifecycle 模块在导入时注入。
# ⚠️ 必须在 HTTP server 启动前赋值（见 lifecycle.py 顺序约束注释）。
SESSION_MGR = None

# AUTH_SERVICE 由 lifecycle 模块在导入时注入。
AUTH_SERVICE = None


def _resp(success: bool, data: Any = None, error: str = "", details: dict | None = None) -> dict:
    """统一JSON响应格式。"""
    result = {"success": success, "data": data, "error": error}
    if details is not None:
        result["details"] = details
    return result


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    _last_status: int = 200  # tracked for compact log

    def log_message(self, fmt: str, *args: Any) -> None:
        """Suppress default access log — we emit a single compact line per request."""
        pass

    # ── CORS ──

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Id, Authorization")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    # ── 工具方法 ──

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()
        self._last_status = status

    # ── 认证辅助 ──

    def _authenticate(self) -> dict | None:
        """从 Authorization 头提取 token 并验证。返回 {username, role} 或 None。"""
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        if not AUTH_SERVICE:
            return None
        return AUTH_SERVICE.validate_token(token)

    def _require_auth(self) -> dict | None:
        """要求认证，失败时自动发送 401 响应并返回 None。"""
        user = self._authenticate()
        if not user:
            self._send_json(401, _resp(False, error="认证失败，请重新登录"))
            return None
        return user

    def _require_admin(self) -> dict | None:
        """要求 admin 角色，失败时自动发送 403 响应并返回 None。"""
        user = self._require_auth()
        if user and not AUTH_SERVICE.is_admin(user["username"]):
            self._send_json(403, _resp(False, error="仅管理员可执行此操作"))
            return None
        return user

    def _read_json_body(self) -> dict:
        """读取 JSON 请求体。"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _path_parts(self) -> list[str]:
        """返回路径部分（不含query string），以'/'分割并过滤空字符串。"""
        parsed = urllib.parse.urlparse(self.path)
        return [p for p in parsed.path.split("/") if p]

    # ── 静态文件服务 ──

    def _serve_static(self) -> None:
        """Serve static files. New Vue frontend in dist/, legacy HTML in root."""
        import mimetypes

        parsed = urllib.parse.urlparse(self.path)
        filepath = parsed.path.lstrip("/")
        if not filepath:
            filepath = "index.html"

        safe_path = os.path.normpath(filepath)
        if safe_path.startswith("..") or os.path.isabs(safe_path):
            self._send_json(403, _resp(False, error="Forbidden"))
            return

        # PyInstaller 打包后 __file__ 指向 _MEIPASS 临时目录，前端资源在那里
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            # 从 app/server/http_handler.py 上溯 3 层到项目根目录
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Vue frontend assets live in dist/
        full_path = os.path.join(base_dir, "dist", safe_path)
        if not os.path.isfile(full_path):
            full_path = os.path.join(base_dir, safe_path)

        # realpath 边界检查：防御 symlink 和编码绕过
        full_path = os.path.realpath(full_path)
        base_real = os.path.realpath(base_dir)
        if not full_path.startswith(base_real + os.sep) and full_path != base_real:
            self._send_json(403, _resp(False, error="Forbidden"))
            return

        if not os.path.isfile(full_path):
            self._send_json(404, _resp(False, error="Not found"))
            return

        mime_type, _ = mimetypes.guess_type(full_path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self._last_status = 200
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)
            self.wfile.flush()
        except Exception as e:
            logger.error("Static file read error: %s", e)
            self._send_json(500, _resp(False, error=str(e)))

    # ── 路由 ──

    def do_GET(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            # 白名单路径无需认证
            if parts == ["api", "status"]:
                self._get_status()
            elif parts == ["api", "version"]:
                self._get_version()
            elif parts == ["api", "diag"]:
                self._get_diag()
            elif parts == ["api", "export"]:
                self._get_export()
            # 认证路由
            elif parts == ["api", "me"]:
                self._get_me()
            elif parts == ["api", "file-permission"]:
                self._get_file_permission()
            # 管理员路由
            elif parts == ["api", "admin", "users"]:
                user = self._require_admin()
                if user:
                    self._get_admin_users()
            else:
                self._serve_static()
        except Exception as e:
            logger.error("do_GET error: %s", e, exc_info=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except Exception:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            logger.info("[API] %d GET %s +%.1fms", self._last_status, self.path, elapsed)

    def do_POST(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if parts == ["api", "release"]:
                self._post_release()
            elif parts == ["api", "login"]:
                self._post_login()
            elif parts == ["api", "logout"]:
                self._post_logout()
            elif parts == ["api", "change-password"]:
                self._post_change_password()
            elif parts == ["api", "admin", "users"]:
                user = self._require_admin()
                if user:
                    self._post_admin_create_user()
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except Exception as e:
            logger.error("do_POST error: %s", e, exc_info=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except Exception:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            logger.info("[API] %d POST %s +%.1fms", self._last_status, self.path, elapsed)

    def do_PUT(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if len(parts) == 5 and parts[:3] == ["api", "admin", "users"] and parts[4] == "role":
                user = self._require_admin()
                if user:
                    self._put_admin_user_role(parts[3])
            elif len(parts) == 5 and parts[:3] == ["api", "admin", "users"] and parts[4] == "password":
                user = self._require_admin()
                if user:
                    self._put_admin_user_password(parts[3])
            elif parts == ["api", "admin", "file-permission"]:
                user = self._require_admin()
                if user:
                    self._put_admin_file_permission()
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found"))
        except Exception as e:
            logger.error("do_PUT error: %s", e, exc_info=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except Exception:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            logger.info("[API] %d PUT %s +%.1fms", self._last_status, self.path, elapsed)

    def do_DELETE(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if len(parts) == 4 and parts[:3] == ["api", "admin", "users"]:
                user = self._require_admin()
                if user:
                    self._delete_admin_user(parts[3], user["username"])
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found"))
        except Exception as e:
            logger.error("do_DELETE error: %s", e, exc_info=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except Exception:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            logger.info("[API] %d DELETE %s +%.1fms", self._last_status, self.path, elapsed)

    # ── 端点实现 ──

    def _get_status(self) -> None:
        self._send_json(200, _resp(True, {"status": "ok"}))

    def _get_version(self) -> None:
        self._send_json(200, _resp(True, VERSION))

    def _post_release(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        sid = params.get("sid", [""])[0]
        abort = params.get("abort", [""])[0] in ("1", "true", "yes")
        if sid:
            SESSION_MGR.release_session(sid, abort=abort)
        self._send_json(200, _resp(True))

    def _get_export(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        sid = params.get("sid", [""])[0]
        fmt = params.get("fmt", ["properties"])[0]
        force = params.get("force", ["0"])[0] == "1"

        if not sid:
            self._send_json(400, _resp(False, error="sid is required"))
            return

        session = SESSION_MGR.get(sid)
        if not session:
            self._send_json(404, _resp(False, error="Session not found"))
            return

        # DBC 导出前校验：存在数据完整性错误时拒绝导出（force=True 跳过校验）
        if fmt == "dbc" and not force:
            with session.db.with_lock():
                export_errors = session.db.validate_for_dbc_export()
            if export_errors:
                self._send_json(422, _resp(False,
                    error=f"存在 {len(export_errors)} 个数据错误，无法导出 DBC",
                    details={"errors": export_errors[:10], "total": len(export_errors)}))
                return

        try:
            if fmt == "dbc":
                content = session.db.to_dbc_str()
                ext = ".dbc"
                mime = "application/octet-stream"
            elif fmt == "properties":
                content = session.db.to_properties_str()
                ext = ".properties"
                mime = "text/plain"
            elif fmt == "c_header":
                content = session.db.to_c_header_str()
                mime = "text/plain"
            elif fmt == "c_source":
                content = session.db.to_c_source_str()
                mime = "text/plain"
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            logger.error("Export failed: session=%s fmt=%s error=%s", sid[:8] if sid else '', fmt, e)
            self._send_json(500, _resp(False, error=f"Export failed: {e}"))
            return

        if fmt in ("c_header", "c_source"):
            from app.io.c_code_gen import c_export_filename
            file_name = c_export_filename(session.db.name or "export",
                                          'h' if fmt == "c_header" else 'c')
        else:
            file_name = session.db.name or "export"
            if not file_name.endswith(ext):
                file_name = file_name.rsplit(".", 1)[0] + ext

        # 净化文件名：剥离 CR/LF（防响应拆分）和双引号（防头注入）
        file_name = file_name.replace('\r', '').replace('\n', '').replace('"', '')

        payload = content.encode("utf-8")
        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{file_name}"')
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()
        logger.info("Export: session=%s fmt=%s file=%s size=%d bytes",
                    sid[:8], fmt, file_name, len(payload))

    def _get_diag(self) -> None:
        try:
            from app.ws.transport import WsTransport
        except ImportError:
            self._send_json(404, _resp(False, error="WS module not available"))
            return
        transport = getattr(self.__class__, '_ws_transport', None)
        if not transport or not transport.diag.enabled:
            self._send_json(404, _resp(False, error="Diagnostics not enabled"))
            return
        self._send_json(200, _resp(True, transport.diag.snapshot()))

    # ── 认证端点 ──

    def _post_login(self) -> None:
        """POST /api/login — 用户登录。"""
        try:
            body = self._read_json_body()
        except Exception:
            self._send_json(400, _resp(False, error="无效的请求体"))
            return
        username = body.get("username", "").strip()
        password = body.get("password", "")
        if not username or not password:
            self._send_json(400, _resp(False, error="用户名和密码不能为空"))
            return
        result = AUTH_SERVICE.verify_password(username, password)
        if not result:
            self._send_json(401, _resp(False, error="用户名或密码错误"))
            return
        token = AUTH_SERVICE.create_token(username)
        self._send_json(200, _resp(True, {
            "token": token,
            "username": result["username"],
            "role": result["role"],
            "must_change_password": result.get("must_change_password", False),
        }))

    def _post_logout(self) -> None:
        """POST /api/logout — 用户登出。"""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            AUTH_SERVICE.revoke_token(auth_header[7:])
        self._send_json(200, _resp(True))

    def _get_me(self) -> None:
        """GET /api/me — 验证 token，返回用户信息（页面刷新后恢复登录态用）。"""
        user = self._require_auth()
        if not user:
            return
        user_data = {
            "username": user["username"],
            "role": user["role"],
        }
        # 检查是否需要强制改密
        for u in AUTH_SERVICE._users:
            if u["username"] == user["username"]:
                user_data["must_change_password"] = u.get("must_change_password", False)
                break
        self._send_json(200, _resp(True, user_data))

    def _post_change_password(self) -> None:
        """POST /api/change-password — 修改密码。"""
        user = self._require_auth()
        if not user:
            return
        try:
            body = self._read_json_body()
        except Exception:
            self._send_json(400, _resp(False, error="无效的请求体"))
            return
        old_pwd = body.get("old_password", "")
        new_pwd = body.get("new_password", "")
        if not old_pwd or not new_pwd:
            self._send_json(400, _resp(False, error="旧密码和新密码不能为空"))
            return
        if len(new_pwd) < 4:
            self._send_json(400, _resp(False, error="新密码长度不能少于 4 位"))
            return
        ok = AUTH_SERVICE.change_password(user["username"], old_pwd, new_pwd)
        if not ok:
            self._send_json(400, _resp(False, error="旧密码错误"))
            return
        # 密码修改成功后重新签发 token
        new_token = AUTH_SERVICE.create_token(user["username"])
        self._send_json(200, _resp(True, {"token": new_token}))

    # ── 管理员端点 ──

    def _get_admin_users(self) -> None:
        """GET /api/admin/users — 列出所有用户。"""
        users = AUTH_SERVICE.list_users()
        # 追加每个用户的文件数量
        for u in users:
            u["file_count"] = len(AUTH_SERVICE._get_user_files(u["username"]))
        self._send_json(200, _resp(True, users))

    def _post_admin_create_user(self) -> None:
        """POST /api/admin/users — 创建用户。"""
        try:
            body = self._read_json_body()
        except Exception:
            self._send_json(400, _resp(False, error="无效的请求体"))
            return
        username = body.get("username", "").strip()
        password = body.get("password", "")
        role = body.get("role", "user")
        if not username or not password:
            self._send_json(400, _resp(False, error="用户名和密码不能为空"))
            return
        if len(password) < 4:
            self._send_json(400, _resp(False, error="密码长度不能少于 4 位"))
            return
        try:
            result = AUTH_SERVICE.create_user(username, password, role)
            self._send_json(200, _resp(True, result))
        except ValueError as e:
            self._send_json(409, _resp(False, error=str(e)))

    def _delete_admin_user(self, username: str, operator: str) -> None:
        """DELETE /api/admin/users/{username} — 删除用户。"""
        result = AUTH_SERVICE.delete_user(username, operator)
        if result["success"]:
            self._send_json(200, _resp(True))
        else:
            self._send_json(409, _resp(False, error=result["error"],
                                        details={"files": result.get("files", [])}))

    def _put_admin_user_role(self, username: str) -> None:
        """PUT /api/admin/users/{username}/role — 修改用户角色。"""
        try:
            body = self._read_json_body()
        except Exception:
            self._send_json(400, _resp(False, error="无效的请求体"))
            return
        role = body.get("role", "")
        result = AUTH_SERVICE.update_user_role(username, role)
        if result["success"]:
            self._send_json(200, _resp(True))
        else:
            self._send_json(409, _resp(False, error=result["error"]))

    def _put_admin_user_password(self, username: str) -> None:
        """PUT /api/admin/users/{username}/password — 管理员重置密码。"""
        try:
            body = self._read_json_body()
        except Exception:
            self._send_json(400, _resp(False, error="无效的请求体"))
            return
        password = body.get("password", "")
        if not password or len(password) < 4:
            self._send_json(400, _resp(False, error="密码长度不能少于 4 位"))
            return
        ok = AUTH_SERVICE.reset_user_password(username, password)
        if ok:
            self._send_json(200, _resp(True))
        else:
            self._send_json(404, _resp(False, error=f"用户 '{username}' 不存在"))

    def _put_admin_file_permission(self) -> None:
        """PUT /api/admin/file-permission — 转移文件所有权 / 接管无主文件。"""
        try:
            body = self._read_json_body()
        except Exception:
            self._send_json(400, _resp(False, error="无效的请求体"))
            return
        file_name = body.get("file_name", "")
        new_owner = body.get("new_owner", "")
        if not file_name or not new_owner:
            self._send_json(400, _resp(False, error="file_name 和 new_owner 不能为空"))
            return
        if not AUTH_SERVICE.user_exists(new_owner):
            self._send_json(400, _resp(False, error=f"用户 '{new_owner}' 不存在"))
            return
        AUTH_SERVICE.set_file_permission(file_name, new_owner)
        self._send_json(200, _resp(True, {"file_name": file_name, "owner": new_owner}))

    def _get_file_permission(self) -> None:
        """GET /api/file-permission?file=xxx — 获取文件所有者信息。"""
        user = self._require_auth()
        if not user:
            return
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        file_name = params.get("file", [""])[0]
        if not file_name:
            self._send_json(400, _resp(False, error="file 参数不能为空"))
            return
        perm = AUTH_SERVICE.get_file_permission(file_name)
        if perm:
            self._send_json(200, _resp(True, {
                "file_name": file_name,
                "owner": perm.get("owner", ""),
                "created_at": perm.get("created_at", 0),
            }))
        else:
            self._send_json(200, _resp(True, {
                "file_name": file_name,
                "owner": "",
                "created_at": 0,
            }))
