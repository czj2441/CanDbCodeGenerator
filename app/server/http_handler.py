"""
http_handler.py — ApiHandler（静态文件 + HTTP 路由）
"""

import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Any

from app.version import VERSION

# SESSION_MGR 由 lifecycle 模块在导入时注入
SESSION_MGR = None


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Id")

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
        if safe_path.startswith(".."):
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
            self._send_json(500, _resp(False, error=str(e)))

    # ── 路由 ──

    def do_GET(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if parts == ["api", "status"]:
                self._get_status()
            elif parts == ["api", "diag"]:
                self._get_diag()
            elif parts == ["api", "export"]:
                self._get_export()
            elif parts == ["api", "version"]:
                self._get_version()
            else:
                self._serve_static()
        except Exception as e:
            print(f"[ERROR] do_GET: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} GET {self.path} +{elapsed:.1f}ms")

    def do_POST(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if parts == ["api", "release"]:
                self._post_release()
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except Exception as e:
            print(f"[ERROR] do_POST: {e}", flush=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} POST {self.path} +{elapsed:.1f}ms")

    def do_PUT(self) -> None:
        self._last_status = 404
        try:
            self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except:
            pass
        print(f"[API] 404 PUT {self.path} (moved to WS)")

    def do_DELETE(self) -> None:
        self._last_status = 404
        try:
            self._send_json(404, _resp(False, error="Not found. All CRUD operations moved to WebSocket."))
        except:
            pass
        print(f"[API] 404 DELETE {self.path} (moved to WS)")

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

        if not sid:
            self._send_json(400, _resp(False, error="sid is required"))
            return

        session = SESSION_MGR.get(sid)
        if not session:
            self._send_json(404, _resp(False, error="Session not found"))
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
                ext = "_signals.h"
                mime = "text/plain"
            elif fmt == "c_source":
                content = session.db.to_c_source_str()
                ext = "_signals.c"
                mime = "text/plain"
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(500, _resp(False, error=f"Export failed: {e}"))
            return

        file_name = session.db.name or "export"
        if not file_name.endswith(ext):
            file_name = file_name.rsplit(".", 1)[0] + ext

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
