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
import os
import sys
import urllib.parse
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
from session_manager import init_session_manager, get_session_manager

SESSION_MGR = init_session_manager()

# ── 数据模型 ──────────────────────────────────────────────────────────────────

class Signal:
    """单个CAN信号定义（per-message实体）。"""

    def __init__(self, data: dict | None = None) -> None:
        data = data or {}
        self.name: str = data.get("name", "")
        self.start_bit: int = data.get("start_bit", 0)
        self.length: int = data.get("length", 8)
        self.byte_order: str = data.get("byte_order", "little_endian")
        self.is_signed: bool = data.get("is_signed", False)
        self.factor: float = data.get("factor", 1.0)
        self.offset: float = data.get("offset", 0.0)
        self.min_val: float = data.get("min_val", 0.0)
        self.max_val: float = data.get("max_val", 0.0)
        self.unit: str = data.get("unit", "")
        self.comment: str = data.get("comment", "")
        self.receivers: list[str] = data.get("receivers", [])
        self.multiplexer_mode: str = data.get("multiplexer_mode", "none")
        self.multiplexer_value: int = data.get("multiplexer_value", 0)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "start_bit": self.start_bit,
            "length": self.length,
            "byte_order": self.byte_order,
            "is_signed": self.is_signed,
            "factor": self.factor,
            "offset": self.offset,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "unit": self.unit,
            "comment": self.comment,
            "receivers": self.receivers,
            "multiplexer_mode": self.multiplexer_mode,
            "multiplexer_value": self.multiplexer_value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Signal":
        return cls(data)


class Message:
    """一个CAN报文及其信号定义。"""

    def __init__(self, data: dict | None = None) -> None:
        data = data or {}
        self.id: int = data.get("id", 0)
        self.name: str = data.get("name", "")
        self.dlc: int = data.get("dlc", 8)
        self.cycle_time: int = data.get("cycle_time", 0)
        self.comment: str = data.get("comment", "")
        self.sender: str = data.get("sender", "")
        self.signals: list[Signal] = [
            Signal(s) for s in data.get("signals", [])
        ]

    def to_dict(self, signals_as_dict: bool = True) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "dlc": self.dlc,
            "cycle_time": self.cycle_time,
            "comment": self.comment,
            "sender": self.sender,
        }
        if signals_as_dict:
            d["signals"] = [s.to_dict() for s in self.signals]
        else:
            d["signals"] = self.signals
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(data)


