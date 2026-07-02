#!/usr/bin/env python3
"""
CanMatrix Editor - REST API Server
解耦前后端架构：前端只负责UI渲染，所有数据操作通过REST API。
使用标准库 http.server，不引入重量级依赖。

会话模型：
  - 每个浏览器标签页对应一个独立 session
  - 每个 session 绑定一个数据文件，所有变更自动落盘
  - 浏览器意外关闭后可通过 localStorage 中的 session_id 恢复
"""

import json
import math
import os
import signal
import atexit
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

try:
    from http.server import ThreadingHTTPServer
    THREADING_AVAILABLE = True
except ImportError:
    from socketserver import ThreadingMixIn
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        pass
    THREADING_AVAILABLE = True

# ── 会话管理器 ──────────────────────────────────────────────────────────────────
from session_manager import init_session_manager, get_session_manager, FileLockedError

SESSION_MGR = init_session_manager()

# ── 数据模型（统一从 models.py 导入）────────────────────────────────────
from models import Signal, Message, CanDatabase


# ── 全局会话（单用户桌面应用场景）─────────────────────────────────────────────

# ── 临时 DB 降级（无 session 时）───────────────────────────────────────────────

_temp_db_instance: CanDatabase | None = None

def _temp_db() -> CanDatabase:
    """返回匿名临时数据库（仅内存，不落盘）。"""
    global _temp_db_instance
    if _temp_db_instance is None:
        _temp_db_instance = CanDatabase("Temporary")
    return _temp_db_instance


# ── 注入模型工厂 ──
SESSION_MGR.set_model_factory(CanDatabase)


def _pure_file_name(session) -> str:
    """从 session 中提取纯文件名（去掉 session_id 前缀）。"""
    base = os.path.basename(session.file_path)
    if base.startswith(session.id + "_"):
        base = base[len(session.id) + 1:]
    return base


def _resp(success: bool, data: Any = None, error: str = "", details: dict | None = None) -> dict:
    """统一JSON响应格式。"""
    result = {"success": success, "data": data, "error": error}
    if details is not None:
        result["details"] = details
    return result


