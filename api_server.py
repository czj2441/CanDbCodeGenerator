#!/usr/bin/env python3
"""
CanMatrix Editor - REST API Server
解耦前后端架构：前端只负责UI渲染，所有数据操作通过REST API。
使用标准库 http.server，不引入重量级依赖。
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
    # Python < 3.7 回退
    from socketserver import ThreadingMixIn
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        pass
    THREADING_AVAILABLE = True

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

DB = CanDatabase()
CURRENT_FILE: str | None = None


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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
        # parts: ["api", "messages", "{id}"] 等
        if parts == ["api", "status"]:
            self._get_status()
        elif parts == ["api", "messages"]:
            self._get_messages()
        elif parts[0:2] == ["api", "messages"] and len(parts) == 3:
            # GET /api/messages/{id}
            self._get_message(parts[2])
        elif parts == ["api", "summary"]:
            self._get_summary()
        else:
            self._send_json(404, _resp(False, error="Not found"))

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
        else:
            self._send_json(404, _resp(False, error="Not found"))

    # ── 端点实现 ──

    def _get_status(self) -> None:
        global DB
        self._send_json(200, _resp(True, {
            "message_count": len(DB.messages),
            "signal_count": DB.total_signals(),
            "modified": DB.modified,
            "current_file": CURRENT_FILE,
        }))

    def _get_messages(self) -> None:
        global DB
        data = [
            {
                "id": mid,
                "id_hex": f"0x{mid:X}",
                "name": m.name,
                "dlc": m.dlc,
                "cycle_time": m.cycle_time,
                "signal_count": len(m.signals),
            }
            for mid, m in sorted(DB.messages.items())
        ]
        self._send_json(200, _resp(True, data))

    def _get_message(self, id_str: str) -> None:
        global DB
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        msg = DB.get_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._send_json(200, _resp(True, msg.to_dict()))

    def _get_summary(self) -> None:
        global DB
        msgs = list(DB.messages.values())
        self._send_json(200, _resp(True, {
            "name": DB.name,
            "message_count": len(msgs),
            "signal_count": DB.total_signals(),
            "modified": DB.modified,
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
        global DB, CURRENT_FILE
        body = self._read_body()
        name = body.get("name", "Untitled") if body else {"name": "Untitled"}
        if isinstance(name, dict):
            name = name.get("name", "Untitled")
        DB = CanDatabase(name)
        CURRENT_FILE = None
        self._send_json(200, _resp(True, {"name": DB.name}))

    def _post_import(self) -> None:
        """导入文件内容（前端已读取文件，发送JSON）。"""
        global DB, CURRENT_FILE
        body = self._read_body()
        fmt = body.get("format", "json")
        content = body.get("content", "")
        filename = body.get("filename", "")

        try:
            if fmt == "toml":
                import toml
                DB = CanDatabase.from_toml_str(content)
            elif fmt == "json":
                data = json.loads(content)
                DB = CanDatabase.from_dict(data)
            elif fmt == "dbc":
                # DBC需要文件，这里只做占位
                self._send_json(400, _resp(False, error="DBC import via API not yet implemented"))
                return
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(400, _resp(False, error=f"Import failed: {e}"))
            return

        CURRENT_FILE = filename or None
        self._send_json(200, _resp(True, {"message_count": len(DB.messages)}))

    def _post_export(self) -> None:
        """导出数据库为指定格式并返回内容。"""
        global DB
        body = self._read_body()
        fmt = body.get("format", "json") if body else "json"

        try:
            if fmt == "json":
                content = json.dumps(DB.to_dict(), ensure_ascii=False, indent=2)
            elif fmt == "toml":
                content = DB.to_toml_str()
            elif fmt == "dbc":
                content = DB.to_dbc_str()
            else:
                self._send_json(400, _resp(False, error=f"Unsupported format: {fmt}"))
                return
        except Exception as e:
            self._send_json(500, _resp(False, error=f"Export failed: {e}"))
            return

        self._send_json(200, _resp(True, {"content": content, "format": fmt}))

    def _post_messages(self) -> None:
        """POST /api/messages - 添加报文。"""
        global DB
        body = self._read_body()
        msg_id = _parse_id(body.get("id", ""))
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid or missing message ID"))
            return
        msg = Message(body)
        msg.id = msg_id
        if not DB.add_message(msg):
            self._send_json(409, _resp(False, error=f"Message 0x{msg_id:X} already exists"))
            return
        self._send_json(201, _resp(True, msg.to_dict()))

    def _put_message(self, id_str: str) -> None:
        """PUT /api/messages/{id} - 更新报文。"""
        global DB
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
            if DB.get_message(new_id):
                self._send_json(409, _resp(False, error=f"Message 0x{new_id:X} already exists"))
                return
            old = DB.remove_message(msg_id)
            if old:
                old.id = new_id
                DB.add_message(old)
                msg_id = new_id
        ok = DB.update_message(msg_id, **{k: v for k, v in body.items() if k != "id"})
        if not ok:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._send_json(200, _resp(True, DB.get_message(msg_id).to_dict()))

    def _delete_message(self, id_str: str) -> None:
        """DELETE /api/messages/{id} - 删除报文。"""
        global DB
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        msg = DB.remove_message(msg_id)
        if not msg:
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._send_json(200, _resp(True, {"deleted": f"0x{msg_id:X}"}))

    def _post_signals(self, id_str: str) -> None:
        """POST /api/messages/{id}/signals - 添加信号。"""
        global DB
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        sig = Signal(body)
        if not DB.add_signal_to_message(msg_id, sig):
            self._send_json(404, _resp(False, error=f"Message 0x{msg_id:X} not found"))
            return
        self._send_json(201, _resp(True, sig.to_dict()))

    def _put_signal(self, id_str: str, idx_str: str) -> None:
        """PUT /api/messages/{id}/signals/{idx} - 更新信号。"""
        global DB
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
        ok = DB.update_signal_in_message(msg_id, sig_idx, **body)
        if not ok:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
        sig = DB.get_message(msg_id).signals[sig_idx]
        self._send_json(200, _resp(True, sig.to_dict()))

    def _delete_signal(self, id_str: str, idx_str: str) -> None:
        """DELETE /api/messages/{id}/signals/{idx} - 删除信号。"""
        global DB
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        try:
            sig_idx = int(idx_str)
        except ValueError:
            self._send_json(400, _resp(False, error="Invalid signal index"))
            return
        ok = DB.remove_signal_from_message(msg_id, sig_idx)
        if not ok:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
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