class CanDatabase:
    """顶层CAN数据库。信号是per-message定义。"""

    def __init__(self, name: str = "Untitled") -> None:
        self.name: str = name
        self.messages: dict[int, Message] = {}
        self.modified: bool = False

    # ── 报文操作 ──

    def add_message(self, msg: Message) -> bool:
        if msg.id in self.messages:
            return False
        self.messages[msg.id] = msg
        self.modified = True
        return True

    def remove_message(self, msg_id: int) -> Message | None:
        msg = self.messages.pop(msg_id, None)
        if msg:
            self.modified = True
        return msg

    def get_message(self, msg_id: int) -> Message | None:
        return self.messages.get(msg_id)

    def update_message(self, msg_id: int, **kwargs: Any) -> bool:
        msg = self.messages.get(msg_id)
        if not msg:
            return False
        for k, v in kwargs.items():
            if hasattr(msg, k):
                setattr(msg, k, v)
        self.modified = True
        return True

    # ── 信号操作 ──

    def add_signal_to_message(self, msg_id: int, sig: Signal) -> bool:
        msg = self.messages.get(msg_id)
        if not msg:
            return False
        msg.signals.append(sig)
        self.modified = True
        return True

    def remove_signal_from_message(self, msg_id: int, sig_idx: int) -> bool:
        msg = self.messages.get(msg_id)
        if not msg or sig_idx < 0 or sig_idx >= len(msg.signals):
            return False
        msg.signals.pop(sig_idx)
        self.modified = True
        return True

    def update_signal_in_message(
        self, msg_id: int, sig_idx: int, **kwargs: Any
    ) -> bool:
        msg = self.messages.get(msg_id)
        if not msg or sig_idx < 0 or sig_idx >= len(msg.signals):
            return False
        sig = msg.signals[sig_idx]
        for k, v in kwargs.items():
            if hasattr(sig, k):
                setattr(sig, k, v)
        self.modified = True
        return True

    def total_signals(self) -> int:
        return sum(len(m.signals) for m in self.messages.values())

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "messages": {
                str(mid): m.to_dict() for mid, m in sorted(self.messages.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CanDatabase":
        db = cls(name=data.get("name", "Untitled"))
        for mid_str, mdata in data.get("messages", {}).items():
            mid = int(mid_str, 16) if mid_str.startswith("0x") else int(mid_str)
            mdata["id"] = mid
            msg = Message.from_dict(mdata)
            db.messages[mid] = msg
        return db

    # ── JSON 序列化（SessionManager 持久化用） ──

    def to_json_dict(self) -> dict:
        return self.to_dict()

    @classmethod
    def from_json_dict(cls, data: dict) -> "CanDatabase":
        return cls.from_dict(data)

    # ── TOML 序列化 ──

    def to_toml_str(self) -> str:
        import toml

        data = {"name": self.name, "messages": []}
        for mid in sorted(self.messages):
            msg = self.messages[mid]
            m_dict = {
                "id": f"0x{mid:X}",
                "name": msg.name,
                "dlc": msg.dlc,
                "cycle_time": msg.cycle_time,
                "sender": msg.sender,
                "comment": msg.comment,
                "signals": [],
            }
            for sig in msg.signals:
                s_dict = {k: v for k, v in sig.to_dict().items() if v != _SIGNAL_DEFAULTS.get(k)}
                m_dict["signals"].append(s_dict)
            data["messages"].append(m_dict)
        return toml.dumps(data)

    # ── DBC 序列化 ──

    def to_dbc_str(self) -> str:
        """导出为 DBC 格式字符串。"""
        lines = []
        lines.append("VERSION \"\"")
        lines.append("")
        lines.append("NS_ :")
        lines.append("    NS_DESC_")
        lines.append("    CM_")
        lines.append("    BA_DEF_")
        lines.append("    BA_")
        lines.append("    VAL_")
        lines.append("    CAT_DEF_")
        lines.append("    CAT_")
        lines.append("    FILTER")
        lines.append("    BA_DEF_DEF_")
        lines.append("    EV_DATA_")
        lines.append("    ENVVAR_DATA_")
        lines.append("    SGTYPE_")
        lines.append("    SGTYPE_VAL_")
        lines.append("    BA_DEF_SGTYPE_")
        lines.append("    BA_SGTYPE_")
        lines.append("    SIG_TYPE_REF_")
        lines.append("    VAL_TABLE_")
        lines.append("    SIG_GROUP_")
        lines.append("    SIG_VALTYPE_")
        lines.append("    SIGTYPE_VALTYPE_")
        lines.append("    BO_TX_BU_")
        lines.append("    BA_DEF_REL_")
        lines.append("    BA_REL_")
        lines.append("    BA_DEF_DEF_REL_")
        lines.append("    BU_SG_REL_")
        lines.append("    BU_EV_REL_")
        lines.append("    BU_BO_REL_")
        lines.append("    SG_MUL_VAL_")
        lines.append("")
        
        # BU_: 网络节点
        lines.append("BU_: ECU1 ECU2 BMS")
        lines.append("")
        
        # BO_: 报文定义
        for mid in sorted(self.messages):
            msg = self.messages[mid]
            # BO_ <id> <name>: <dlc> <sender>
            sender = msg.sender if msg.sender else "ECU1"
            lines.append(f"BO_ {mid} {msg.name}: {msg.dlc} {sender}")
            
            # 信号定义
            for sig in msg.signals:
                # SG_ <name> : <start_bit>|<length>@<byte_order><sign> (<factor>,<offset>) [<min>|<max>] "<unit>" <receivers>
                byte_order = 1 if sig.byte_order == "big_endian" else 0
                sign = "-" if sig.is_signed else "+"
                factor = sig.factor if sig.factor != 1.0 else 1
                offset = sig.offset if sig.offset != 0.0 else 0
                min_val = sig.min_val if sig.min_val != 0.0 else 0
                max_val = sig.max_val if sig.max_val != 0.0 else 0
                unit = sig.unit if sig.unit else ""
                receivers = ",".join(sig.receivers) if sig.receivers else "Vector__XXX"
                
                lines.append(f" SG_ {sig.name} : {sig.start_bit}|{sig.length}@{byte_order}{sign} ({factor},{offset}) [{min_val}|{max_val}] \"{unit}\" {receivers}")
            
            lines.append("")
        
        # VAL_: 信号值描述（可选）
        for mid in sorted(self.messages):
            msg = self.messages[mid]
            for sig in msg.signals:
                if sig.comment:
                    # CM_ SG_ <message_id> <signal_name> "<comment>";
                    lines.append(f"CM_ SG_ {mid} {sig.name} \"{self._escape_dbc_string(sig.comment)}\";")
        
        # 报文注释
        for mid in sorted(self.messages):
            msg = self.messages[mid]
            if msg.comment:
                lines.append(f"CM_ BO_ {mid} \"{self._escape_dbc_string(msg.comment)}\";")
        
        lines.append("")
        return "\n".join(lines)
    
    def _escape_dbc_string(self, s: str) -> str:
        """转义 DBC 字符串中的特殊字符。"""
        if not s:
            return ""
        # 简单转义：双引号、反斜杠
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
    
    @classmethod
    def from_dbc_str(cls, content: str) -> "CanDatabase":
        """从 DBC 格式解析（暂不实现）。"""
        raise NotImplementedError("DBC import not yet implemented")

    @classmethod
    def from_toml_str(cls, content: str) -> "CanDatabase":
        import toml

        data = toml.loads(content)
        db = cls(name=data.get("name", "Untitled"))
        for m_dict in data.get("messages", []):
            mid_raw = m_dict["id"]
            mid = int(mid_raw, 16) if isinstance(mid_raw, str) and mid_raw.startswith("0x") else int(mid_raw)
            msg = Message(
                id=mid,
                name=m_dict.get("name", ""),
                dlc=m_dict.get("dlc", 8),
                cycle_time=m_dict.get("cycle_time", 0),
                sender=m_dict.get("sender", ""),
                comment=m_dict.get("comment", ""),
            )
            for s_dict in m_dict.get("signals", []):
                msg.signals.append(Signal.from_dict(s_dict))
            db.messages[mid] = msg
        return db


_SIGNAL_DEFAULTS = {
    "name": "",
    "start_bit": 0,
    "length": 8,
    "byte_order": "little_endian",
    "is_signed": False,
    "factor": 1.0,
    "offset": 0.0,
    "min_val": 0.0,
    "max_val": 0.0,
    "unit": "",
    "comment": "",
    "receivers": [],
    "multiplexer_mode": "none",
    "multiplexer_value": 0,
}


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


def _resp(success: bool, data: Any = None, error: str = "") -> dict:
    """统一JSON响应格式。"""
    return {"success": success, "data": data, "error": error}


# ── API 请求处理器 ────────────────────────────────────────────────────────────

class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        """调试日志。"""
        msg = fmt % args
        print(f"[HTTP] {msg}")

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
            s = SESSION_MGR.restore(session_id)
            if s:
                return s.db
        # 降级：无 session 时使用匿名临时 DB
        return _temp_db()

    def _auto_save(self) -> None:
        """变更后自动保存。"""
        session_id = self.headers.get("X-Session-Id", "")
        if session_id:
            SESSION_MGR.save(session_id)

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
        try:
            self._handle_GET()
        except Exception as e:
            print(f"[ERROR] do_GET: {e}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass

    def _handle_GET(self) -> None:
        parts = self._path_parts()
        if parts == ["api", "status"]:
            self._get_status()
        elif parts == ["api", "messages"]:
            self._get_messages()
        elif parts[0:2] == ["api", "messages"] and len(parts) == 3:
            self._get_message(parts[2])
        elif parts == ["api", "summary"]:
            self._get_summary()
        elif parts[0:2] == ["api", "session"] and len(parts) == 3:
            self._get_session(parts[2])
        elif parts == ["api", "sessions"]:
            self._get_sessions()
        else:
            self._serve_static()

    def do_POST(self) -> None:
        try:
            self._handle_POST()
        except Exception as e:
            print(f"[ERROR] do_POST: {e}", flush=True)
            import traceback
            traceback.print_exc()
            try:
                self._send_json(500, _resp(False, error="Internal server error"))
            except:
                pass

    def _handle_POST(self) -> None:
        parts = self._path_parts()
        if parts == ["api", "new"]:
            self._post_new()
        elif parts == ["api", "import"]:
            self._post_import()
        elif parts == ["api", "export"]:
            self._post_export()
        elif parts == ["api", "messages"]:
            self._post_messages()
        elif parts == ["api", "session"]:
            self._post_session()
        elif len(parts) == 4 and parts[0:2] == ["api", "session"] and parts[3] == "load":
            # POST /api/session/{id}/load
            self._post_session_load(parts[2])
        elif len(parts) == 4 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
            # POST /api/messages/{id}/signals
            self._post_signals(parts[2])
        else:
            self._send_json(404, _resp(False, error="Not found"))

    def do_PUT(self) -> None:
        parts = self._path_parts()
        if len(parts) == 3 and parts[0:2] == ["api", "messages"]:
            # PUT /api/messages/{id}
            self._put_message(parts[2])
        elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
            # PUT /api/messages/{id}/signals/{idx}
            self._put_signal(parts[2], parts[4])
        elif parts == ["api", "session"]:
            # PUT /api/session - 更新数据库名称
            self._put_session()
        else:
            self._send_json(404, _resp(False, error="Not found"))

    def do_DELETE(self) -> None:
        parts = self._path_parts()
        if len(parts) == 3 and parts[0:2] == ["api", "messages"]:
            # DELETE /api/messages/{id}
            self._delete_message(parts[2])
        elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
            # DELETE /api/messages/{id}/signals/{idx}
            self._delete_signal(parts[2], parts[4])
        elif len(parts) == 3 and parts[0:2] == ["api", "session"]:
            # DELETE /api/session/{id}
            self._delete_session(parts[2])
        else:
            self._send_json(404, _resp(False, error="Not found"))

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
        """GET /api/session/{id} - 恢复会话，返回完整数据库状态。"""
        s = SESSION_MGR.restore(session_id)
        if not s:
            self._send_json(404, _resp(False, error="Session not found or expired"))
            return
        self._send_json(200, _resp(True, {
            "session_id": s.id,
            "file_name": _pure_file_name(s),
            "db": s.db.to_dict(),
            "message_count": len(s.db.messages),
            "signal_count": s.db.total_signals(),
        }))

    def _get_sessions(self) -> None:
        """GET /api/sessions - 列出所有历史会话（含磁盘文件）。"""
        sessions = SESSION_MGR.list_history()
        self._send_json(200, _resp(True, sessions))

    def _delete_session(self, session_id: str) -> None:
        """DELETE /api/session/{id} - 删除历史会话（内存 + 磁盘）。"""
        ok = SESSION_MGR.delete_history(session_id)
        if ok:
            self._send_json(200, _resp(True, {"deleted": session_id}))
        else:
            self._send_json(404, _resp(False, error="Session not found"))

    def _post_session_load(self, session_id: str) -> None:
        """POST /api/session/{id}/load - 恢复历史会话（直接复用原 session，不创建副本）。"""
        s = SESSION_MGR.restore(session_id)
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
        self._send_json(200, _resp(True, {
            "message_count": len(db.messages),
            "signal_count": db.total_signals(),
            "modified": db.modified,
            "session_id": session_id,
            "file_name": _pure_file_name(s) if s else None,
        }))

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
        name = body.get("name", "Untitled") if body else {"name": "Untitled"}
        if isinstance(name, dict):
            name = name.get("name", "Untitled")

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
                self._send_json(400, _resp(False, error="DBC import via API not yet implemented"))
                return
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(400, _resp(False, error=f"Import failed: {e}"))
            return

        # 替换当前会话的 DB 并自动保存
        session_id = self.headers.get("X-Session-Id", "")
        if session_id:
            s = SESSION_MGR.get(session_id)
            if s:
                s.db = new_db
                self._auto_save()

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
        msg = Message(body)
        msg.id = msg_id
        if not db.add_message(msg):
            self._send_json(409, _resp(False, error=f"Message 0x{msg_id:X} already exists"))
            return
        self._auto_save()
        self._send_json(201, _resp(True, msg.to_dict()))

    def _put_message(self, id_str: str) -> None:
        """PUT /api/messages/{id} - 更新报文。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        # 允许更新id（即移动key）
        new_id = _parse_id(body.get("id", msg_id))
        if new_id is None:
            self._send_json(400, _resp(False, error="Invalid new ID"))
            return
        if new_id != msg_id:
            if db.get_message(new_id):
                self._send_json(409, _resp(False, error=f"Message 0x{new_id:X} already exists"))
                return
            old = db.remove_message(msg_id)
            if old:
                old.id = new_id
                db.add_message(old)
                msg_id = new_id
        ok = db.update_message(msg_id, **{k: v for k, v in body.items() if k != "id"})
        if not ok:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._auto_save()
        self._send_json(200, _resp(True, db.get_message(msg_id).to_dict()))

    def _delete_message(self, id_str: str) -> None:
        """DELETE /api/messages/{id} - 删除报文。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        msg = db.remove_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._auto_save()
        self._send_json(200, _resp(True, {"deleted": f"0x{msg_id:X}"}))

    def _post_signals(self, id_str: str) -> None:
        """POST /api/messages/{id}/signals - 添加信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        sig = Signal(body)
        if not db.add_signal_to_message(msg_id, sig):
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._auto_save()
        self._send_json(201, _resp(True, sig.to_dict()))

    def _put_signal(self, id_str: str, idx_str: str) -> None:
        """PUT /api/messages/{id}/signals/{idx} - 更新信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        try:
            sig_idx = int(idx_str)
        except ValueError:
            self._send_json(400, _resp(False, error="Invalid signal index"))
            return
        body = self._read_body()
        ok = db.update_signal_in_message(msg_id, sig_idx, **body)
        if not ok:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
        sig = db.get_message(msg_id).signals[sig_idx]
        self._auto_save()
        self._send_json(200, _resp(True, sig.to_dict()))

    def _delete_signal(self, id_str: str, idx_str: str) -> None:
        """DELETE /api/messages/{id}/signals/{idx} - 删除信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        try:
            sig_idx = int(idx_str)
        except ValueError:
            self._send_json(400, _resp(False, error="Invalid signal index"))
            return
        ok = db.remove_signal_from_message(msg_id, sig_idx)
        if not ok:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
        self._auto_save()
        self._send_json(200, _resp(True, {"deleted": sig_idx}))


def _parse_id(s: Any) -> int | None:
    """解析报文ID（支持十进制、0x十六进制）。"""
    if isinstance(s, int):
        return s
    if not isinstance(s, str):
        return None
    s = s.strip()
    if s.startswith("0x") or s.startswith("0X"):
        try:
            return int(s, 16)
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


# ── 启动服务器 ────────────────────────────────────────────────────────────────

def main() -> None:
    port = 8080
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = HTTPServer(("localhost", port), ApiHandler)
    print(f"CanMatrix Editor API server running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