# ── API 请求处理器 ────────────────────────────────────────────────────────────

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

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            return json.loads(raw)
        except Exception as e:
            print(f"[DEBUG] _read_body error: {e}")
            return {}

    def _url_params(self) -> dict[str, str]:
        parsed = urllib.parse.urlparse(self.path)
        return urllib.parse.parse_qs(parsed.query)

    def _get_download(self) -> None:
        """GET /api/download?format=dbc&sid=xxx - 直接返回文件内容（触发浏览器保存对话框）。

        通过 Content-Disposition: attachment 让浏览器/WebView 原生弹出保存位置。
        支持从 URL 查询参数读取 sid（window.location 无法设置自定义请求头）。
        """
        params = self._url_params()
        fmt = (params.get("format", ["dbc"])[0]).lower()
        sid = params.get("sid", [""])[0]

        # 获取数据库
        db = None
        if sid:
            s = SESSION_MGR.get(sid)
            if s:
                db = s.db
        if db is None:
            db = _temp_db()

        # 生成导出内容
        try:
            if fmt == "dbc":
                content = db.to_dbc_str()
                mime = "text/plain"
                ext = ".dbc"
            elif fmt == "toml":
                content = db.to_toml_str()
                mime = "text/plain"
                ext = ".toml"
            elif fmt == "json":
                content = json.dumps(db.to_dict(), ensure_ascii=False, indent=2)
                mime = "application/json"
                ext = ".json"
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(500, _resp(False, error=f"Export failed: {e}"))
            return

        # 文件名
        file_name = db.name or "export"
        if not file_name.endswith(ext):
            file_name = file_name.rsplit(".", 1)[0] + ext

        # 直接返回二进制流 + Content-Disposition
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
        self._last_status = 200

    def _path_parts(self) -> list[str]:
        """返回路径部分（不含query string），以'/'分割并过滤空字符串。"""
        parsed = urllib.parse.urlparse(self.path)
        return [p for p in parsed.path.split("/") if p]

    # ── 会话管理 ──

    def _get_db(self) -> CanDatabase:
        """从请求头提取 session_id，返回对应的 CanDatabase 实例。
        若无有效 session，自动创建匿名临时 session（仅内存，不落盘）。
        """
        session_id = self.headers.get("X-Session-Id", "")
        if session_id:
            s = SESSION_MGR.get(session_id)
            if s:
                return s.db
        # 降级：无 session 时使用匿名临时 DB
        return _temp_db()

    def _auto_save(self) -> None:
        """（已废弃）变更后不再立即落盘，由定时自动保存器处理。"""
        pass

    def _push_undo(self, snapshot: dict) -> None:
        """推入撤销快照（如果存在 session）。"""
        session_id = self.headers.get("X-Session-Id", "")
        if session_id:
            SESSION_MGR.push_undo(session_id, snapshot)

    def _session_id_from_path(self) -> str | None:
        """从路径中取 session_id（用于 /api/session/{id} 类端点）。"""
        parts = self._path_parts()
        if len(parts) >= 3 and parts[0] == "api":
            if parts[1] == "session":
                return parts[2] if len(parts) >= 3 else None
            if parts[1] == "sessions":
                return None
        return None

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
            base_dir = os.path.dirname(os.path.abspath(__file__))

        # Legacy HTML always served from root
        if safe_path == "canmatrix_web_editor.html":
            full_path = os.path.join(base_dir, safe_path)
        else:
            # New Vue frontend assets live in dist/
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
            self._handle_GET()
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

    def _handle_GET(self) -> None:
        parts = self._path_parts()
        if parts == ["api", "status"]:
            self._get_status()
        elif parts == ["api", "messages"]:
            self._get_messages()
        elif parts[0:2] == ["api", "messages"] and len(parts) == 3:
            self._get_message(parts[2])
        elif parts[0:2] == ["api", "messages"] and len(parts) == 4 and parts[3] == "signal-errors":
            self._get_signal_errors(parts[2])
        elif parts == ["api", "summary"]:
            self._get_summary()
        elif parts[0:2] == ["api", "session"] and len(parts) == 3:
            self._get_session(parts[2])
        elif len(parts) == 4 and parts[0:2] == ["api", "session"] and parts[3] == "info":
            # GET /api/session/{id}/info - 轻量级检查 session 状态（不含数据库）
            self._get_session_info(parts[2])
        elif parts == ["api", "sessions"]:
            self._get_sessions()
        elif parts == ["api", "download"]:
            self._get_download()
        else:
            self._serve_static()

    def do_POST(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            self._handle_POST()
        except Exception as e:
            print(f"[ERROR] do_POST: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} POST {self.path} +{elapsed:.1f}ms")

    def _handle_POST(self) -> None:
        parts = self._path_parts()
        if parts == ["api", "new"]:
            self._post_new()
        elif parts == ["api", "import"]:
            self._post_import()
        elif parts == ["api", "export"]:
            self._post_export()
        elif parts == ["api", "save"]:
            self._post_save()
        elif parts == ["api", "release"]:
            self._post_release()
        elif parts == ["api", "heartbeat"]:
            self._post_heartbeat()
        elif parts == ["api", "steal"]:
            self._post_steal()
        elif parts == ["api", "undo"]:
            self._post_undo()
        elif parts == ["api", "redo"]:
            self._post_redo()
        elif parts == ["api", "messages"]:
            self._post_messages()
        elif parts == ["api", "session"]:
            self._post_session()
        elif len(parts) == 4 and parts[0:2] == ["api", "session"] and parts[3] == "load":
            # POST /api/session/{id}/load
            self._post_session_load(parts[2])
        elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals" and parts[4] == "batch":
            # POST /api/messages/{id}/signals/batch
            self._post_signals_batch(parts[2])
        elif len(parts) == 4 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
            # POST /api/messages/{id}/signals
            self._post_signals(parts[2])
        else:
            self._send_json(404, _resp(False, error="Not found"))

    def do_PUT(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if len(parts) == 3 and parts[0:2] == ["api", "messages"]:
                self._put_message(parts[2])
            elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
                self._put_signal(parts[2], parts[4])
            elif parts == ["api", "session"]:
                self._put_session()
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found"))
        except Exception as e:
            print(f"[ERROR] do_PUT: {e}", flush=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} PUT {self.path} +{elapsed:.1f}ms")

    def do_DELETE(self) -> None:
        t_start = time.monotonic()
        self._last_status = 200
        try:
            parts = self._path_parts()
            if len(parts) == 3 and parts[0:2] == ["api", "messages"]:
                self._delete_message(parts[2])
            elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
                self._delete_signal(parts[2], parts[4])
            elif len(parts) == 3 and parts[0:2] == ["api", "session"]:
                self._delete_session(parts[2])
            else:
                self._last_status = 404
                self._send_json(404, _resp(False, error="Not found"))
        except Exception as e:
            print(f"[ERROR] do_DELETE: {e}", flush=True)
            self._last_status = 500
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass
        finally:
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] {self._last_status} DELETE {self.path} +{elapsed:.1f}ms")

    # ── 端点实现 ──

    # ── Session ──

    def _post_session(self) -> None:
        """POST /api/session - 创建新会话。
        Body: {name: str, content: dict|None}
        返回: {session_id, file_name}
        """
        body = self._read_body()
        db_name = body.get("name", "Untitled")
        content = body.get("content", None)

        if content:
            db = CanDatabase.from_dict(content)
            db.name = db_name
        else:
            db = CanDatabase(db_name)

        file_name = f"{db_name}.toml"
        session_id = SESSION_MGR.create(file_name, db)
        self._send_json(201, _resp(True, {
            "session_id": session_id,
            "file_name": file_name,
            "message_count": len(db.messages),
            "signal_count": db.total_signals(),
        }))

    def _get_session(self, session_id: str) -> None:
        """GET /api/session/{id} - 恢复会话，返回会话元数据（不含完整数据库，避免大对象序列化）。"""
        s = SESSION_MGR.restore(session_id)
        if not s:
            self._send_json(404, _resp(False, error="Session not found or expired"))
            return
        self._send_json(200, _resp(True, {
            "session_id": s.id,
            "file_name": _pure_file_name(s),
            "message_count": len(s.db.messages),
            "signal_count": s.db.total_signals(),
        }))

    def _get_sessions(self) -> None:
        """GET /api/sessions - 列出所有历史会话（含磁盘文件）。"""
        # 获取当前会话 ID（用于排除自身锁定）
        current_sid = self.headers.get("X-Session-Id", "")
        sessions = SESSION_MGR.list_history(exclude_session=current_sid)
        self._send_json(200, _resp(True, sessions))

    def _get_session_info(self, session_id: str) -> None:
        """GET /api/session/{id}/info - 轻量级检查 session 状态（不含数据库）。
        
        用于编辑器页面定期检查文件锁状态。
        如果 session 被其他标签页抢占，返回 409 Conflict。
        """
        s = SESSION_MGR.get(session_id)
        if not s:
            self._send_json(404, _resp(False, error="Session not found or expired"))
            return
        
        # 检查文件是否被其他 session 占用（排除当前 session）
        if SESSION_MGR.is_file_locked(s.file_path, exclude_session=session_id):
            self._send_json(409, _resp(False, error=f"File '{_pure_file_name(s)}' is opened in another tab"))
            return
        
        self._send_json(200, _resp(True, {
            "session_id": s.id,
            "file_name": _pure_file_name(s),
            "message_count": len(s.db.messages),
            "signal_count": s.db.total_signals(),
            "is_locked": False,
        }))

    def _delete_session(self, session_id: str) -> None:
        """DELETE /api/session/{id} - 删除历史会话（内存 + 磁盘）。"""
        ok = SESSION_MGR.delete_history(session_id)
        if ok:
            self._send_json(200, _resp(True, {"deleted": session_id}))
        else:
            self._send_json(404, _resp(False, error="Session not found"))

    def _post_session_load(self, session_id: str) -> None:
        """POST /api/session/{id}/load - 恢复历史会话（直接复用原 session，不创建副本）。"""
        # 获取当前会话 ID（用于排除自身锁定）
        current_sid = self.headers.get("X-Session-Id", "")
        try:
            s = SESSION_MGR.restore(session_id, exclude_session=current_sid)
        except FileLockedError as e:
            self._send_json(409, _resp(False, error=str(e)))
            return
        if not s:
            self._send_json(404, _resp(False, error="Session not found or corrupted"))
            return
        self._send_json(200, _resp(True, {
            "session_id": s.id,
            "file_name": _pure_file_name(s),
            "message_count": len(s.db.messages),
            "signal_count": s.db.total_signals(),
        }))

    def _put_session(self) -> None:
        """PUT /api/session - 更新数据库名称并重命名文件。"""
        session_id = self.headers.get("X-Session-Id", "")
        if not session_id:
            self._send_json(400, _resp(False, error="Session ID required"))
            return
        body = self._read_body()
        new_name = body.get("name", "")
        if not new_name:
            self._send_json(400, _resp(False, error="Name is required"))
            return
        ok = SESSION_MGR.rename(session_id, new_name)
        if not ok:
            self._send_json(404, _resp(False, error="Session not found"))
            return
        s = SESSION_MGR.get(session_id)
        self._send_json(200, _resp(True, {
            "name": s.db.name,
            "file_name": _pure_file_name(s),
        }))

    # ── Status ──

    def _get_status(self) -> None:
        db = self._get_db()
        session_id = self.headers.get("X-Session-Id", "")
        s = SESSION_MGR.get(session_id) if session_id else None
        
        status_data = {
            "message_count": len(db.messages),
            "signal_count": db.total_signals(),
            "modified": db.modified,
            "session_id": session_id,
            "file_name": _pure_file_name(s) if s else None,
        }
        
        # 添加撤销/重做计数（如果有 session）
        if s:
            status_data["undo_count"] = len(s.undo_stack)
            status_data["redo_count"] = len(s.redo_stack)
            status_data["save_error"] = s.save_error
        
        self._send_json(200, _resp(True, status_data))

    def _get_messages(self) -> None:
        db = self._get_db()
        data = [
            {
                "id": mid,
                "id_hex": f"0x{mid:X}",
                "name": m.name,
                "dlc": m.dlc,
                "cycle_time": m.cycle_time,
                "signal_count": len(m.signals),
            }
            for mid, m in sorted(db.messages.items())
        ]
        self._send_json(200, _resp(True, data))

    def _get_message(self, id_str: str) -> None:
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        msg = db.get_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._send_json(200, _resp(True, msg.to_dict()))

    def _get_signal_errors(self, id_str: str) -> None:
        """GET /api/messages/{id}/signal-errors - 获取报文所有信号布局错误。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        errors = db.validate_all_signals(msg_id)
        self._send_json(200, _resp(True, errors))

    def _get_summary(self) -> None:
        db = self._get_db()
        msgs = list(db.messages.values())
        self._send_json(200, _resp(True, {
            "name": db.name,
            "message_count": len(msgs),
            "signal_count": db.total_signals(),
            "modified": db.modified,
            "messages": [
                {
                    "id": m.id,
                    "id_hex": f"0x{m.id:X}",
                    "name": m.name,
                    "dlc": m.dlc,
                    "signal_count": len(m.signals),
                }
                for m in sorted(msgs, key=lambda m: m.id)
            ],
        }))

    def _post_new(self) -> None:
        body = self._read_body()
        name = (body or {}).get("name", "Untitled")

        session_id = self.headers.get("X-Session-Id", "")
        # 先保存当前会话（确保旧数据不丢失）
        if session_id:
            SESSION_MGR.save(session_id)

        new_db = CanDatabase(name)
        file_name = f"{name}.toml"
        new_session_id = SESSION_MGR.create(file_name, new_db)

        self._send_json(200, _resp(True, {
            "name": new_db.name,
            "session_id": new_session_id,
        }))

    def _post_save(self) -> None:
        """POST /api/save - 手动保存当前会话到磁盘。
        
        立即保存会话数据，成功后重置 modified 标志。
        用于用户主动触发保存（Ctrl+S 或点击保存按钮）。
        支持从 X-Session-Id 请求头或 URL 查询参数 ?sid=xxx 读取 session ID，
        以便 navigator.sendBeacon() 使用（beacon 不支持自定义请求头）。
        """
        session_id = self.headers.get("X-Session-Id", "")
        if not session_id:
            # 支持从 URL 查询参数读取（用于 sendBeacon）
            params = self._url_params()
            sid_list = params.get("sid", [])
            if sid_list:
                session_id = sid_list[0]
        if not session_id:
            self._send_json(400, _resp(False, error="Session ID required"))
            return
        
        try:
            success = SESSION_MGR.save(session_id)
            if success:
                self._send_json(200, _resp(True, data={"message": "保存成功"}))
            else:
                self._send_json(500, _resp(False, error="保存失败：会话不存在"))
        except Exception as e:
            print(f"[ERROR] save failed: {e}")
            self._send_json(500, _resp(False, error=f"保存失败: {str(e)}"))

    def _post_undo(self) -> None:
        """POST /api/undo - 执行撤销操作。
        
        从后端撤销栈中弹出最近的操作，执行回滚并自动保存。
        返回更新后的 undo_count 和 redo_count。
        """
        session_id = self.headers.get("X-Session-Id", "")
        if not session_id:
            self._send_json(400, _resp(False, error="Session ID required"))
            return
        
        result = SESSION_MGR.undo(session_id)
        status_code = 200 if result["success"] else 400
        self._send_json(status_code, _resp(result["success"], data=result.get("data"), error=result.get("message") if not result["success"] else None))

    def _post_redo(self) -> None:
        """POST /api/redo - 执行重做操作。
        
        从后端重做栈中弹出最近的操作，执行重做并自动保存。
        返回更新后的 undo_count 和 redo_count。
        """
        session_id = self.headers.get("X-Session-Id", "")
        if not session_id:
            self._send_json(400, _resp(False, error="Session ID required"))
            return
        
        result = SESSION_MGR.redo(session_id)
        status_code = 200 if result["success"] else 400
        self._send_json(status_code, _resp(result["success"], data=result.get("data"), error=result.get("message") if not result["success"] else None))

    def _post_release(self) -> None:
        """POST /api/release - 释放当前 session 的文件锁。

        支持查询参数 ?abort=1 以同时销毁 session（丢弃未保存变更）。
        支持从 X-Session-Id 请求头或 URL 查询参数 ?sid=xxx 读取 session ID，
        以便 navigator.sendBeacon() 使用（beacon 不支持自定义请求头）。
        常规 API 调用也可通过 JSON body {"abort": true} 传递。
        """
        sid = self.headers.get("X-Session-Id", "")
        abort = False
        if not sid:
            params = self._url_params()
            sid_list = params.get("sid", [])
            if sid_list:
                sid = sid_list[0]
            abort_list = params.get("abort", [])
            if abort_list:
                abort = abort_list[0] in ("1", "true", "yes")
        else:
            body = self._read_body() or {}
            abort = body.get("abort", False)
        if sid:
            SESSION_MGR.release_session(sid, abort=abort)
        self._send_json(200, _resp(True))

    def _post_heartbeat(self) -> None:
        """POST /api/heartbeat - 编辑器标签页心跳上报。

        Body: {session_id: str}
        前端每 10 秒发送一次，后端记录心跳时间用于自动释放离线标签页的文件锁。
        """
        body = self._read_body() or {}
        sid = body.get("session_id", "")
        if not sid:
            self._send_json(400, _resp(False, error="Session ID required"))
            return
        ok = SESSION_MGR.update_heartbeat(sid)
        self._send_json(200, _resp(True, {"active": ok}))

    def _post_steal(self) -> None:
        """POST /api/steal - 抢占指定 session 的文件锁。
        Body: {target_session_id: str}
        释放目标 session 的文件锁，让当前 session 可以打开该文件。
        不保存目标 session 的数据——抢占仅变更归属权，不应落盘。
        """
        body = self._read_body()
        target_sid = body.get("target_session_id", "")
        if not target_sid:
            self._send_json(400, _resp(False, error="target_session_id is required"))
            return
        
        # 检查目标 session 是否存在
        target_session = SESSION_MGR.get(target_sid)
        if not target_session:
            self._send_json(404, _resp(False, error="Target session not found"))
            return
        
        # 释放目标 session 的文件锁（不保存数据）
        SESSION_MGR.release_session(target_sid)
        self._send_json(200, _resp(True, {"released_session": target_sid}))

    def _post_import(self) -> None:
        """导入文件内容（前端已读取文件，发送JSON）。"""
        body = self._read_body()
        fmt = body.get("format", "json")
        content = body.get("content", "")
        filename = body.get("filename", "")

        try:
            if fmt == "toml":
                import toml
                new_db = CanDatabase.from_toml_str(content)
            elif fmt == "json":
                data = json.loads(content)
                new_db = CanDatabase.from_dict(data)
            elif fmt == "dbc":
                # 使用 cantools 解析 DBC 内容
                import cantools.database
                import tempfile
                
                # 将 DBC 内容写入临时文件，供 cantools 解析
                with tempfile.NamedTemporaryFile(mode='w', suffix='.dbc', delete=False, encoding='utf-8') as tmp_file:
                    tmp_file.write(content)
                    tmp_file_path = tmp_file.name
                
                try:
                    # 使用 cantools 解析 DBC 文件
                    can_db = cantools.database.load_file(tmp_file_path)
                    
                    # 转换为内部 CanDatabase 模型
                    new_db = CanDatabase(name=filename.replace('.dbc', '') if filename else 'imported_dbc')
                    
                    for can_msg in can_db.messages:
                        # 提取周期时间
                        cycle_time = 0
                        try:
                            if can_msg.cycle_time is not None:
                                cycle_time = int(can_msg.cycle_time)
                        except Exception:
                            pass
                        
                        # 提取发送者
                        sender = ""
                        try:
                            senders = getattr(can_msg, "senders", None)
                            if senders and isinstance(senders, list) and len(senders) > 0:
                                sender = str(senders[0])
                        except Exception:
                            pass
                        
                        comment = can_msg.comment or ""
                        
                        msg = Message.from_dict({
                            "id": can_msg.frame_id,
                            "name": can_msg.name,
                            "dlc": can_msg.length,
                            "cycle_time": cycle_time,
                            "comment": str(comment),
                            "sender": sender,
                        })
                        
                        for can_sig in can_msg.signals:
                            # 映射 cantools byte_order 到内部格式
                            byte_order = can_sig.byte_order
                            if hasattr(byte_order, "name"):
                                order_str = byte_order.name.lower()
                            else:
                                order_str = str(byte_order).lower()
                            # 标准化为内部格式: intel/motorola
                            if order_str in ("little", "little_endian", "intel"):
                                order_str = "intel"
                            elif order_str in ("big", "big_endian", "motorola"):
                                order_str = "motorola"
                            
                            # 多路复用信息
                            mux_mode = "none"
                            mux_value = 0
                            if can_sig.is_multiplexer:
                                mux_mode = "multiplexer"
                            elif can_sig.multiplexer_ids is not None and len(can_sig.multiplexer_ids) > 0:
                                mux_mode = "multiplexed"
                                mux_value = can_sig.multiplexer_ids[0] if can_sig.multiplexer_ids else 0
                            
                            sig = Signal.from_dict({
                                "name": can_sig.name,
                                "start_bit": can_sig.start,
                                "length": can_sig.length,
                                "byte_order": order_str,
                                "is_signed": can_sig.is_signed,
                                "factor": can_sig.scale if can_sig.scale is not None else 1.0,
                                "offset": can_sig.offset if can_sig.offset is not None else 0.0,
                                "min_val": can_sig.minimum if can_sig.minimum is not None else 0.0,
                                "max_val": can_sig.maximum if can_sig.maximum is not None else 0.0,
                                "unit": can_sig.unit or "",
                                "comment": can_sig.comment or "",
                                "receivers": can_sig.receivers[:] if can_sig.receivers else [],
                                "multiplexer_mode": mux_mode,
                                "multiplexer_value": mux_value,
                            })
                            msg.signals.append(sig)
                        
                        new_db.add_message(msg)
                finally:
                    # 清理临时文件
                    try:
                        os.unlink(tmp_file_path)
                    except Exception:
                        pass
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(400, _resp(False, error=f"Import failed: {e}"))
            return

        # 替换当前会话的 DB 并标记已修改
        session_id = self.headers.get("X-Session-Id", "")
        if session_id:
            s = SESSION_MGR.get(session_id)
            if s:
                s.db = new_db
                # 导入后立即保存（全量替换，数据量大，值得即时持久化）
                SESSION_MGR.save(session_id)

        self._send_json(200, _resp(True, {"message_count": len(new_db.messages)}))

    def _post_export(self) -> None:
        """导出数据库为指定格式并返回内容。"""
        db = self._get_db()
        body = self._read_body()
        fmt = body.get("format", "json") if body else "json"

        try:
            if fmt == "json":
                content = json.dumps(db.to_dict(), ensure_ascii=False, indent=2)
            elif fmt == "toml":
                content = db.to_toml_str()
            elif fmt == "dbc":
                content = db.to_dbc_str()
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(500, _resp(False, error=f"Export failed: {e}"))
            return

        self._send_json(200, _resp(True, {"content": content, "format": fmt}))

    def _post_messages(self) -> None:
        """POST /api/messages - 添加报文。"""
        db = self._get_db()
        body = self._read_body()
        msg_id = _parse_id(body.get("id", ""))
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid or missing message ID"))
            return
        # ★ 字段级校验（name 非空、DLC 范围）
        if "name" in body:
            name = body["name"]
            if not isinstance(name, str) or not name.strip():
                self._send_json(400, _resp(False, error="Message name cannot be empty",
                    details={"error_code": "message_name_empty", "field": "name"}))
                return
        if "dlc" in body:
            dlc = body["dlc"]
            if dlc is None or not isinstance(dlc, (int, float)):
                self._send_json(400, _resp(False, error="Invalid DLC value",
                    details={"error_code": "dlc_invalid", "field": "dlc"}))
                return
            try:
                dlc_int = int(dlc)
            except (ValueError, TypeError):
                self._send_json(400, _resp(False, error="Invalid DLC value",
                    details={"error_code": "dlc_invalid", "field": "dlc"}))
                return
            if dlc_int not in db.VALID_DLC_VALUES:
                self._send_json(400, _resp(False, error=f"Invalid DLC, valid: {sorted(db.VALID_DLC_VALUES)}",
                    details={"error_code": "dlc_invalid", "field": "dlc",
                             "valid_values": sorted(db.VALID_DLC_VALUES)}))
                return
        msg = Message.from_dict(body)
        msg.id = msg_id
        if not db.add_message(msg):
            self._send_json(409, _resp(False, error=f"Message 0x{msg_id:X} already exists"))
            return
        
        # 推入撤销栈（message_add）
        self._push_undo({
            "type": "message_add",
            "msgId": msg_id,
            "data": msg.to_dict()
        })
        
        self._send_json(201, _resp(True, msg.to_dict()))

    def _put_message(self, id_str: str) -> None:
        """PUT /api/messages/{id} - 更新报文。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        
        # 获取旧值（用于撤销）
        msg = db.get_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        
        # ★ 字段级校验（name 非空、DLC 范围、DLC 缩小冲突）
        ok, err, info = db.validate_message_fields(msg_id, body)
        if not ok:
            self._send_json(400, _resp(False, error=err, details=info))
            return
        
        old_values = {}
        for key in body.keys():
            if key != "id" and hasattr(msg, key):
                old_values[key] = getattr(msg, key)
        
        # 允许更新id（即移动key）
        new_id = _parse_id(body.get("id", msg_id))
        if new_id is None:
            self._send_json(400, _resp(False, error="Invalid new ID"))
            return
        if new_id != msg_id:
            if not db.move_message(msg_id, new_id):
                self._send_json(409, _resp(False, error=f"Message 0x{new_id:X} already exists"))
                return
            msg_id = new_id
        ok = db.update_message(msg_id, **{k: v for k, v in body.items() if k != "id"})
        if not ok:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        
        # 推入撤销栈（message_update）
        if old_values:
            self._push_undo({
                "type": "message_update",
                "msgId": msg_id,
                "prev": old_values,
                "next": {k: v for k, v in body.items() if k != "id"}
            })
        
        self._send_json(200, _resp(True, db.get_message(msg_id).to_dict()))

    def _delete_message(self, id_str: str) -> None:
        """DELETE /api/messages/{id} - 删除报文。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        msg = db.get_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        
        # 保存报文数据（用于撤销）
        msg_data = msg.to_dict()
        
        db.remove_message(msg_id)
        
        # 推入撤销栈（message_delete）
        self._push_undo({
            "type": "message_delete",
            "data": msg_data
        })
        
        self._send_json(200, _resp(True, {"deleted": f"0x{msg_id:X}"}))

    def _post_signals(self, id_str: str) -> None:
        """POST /api/messages/{id}/signals - 添加信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        msg = db.get_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        
        # ★ 信号字段级校验
        if "name" in body:
            name = body["name"]
            if not isinstance(name, str) or not name.strip():
                self._send_json(400, _resp(False, error="Signal name cannot be empty",
                    details={"error_code": "signal_name_empty", "field": "name"}))
                return
            for existing in msg.signals:
                if existing.name == name.strip():
                    self._send_json(400, _resp(False, error=f"Signal name '{name}' already exists",
                        details={"error_code": "signal_name_duplicate", "field": "name",
                                 "name": name}))
                    return
        if "length" in body:
            length = body["length"]
            if length is None or not isinstance(length, (int, float)) or int(length) < 1:
                self._send_json(400, _resp(False, error="Signal length must be at least 1",
                    details={"error_code": "signal_length_invalid", "field": "length"}))
                return
        for num_field in ("factor", "offset", "min_val", "max_val"):
            if num_field in body:
                val = body[num_field]
                if val is None or not isinstance(val, (int, float)):
                    self._send_json(400, _resp(False, error=f"Invalid {num_field} value",
                        details={"error_code": "invalid_number", "field": num_field}))
                    return
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    self._send_json(400, _resp(False, error=f"{num_field} cannot be NaN or Infinity",
                        details={"error_code": "invalid_number", "field": num_field}))
                    return
        if "factor" in body and body["factor"] == 0:
            self._send_json(400, _resp(False, error="Factor cannot be zero",
                details={"error_code": "factor_zero", "field": "factor"}))
            return
        
        sig = Signal.from_dict(body)

        # 校验（前端已自动顺延，后端仅做防御性验证）
        ok, err, _info = db.validate_signal(msg_id, sig)
        if not ok:
            self._send_json(400, _resp(False, error=err, details=_info))
            return

        if not db.add_signal_to_message(msg_id, sig):
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        
        # 推入撤销栈（signal_add）
        self._push_undo({
            "type": "signal_add",
            "msgId": msg_id,
            "sigUuid": sig.uuid,
            "data": sig.to_dict()
        })

        self._send_json(201, _resp(True, sig.to_dict()))

    def _post_signals_batch(self, id_str: str) -> None:
        """POST /api/messages/{id}/signals/batch - 批量添加信号（原子撤销）。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        signals_data = body if isinstance(body, list) else body.get("signals", [])
        if not signals_data or not isinstance(signals_data, list):
            self._send_json(400, _resp(False, error="Expected non-empty signals array"))
            return

        created_signals = []
        errors = []
        for i, sig_dict in enumerate(signals_data):
            sig = Signal.from_dict(sig_dict)
            # 校验（前端已自动顺延，后端仅做防御性验证）
            ok, err, _info = db.validate_signal(msg_id, sig)
            if not ok:
                errors.append({"index": i, "name": sig.name, "error": err})
                continue
            if db.add_signal_to_message(msg_id, sig):
                created_signals.append(sig)
            else:
                errors.append({"index": i, "name": sig.name, "error": f"Message 0x{msg_id:X} not found"})

        if not created_signals:
            self._send_json(400, _resp(False, error="No signals created", details=errors))
            return

        # 推入单个 batch_signal_add 撤销快照
        self._push_undo({
            "type": "batch_signal_add",
            "msgId": msg_id,
            "signals": [
                {"uuid": sig.uuid, "data": sig.to_dict()}
                for sig in created_signals
            ]
        })

        self._send_json(201, _resp(True, {
            "created": [sig.to_dict() for sig in created_signals],
            "errors": errors,
            "count": len(created_signals)
        }))

    def _put_signal(self, id_str: str, idx_str: str) -> None:
        """PUT /api/messages/{id}/signals/{uuid} - 更新信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        
        # 获取旧值（用于撤销）
        msg = db.get_message(msg_id)
        sig = next((s for s in msg.signals if s.uuid == idx_str), None) if msg else None
        if not sig:
            self._send_json(404, _resp(False, error="Signal not found"))
            return
        old_values = {}
        for key in body.keys():
            if hasattr(sig, key):
                old_values[key] = getattr(sig, key)

        # ★ 信号字段级校验
        if "name" in body:
            name = body["name"]
            if not isinstance(name, str) or not name.strip():
                self._send_json(400, _resp(False, error="Signal name cannot be empty",
                    details={"error_code": "signal_name_empty", "field": "name"}))
                return
            for existing in msg.signals:
                if existing.uuid != idx_str and existing.name == name.strip():
                    self._send_json(400, _resp(False, error=f"Signal name '{name}' already exists",
                        details={"error_code": "signal_name_duplicate", "field": "name",
                                 "name": name}))
                    return
        if "length" in body:
            length = body["length"]
            if length is None or not isinstance(length, (int, float)) or int(length) < 1:
                self._send_json(400, _resp(False, error="Signal length must be at least 1",
                    details={"error_code": "signal_length_invalid", "field": "length"}))
                return
        for num_field in ("factor", "offset", "min_val", "max_val"):
            if num_field in body:
                val = body[num_field]
                if val is None or not isinstance(val, (int, float)):
                    self._send_json(400, _resp(False, error=f"Invalid {num_field} value",
                        details={"error_code": "invalid_number", "field": num_field}))
                    return
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    self._send_json(400, _resp(False, error=f"{num_field} cannot be NaN or Infinity",
                        details={"error_code": "invalid_number", "field": num_field}))
                    return
        if "factor" in body and body["factor"] == 0:
            self._send_json(400, _resp(False, error="Factor cannot be zero",
                details={"error_code": "factor_zero", "field": "factor"}))
            return

        # 防御性校验：更新后的信号所有 bit 必须在报文范围内
        test_sig = Signal.from_dict({**sig.to_dict(), **body})
        ok, err, _info = db.validate_signal(msg_id, test_sig, exclude_uuid=idx_str)
        if not ok:
            self._send_json(400, _resp(False, error=err, details=_info))
            return

        ok = db.update_signal_in_message(msg_id, idx_str, **body)
        if not ok:
            self._send_json(404, _resp(False, error="Message or signal not found"))
            return
        
        # 推入撤销栈（signal_update）
        if old_values:
            self._push_undo({
                "type": "signal_update",
                "msgId": msg_id,
                "sigUuid": idx_str,
                "prev": old_values,
                "next": body
            })
        
        msg = db.get_message(msg_id)
        sig = next((s for s in msg.signals if s.uuid == idx_str), None) if msg else None
        self._send_json(200, _resp(True, sig.to_dict() if sig else {}))

    def _delete_signal(self, id_str: str, uuid_str: str) -> None:
        """DELETE /api/messages/{id}/signals/{uuid} - 删除信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        
        # 保存信号数据（用于撤销）
        msg = db.get_message(msg_id)
        sig = next((s for s in msg.signals if s.uuid == uuid_str), None) if msg else None
        if not sig:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
        
        sig_data = sig.to_dict()
        
        ok = db.remove_signal_from_message(msg_id, uuid_str)
        if not ok:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
        
        # 推入撤销栈（signal_delete）
        self._push_undo({
            "type": "signal_delete",
            "msgId": msg_id,
            "data": sig_data
        })
        
        self._send_json(200, _resp(True, {"deleted": uuid_str}))


def _parse_id(s: Any) -> int | None:
    """解析报文ID（仅接受十进制整数或整数字符串）。"""
    if isinstance(s, int):
        return s
    if not isinstance(s, str):
        return None
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return None


# ── 启动服务器 ────────────────────────────────────────────────────────────────

def check_port_available(port: int) -> bool:
    """检查端口是否可用。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', port))
            return True
        except OSError:
            return False


def find_processes_on_port(port: int) -> list:
    """查找占用指定端口的进程。
    
    Windows: 使用 netstat -ano
    Linux/Mac: 使用 lsof 或 ss
    """
    import subprocess
    import platform
    
    system = platform.system()
    
    try:
        if system == 'Windows':
            # Windows: 使用 netstat -ano
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            pids = []
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    # 提取 PID（最后一列）
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit():
                            pids.append(int(pid))
            
            return pids
        
        elif system in ('Linux', 'Darwin'):  # Darwin = macOS
            # Linux: 使用 ss 或 lsof
            # 优先使用 ss（更快）
            try:
                result = subprocess.run(
                    ['ss', '-tlnp', f'sport = :{port}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                pids = []
                for line in result.stdout.split('\n'):
                    # ss 输出示例: LISTEN  0  128  0.0.0.0:8080  0.0.0.0:*  users:(("python",pid=12345,fd=3))
                    if 'pid=' in line:
                        import re
                        pid_match = re.search(r'pid=(\d+)', line)
                        if pid_match:
                            pids.append(int(pid_match.group(1)))
                
                if pids:
                    return pids
            except FileNotFoundError:
                # ss 不可用，尝试 lsof
                pass
            
            # 使用 lsof
            result = subprocess.run(
                ['lsof', '-i', f':{port}', '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                pids = []
                for line in result.stdout.strip().split('\n'):
                    if line.strip().isdigit():
                        pids.append(int(line.strip()))
                return pids
        
        return []
    except Exception:
        return []


def kill_process(pid: int) -> bool:
    """终止指定进程。
    
    Windows: 使用 taskkill
    Linux/Mac: 使用 kill
    """
    import subprocess
    import platform
    
    try:
        system = platform.system()
        
        if system == 'Windows':
            subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                capture_output=True,
                timeout=5
            )
        elif system in ('Linux', 'Darwin'):
            subprocess.run(
                ['kill', '-9', str(pid)],
                capture_output=True,
                timeout=5
            )
        else:
            return False
        
        return True
    except Exception:
        return False


def handle_port_conflict(port: int, auto_clean: bool = False) -> bool:
    """处理端口冲突，返回是否成功解决。
    
    Args:
        port: 端口号
        auto_clean: 是否自动清理（无需用户确认）
    """
    import platform
    
    print(f"\n[ERROR] 错误：端口 {port} 已被占用")
    print("=" * 60)
    
    system = platform.system()
    
    # 查找占用端口的进程
    pids = find_processes_on_port(port)
    
    if not pids:
        print(f"端口 {port} 被占用，但无法检测到占用进程。")
        print("可能的原因：")
        print("  1. 其他程序正在使用该端口")
        print("  2. 端口处于 TIME_WAIT 状态（等待关闭）")
        print("\n建议操作：")
        print(f"  - 使用其他端口启动：python api_server.py <端口号>")
        print(f"  - 等待几秒后重试（如果是 TIME_WAIT 状态）")
        return False
    
    # 检查是否是 api_server.py 进程（仅 Windows 支持详细检查）
    api_server_pids = []
    
    if system == 'Windows':
        import subprocess
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            for line in result.stdout.split('\n'):
                if 'python.exe' in line.lower():
                    for pid in pids:
                        if str(pid) in line:
                            api_server_pids.append(pid)
        except Exception:
            pass
    else:
        # Linux/Mac: 简化处理，假设所有占用端口的进程都是目标进程
        # 可以通过 /proc/<pid>/cmdline 或 ps 命令进一步检查
        api_server_pids = pids[:10]  # 限制最多处理 10 个进程
    
    if api_server_pids:
        print(f"检测到 {len(api_server_pids)} 个占用端口的进程：")
        for pid in api_server_pids:
            print(f"  - PID: {pid}")
        print()
        
        # 根据 auto_clean 参数决定是否跳过确认
        if auto_clean:
            print("[Auto-Clean] 正在终止旧进程...")
        else:
            # 询问是否自动清理
            try:
                response = input("是否自动终止旧进程并重启？(Y/n): ").strip().lower()
                if response not in ['', 'y', 'yes']:
                    print("\n已取消自动清理。")
                    print("\n手动操作建议：")
                    if system == 'Windows':
                        print("  Windows: taskkill /F /PID <进程ID>")
                        print("  或使用任务管理器终止 python.exe 进程")
                    elif system == 'Linux':
                        print("  Linux: kill -9 <进程ID>")
                        print("  或使用 pkill -f api_server.py")
                    elif system == 'Darwin':
                        print("  macOS: kill -9 <进程ID>")
                        print("  或使用活动监视器终止进程")
                    else:
                        print(f"  {system}: kill <进程ID>")
                    return False
            except (KeyboardInterrupt, EOFError):
                print("\n\n已取消操作。")
                return False
            
            print("\n正在终止旧进程...")
        
        # 执行清理操作
        for pid in api_server_pids:
            if kill_process(pid):
                print(f"  [OK] 已终止进程 {pid}")
            else:
                print(f"  [ERROR] 无法终止进程 {pid}")
        
        # 等待端口释放
        print("等待端口释放...")
        import time
        for i in range(10):
            if check_port_available(port):
                print("[OK] 端口已释放")
                return True
            time.sleep(0.5)
        
        print("[WARN] 端口仍未释放，请手动检查")
        return False
    else:
        print(f"端口 {port} 被其他程序占用（PID: {', '.join(map(str, pids))}）")
        print("\n建议操作：")
        print(f"  1. 终止占用端口的程序")
        print(f"  2. 使用其他端口启动：python api_server.py <端口号>")
        return False


def main() -> None:
    """主函数，支持命令行参数。"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='CanMatrix Editor API Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python api_server.py                  # 默认端口 8080
  python api_server.py 9090             # 指定端口 9090
  python api_server.py --auto-clean     # 自动清理端口冲突
  python api_server.py -p 9090 --auto-clean  # 组合使用
"""
    )
    
    parser.add_argument(
        'port',
        nargs='?',
        type=int,
        default=8080,
        help='服务器端口号 (默认: 8080)'
    )
    
    parser.add_argument(
        '-p', '--port-opt',
        type=int,
        default=None,
        help='服务器端口号 (覆盖位置参数)'
    )
    
    parser.add_argument(
        '--auto-clean',
        action='store_true',
        help='自动清理端口冲突（无需用户确认）'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='强制模式（同 --auto-clean）'
    )
    
    args = parser.parse_args()
    
    # 确定端口号（--port-opt 优先于位置参数）
    port = args.port_opt if args.port_opt is not None else args.port
    auto_clean = args.auto_clean or args.force
    
    if auto_clean:
        print(f"\n[Auto-Clean] 启动模式：自动清理端口冲突")
    
    # 检查端口是否可用
    if not check_port_available(port):
        print(f"\n[WARN] 检测到端口 {port} 已被占用")
        
        # 尝试处理端口冲突
        if not handle_port_conflict(port, auto_clean=auto_clean):
            print("\n[ERROR] 无法启动服务器，请解决端口冲突后重试。")
            sys.exit(1)
        
        # 再次检查端口
        if not check_port_available(port):
            print(f"\n[ERROR] 端口 {port} 仍然被占用，无法启动。")
            sys.exit(1)
    
    server = HTTPServer(("localhost", port), ApiHandler)
    print(f"\nCanMatrix Editor API server running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    
    # ── 优雅关闭机制（Graceful Shutdown） ──
    
    def save_all_sessions():
        """保存所有活跃会话（优雅关闭）。"""
        print("\n[INFO] Saving all active sessions...")
        count = SESSION_MGR.save_all_dirty()
        if count > 0:
            print(f"[INFO] Save complete: {count} session(s) saved")
        else:
            print(f"[INFO] No modified sessions to save.")
    
    # 注册退出处理器（进程正常退出时触发）
    atexit.register(save_all_sessions)

    # ── 定时自动保存（每 5 分钟） ──
    AUTO_SAVE_INTERVAL = 300  # 5 分钟
    
    def _periodic_auto_saver():
        while True:
            time.sleep(AUTO_SAVE_INTERVAL)
            try:
                count = SESSION_MGR.save_all_dirty()
                if count > 0:
                    print(f"[AUTO-SAVE] Periodic save: {count} session(s) saved to disk")
            except Exception as e:
                print(f"[AUTO-SAVE] Error: {e}")
    
    auto_save_thread = threading.Thread(target=_periodic_auto_saver, daemon=True)
    auto_save_thread.start()
    print(f"[AUTO-SAVE] Periodic auto-save started (interval={AUTO_SAVE_INTERVAL}s)")
    
    # 注册信号处理器（捕获 Ctrl+C 和 kill 信号）
    def graceful_shutdown(signum, frame):
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        print(f"\n[INFO] Received {signal_name} signal, initiating graceful shutdown...")
        sys.exit(0)  # 触发 atexit
    
    # 跨平台信号注册（Windows 支持 SIGINT，Unix 支持 SIGTERM）
    signal.signal(signal.SIGINT, graceful_shutdown)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, graceful_shutdown)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


def start_server_background(port: int = 8080) -> "HTTPServer":
    """在后台线程启动 API 服务器，返回 server 对象供外部控制关闭。
    用于桌面应用（pywebview）集成。
    """
    server = HTTPServer(("localhost", port), ApiHandler)
    print(f"\nCanMatrix Editor API server running at http://localhost:{port}")

    # 定时自动保存（每 5 分钟）
    AUTO_SAVE_INTERVAL = 300
    def _periodic_auto_saver():
        while True:
            time.sleep(AUTO_SAVE_INTERVAL)
            try:
                count = SESSION_MGR.save_all_dirty()
                if count > 0:
                    print(f"[AUTO-SAVE] Periodic save: {count} session(s) saved")
            except Exception as e:
                print(f"[AUTO-SAVE] Error: {e}")

    auto_save_thread = threading.Thread(target=_periodic_auto_saver, daemon=True)
    auto_save_thread.start()

    # 注册 atexit 保存
    def save_all_sessions():
        print("\n[INFO] Saving all active sessions...")
        count = SESSION_MGR.save_all_dirty()
        if count > 0:
            print(f"[INFO] Save complete: {count} session(s) saved")
    atexit.register(save_all_sessions)

    # 在守护线程中运行 serve_forever
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server


if __name__ == "__main__":
    main()
