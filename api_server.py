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

# ── 数据模型 ──────────────────────────────────────────────────────────────────

class Signal:
    """单个CAN信号定义（per-message实体）。"""

    def __init__(self, data: dict | None = None) -> None:
        data = data or {}
        self.uuid: str = data.get("uuid", uuid.uuid4().hex[:8])
        self.name: str = data.get("name", "")
        self.start_bit: int = data.get("start_bit", 0)
        self.length: int = data.get("length", 8)
        self.byte_order: str = data.get("byte_order", "motorola")
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
            "uuid": self.uuid,
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
        self.__lock = threading.RLock()

    def with_lock(self):
        """返回锁上下文管理器，供外部需要原子操作时使用。"""
        return self.__lock

    # ── 报文操作 ──

    def add_message(self, msg: Message) -> bool:
        with self.__lock:
            if msg.id in self.messages:
                return False
            self.messages[msg.id] = msg
            self.modified = True
            return True

    def remove_message(self, msg_id: int) -> Message | None:
        with self.__lock:
            msg = self.messages.pop(msg_id, None)
            if msg:
                self.modified = True
            return msg

    def get_message(self, msg_id: int) -> Message | None:
        with self.__lock:
            return self.messages.get(msg_id)

    def update_message(self, msg_id: int, **kwargs: Any) -> bool:
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            kwargs.pop("id", None)
            changed = False
            for k, v in kwargs.items():
                if hasattr(msg, k) and getattr(msg, k) != v:
                    setattr(msg, k, v)
                    changed = True
            if changed:
                self.modified = True
            return True

    def move_message(self, old_id: int, new_id: int) -> bool:
        with self.__lock:
            if new_id in self.messages or old_id not in self.messages:
                return False
            msg = self.messages.pop(old_id)
            msg.id = new_id
            self.messages[new_id] = msg
            self.modified = True
            return True

    # ── 信号操作 ──

    def _ensure_sig_uuid_unique(
        self, msg: Message, sig: Signal, exclude_sig: Signal | None = None
    ) -> None:
        """若 sig.uuid 与 msg 中其他信号冲突，则重新生成。"""
        existing = {s.uuid for s in msg.signals if s is not exclude_sig}
        while sig.uuid in existing:
            sig.uuid = uuid.uuid4().hex[:8]

    # ── 信号有效性检查（DBC标准） ──

    @staticmethod
    def _get_signal_bits(start_bit: int, length: int, byte_order: str) -> set[int]:
        """将信号按字节序展开为占用的物理 bit 集合（线性编号 0~N-1）。
        Intel（小端序）: start_bit 是 LSB，占用连续递增位。
        Motorola（大端序）: start_bit 是 MSB，按锯齿规则展开：
            字节内从高位向低位填充，到达 bit0 后跳到下一字节的 bit7。
        """
        bits: set[int] = set()
        bo = str(byte_order).lower() if byte_order else "motorola"
        if bo == "motorola":
            current = start_bit
            for _ in range(length):
                bits.add(current)
                bit_in_byte = current % 8
                if bit_in_byte == 0:
                    current += 15
                else:
                    current -= 1
        else:
            for i in range(length):
                bits.add(start_bit + i)
        return bits

    def _find_next_available_start_bit(
        self, msg: Message, length: int, byte_order: str, exclude_uuid: str | None = None
    ) -> dict | None:
        """在报文中寻找第一个足够大的空闲区间，返回建议的 start_bit。"""
        max_bits = msg.dlc * 8
        if length > max_bits:
            return None
        used: set[int] = set()
        for s in msg.signals:
            if exclude_uuid and s.uuid == exclude_uuid:
                continue
            used |= self._get_signal_bits(s.start_bit, s.length, s.byte_order)
        for candidate in range(max_bits):
            candidate_bits = self._get_signal_bits(candidate, length, byte_order)
            if all(0 <= b < max_bits for b in candidate_bits) and not (candidate_bits & used):
                return {
                    "action": "move_start_bit",
                    "recommended_start_bit": candidate,
                    "reason": f"First available gap at bit {candidate}",
                }
        return None

    def validate_signal(
        self, msg_id: int, sig: Signal, exclude_uuid: str | None = None
    ) -> tuple[bool, str, dict]:
        """验证信号是否可以加入/更新到报文中。返回 (is_valid, error_message, details)."""
        msg = self.messages.get(msg_id)
        if not msg:
            return False, "Message not found", {"type": "invalid_param"}
        max_bits = msg.dlc * 8
        if max_bits < 1:
            return False, "Invalid message DLC", {"type": "invalid_param"}
        if sig.start_bit < 0:
            return False, "Start bit must be non-negative", {
                "type": "invalid_param", "field": "start_bit", "value": sig.start_bit,
            }
        if sig.length < 1:
            return False, "Signal length must be at least 1", {
                "type": "invalid_param", "field": "length", "value": sig.length,
            }
        # 越界检查
        occupied = self._get_signal_bits(sig.start_bit, sig.length, sig.byte_order)
        oob = [b for b in occupied if b < 0 or b >= max_bits]
        if oob:
            suggestion = self._find_next_available_start_bit(
                msg, sig.length, sig.byte_order, exclude_uuid
            )
            return False, f"Signal out of bounds (DLC={msg.dlc}, max bit={max_bits - 1})", {
                "type": "out_of_bounds",
                "signal_name": sig.name,
                "start_bit": sig.start_bit,
                "length": sig.length,
                "byte_order": sig.byte_order,
                "dlc": msg.dlc,
                "max_bit": max_bits - 1,
                "out_of_bounds_bits": sorted(oob)[:10],
                "suggestion": suggestion,
            }
        # 重叠检查
        for existing in msg.signals:
            if exclude_uuid and existing.uuid == exclude_uuid:
                continue
            existing_bits = self._get_signal_bits(
                existing.start_bit, existing.length, existing.byte_order
            )
            overlap = occupied & existing_bits
            if overlap:
                suggestion = self._find_next_available_start_bit(
                    msg, sig.length, sig.byte_order, exclude_uuid
                )
                return False, f"Signal overlaps with '{existing.name}'", {
                    "type": "overlap",
                    "signal_name": sig.name,
                    "conflicts_with": existing.name,
                    "conflicts_uuid": existing.uuid,
                    "overlapping_bits": sorted(overlap),
                    "suggestion": suggestion,
                }
        return True, "", {"type": "ok"}

    def validate_all_signals(self, msg_id: int) -> list[dict]:
        """验证报文中所有信号，返回全部错误列表（用于界面错误提示区）。"""
        msg = self.messages.get(msg_id)
        if not msg:
            return []
        errors: list[dict] = []
        max_bits = msg.dlc * 8
        n = len(msg.signals)
        for i in range(n):
            sig = msg.signals[i]
            occupied = self._get_signal_bits(sig.start_bit, sig.length, sig.byte_order)
            oob = [b for b in occupied if b < 0 or b >= max_bits]
            if oob:
                suggestion = self._find_next_available_start_bit(
                    msg, sig.length, sig.byte_order, sig.uuid
                )
                errors.append({
                    "type": "out_of_bounds",
                    "signal_uuid": sig.uuid,
                    "signal_name": sig.name,
                    "start_bit": sig.start_bit,
                    "length": sig.length,
                    "out_of_bounds_bits": sorted(oob)[:10],
                    "suggestion": suggestion,
                })
            for j in range(i + 1, n):
                other = msg.signals[j]
                other_bits = self._get_signal_bits(other.start_bit, other.length, other.byte_order)
                overlap = occupied & other_bits
                if overlap:
                    suggestion = self._find_next_available_start_bit(
                        msg, sig.length, sig.byte_order, sig.uuid
                    )
                    errors.append({
                        "type": "overlap",
                        "signal_uuid": sig.uuid,
                        "signal_name": sig.name,
                        "conflicts_uuid": other.uuid,
                        "conflicts_name": other.name,
                        "overlapping_bits": sorted(overlap),
                        "suggestion": suggestion,
                    })
        return errors

    def add_signal_to_message(self, msg_id: int, sig: Signal) -> bool:
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            self._ensure_sig_uuid_unique(msg, sig)
            msg.signals.append(sig)
            self.modified = True
            return True

    def remove_signal_from_message(self, msg_id: int, sig_uuid: str) -> bool:
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            for i, sig in enumerate(msg.signals):
                if sig.uuid == sig_uuid:
                    msg.signals.pop(i)
                    self.modified = True
                    return True
            return False

    def update_signal_in_message(
        self, msg_id: int, sig_uuid: str, **kwargs: Any
    ) -> bool:
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            for sig in msg.signals:
                if sig.uuid == sig_uuid:
                    changed = False
                    new_uuid = kwargs.get("uuid")
                    if new_uuid is not None and new_uuid != sig.uuid:
                        # 检查新 uuid 是否与同报文其他信号冲突
                        if any(s.uuid == new_uuid for s in msg.signals if s is not sig):
                            # 冲突：忽略 uuid 修改，保留原值
                            kwargs.pop("uuid", None)
                        else:
                            sig.uuid = new_uuid
                            changed = True
                    for k, v in kwargs.items():
                        if k == "uuid":
                            continue
                        if hasattr(sig, k) and getattr(sig, k) != v:
                            setattr(sig, k, v)
                            changed = True
                    if changed:
                        self.modified = True
                    return True
            return False

    def total_signals(self) -> int:
        with self.__lock:
            return sum(len(m.signals) for m in self.messages.values())

    # ── 序列化 ──

    def to_dict(self) -> dict:
        with self.__lock:
            return {
                "name": self.name,
                "messages": {
                    f"0x{mid:X}": m.to_dict() for mid, m in sorted(self.messages.items())
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

        with self.__lock:
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
        """导出为 DBC 格式字符串（使用 cantools 库）。"""
        import cantools.database
        from cantools.database.conversion import IdentityConversion, LinearConversion
        
        with self.__lock:
            # 构建 cantools database 对象
            can_db = cantools.database.Database()
            
            for msg in sorted(self.messages.values(), key=lambda m: m.id):
                can_signals = []
                
                for sig in msg.signals:
                    # 确定转换类型
                    if sig.factor == 1.0 and sig.offset == 0.0:
                        conversion = IdentityConversion(is_float=False)
                    else:
                        conversion = LinearConversion(
                            scale=sig.factor,
                            offset=sig.offset,
                            is_float=False,
                        )
                    
                    # 构建 cantools Signal
                    can_sig = cantools.database.Signal(
                        name=sig.name,
                        start=sig.start_bit,
                        length=sig.length,
                        # cantools 要求 byte_order 为 'little_endian' 或 'big_endian'
                        byte_order="big_endian" if sig.byte_order == "motorola" else "little_endian",
                        is_signed=sig.is_signed,
                        unit=sig.unit if sig.unit else None,
                        minimum=sig.min_val if sig.min_val != 0.0 else None,
                        maximum=sig.max_val if sig.max_val != 0.0 else None,
                        comment=sig.comment if sig.comment else None,
                        receivers=sig.receivers[:] if sig.receivers else [],
                        conversion=conversion,
                        is_multiplexer=(sig.multiplexer_mode == "multiplexer"),
                        multiplexer_ids=[sig.multiplexer_value] if sig.multiplexer_mode == "multiplexed" else None,
                    )
                    can_signals.append(can_sig)
                
                can_msg = cantools.database.Message(
                    frame_id=msg.id,
                    name=msg.name,
                    length=msg.dlc,
                    signals=can_signals,
                    comment=msg.comment if msg.comment else None,
                    senders=[sender] if (sender := msg.sender) else [],
                    cycle_time=msg.cycle_time if msg.cycle_time > 0 else None,
                )
                can_db.messages.append(can_msg)
            
            # 使用 cantools 导出为标准 DBC 字符串
            return can_db.as_dbc_string()

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
            msg = Message({
                "id": mid,
                "name": m_dict.get("name", ""),
                "dlc": m_dict.get("dlc", 8),
                "cycle_time": m_dict.get("cycle_time", 0),
                "sender": m_dict.get("sender", ""),
                "comment": m_dict.get("comment", ""),
            })
            for s_dict in m_dict.get("signals", []):
                msg.signals.append(Signal.from_dict(s_dict))
            db.messages[mid] = msg
        return db


_SIGNAL_DEFAULTS = {
    "name": "",
    "start_bit": 0,
    "length": 8,
    "byte_order": "motorola",
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


def _resp(success: bool, data: Any = None, error: str = "", details: dict | None = None) -> dict:
    """统一JSON响应格式。"""
    result = {"success": success, "data": data, "error": error}
    if details is not None:
        result["details"] = details
    return result


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
        t_resp_start = time.monotonic()
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()
        elapsed = (time.monotonic() - t_resp_start) * 1000
        print(f"[API] response: {status} {len(payload)} bytes +{elapsed:.1f}ms")

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
        """变更后自动保存（延迟写入，不阻塞 API 响应）。"""
        session_id = self.headers.get("X-Session-Id", "")
        if session_id:
            # 在后台线程中延迟保存，避免阻塞 HTTP 响应
            def _save_later(sid):
                import time as _t
                _t.sleep(0.5)  # 延迟 500ms，等待响应返回客户端
                t_save = time.monotonic()
                print(f"[API] auto_save START session={sid[:8]}...")
                try:
                    SESSION_MGR.save(sid)
                    elapsed = (time.monotonic() - t_save) * 1000
                    print(f"[API] auto_save DONE +{elapsed:.1f}ms")
                except Exception as e:
                    print(f"[WARN] auto_save failed for session {sid}: {e}")
            threading.Thread(target=_save_later, args=(session_id,), daemon=True).start()

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
        t_start = time.monotonic()
        try:
            self._handle_GET()
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] GET {self.path} DONE +{elapsed:.1f}ms")
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
        else:
            self._serve_static()

    def do_POST(self) -> None:
        t_start = time.monotonic()
        try:
            self._handle_POST()
            elapsed = (time.monotonic() - t_start) * 1000
            print(f"[API] POST {self.path} DONE +{elapsed:.1f}ms")
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
        elif parts == ["api", "save"]:
            self._post_save()
        elif parts == ["api", "release"]:
            self._post_release()
        elif parts == ["api", "heartbeat"]:
            self._post_heartbeat()
        elif parts == ["api", "steal"]:
            self._post_steal()
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
        t_start = time.monotonic()
        parts = self._path_parts()
        if len(parts) == 3 and parts[0:2] == ["api", "messages"]:
            # PUT /api/messages/{id}
            self._put_message(parts[2])
        elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
            # PUT /api/messages/{id}/signals/{uuid}
            self._put_signal(parts[2], parts[4])
        elif parts == ["api", "session"]:
            # PUT /api/session - 更新数据库名称
            self._put_session()
        else:
            self._send_json(404, _resp(False, error="Not found"))
        elapsed = (time.monotonic() - t_start) * 1000
        print(f"[API] PUT {self.path} DONE +{elapsed:.1f}ms")

    def do_DELETE(self) -> None:
        t_start = time.monotonic()
        parts = self._path_parts()
        if len(parts) == 3 and parts[0:2] == ["api", "messages"]:
            # DELETE /api/messages/{id}
            self._delete_message(parts[2])
        elif len(parts) == 5 and parts[0:3] == ["api", "messages", parts[2]] and parts[3] == "signals":
            # DELETE /api/messages/{id}/signals/{uuid}
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
        """
        session_id = self.headers.get("X-Session-Id", "")
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

    def _post_release(self) -> None:
        """POST /api/release - 主动释放当前 session 的文件锁。

        支持从 X-Session-Id 请求头或 URL 查询参数 ?sid=xxx 读取 session ID，
        以便 navigator.sendBeacon() 使用（beacon 不支持自定义请求头）。
        """
        sid = self.headers.get("X-Session-Id", "")
        if not sid:
            params = self._url_params()
            sid_list = params.get("sid", [])
            if sid_list:
                sid = sid_list[0]
        if sid:
            SESSION_MGR.release_session(sid)
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
        会先保存目标 session 的数据，避免数据丢失。
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
        
        # 先保存目标 session 的数据（避免数据丢失）
        SESSION_MGR.save(target_sid)
        
        # 释放目标 session 的文件锁
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
                        
                        msg = Message({
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
                            
                            sig = Signal({
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
            if not db.move_message(msg_id, new_id):
                self._send_json(409, _resp(False, error=f"Message 0x{new_id:X} already exists"))
                return
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
        """PUT /api/messages/{id}/signals/{uuid} - 更新信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        body = self._read_body()
        ok = db.update_signal_in_message(msg_id, idx_str, **body)
        if not ok:
            self._send_json(404, _resp(False, error="Message or signal not found"))
            return
        msg = db.get_message(msg_id)
        sig = next((s for s in msg.signals if s.uuid == idx_str), None) if msg else None
        self._auto_save()
        self._send_json(200, _resp(True, sig.to_dict() if sig else {}))

    def _delete_signal(self, id_str: str, uuid_str: str) -> None:
        """DELETE /api/messages/{id}/signals/{uuid} - 删除信号。"""
        db = self._get_db()
        msg_id = _parse_id(id_str)
        if msg_id is None:
            self._send_json(400, _resp(False, error="Invalid message ID"))
            return
        ok = db.remove_signal_from_message(msg_id, uuid_str)
        if not ok:
            self._send_json(404, _resp(False, error=f"Message or signal not found"))
            return
        self._auto_save()
        self._send_json(200, _resp(True, {"deleted": uuid_str}))


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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
