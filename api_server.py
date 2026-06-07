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
        """导出为 DBC 格式字符串。"""
        with self.__lock:
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
                    byte_order = 1 if sig.byte_order == "motorola" else 0
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
                        lines.append(f"CM_ SG_ {mid} {sig.name} \"{self._escape_dbc_string(sig.comment)}\"")

            # 报文注释
            for mid in sorted(self.messages):
                msg = self.messages[mid]
                if msg.comment:
                    lines.append(f"CM_ BO_ {mid} \"{self._escape_dbc_string(msg.comment)}\"")

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
        elif parts == ["api", "release"]:
            self._post_release()
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

    def _post_release(self) -> None:
        """POST /api/release - 主动释放当前 session 的文件锁。"""
        sid = self.headers.get("X-Session-Id", "")
        if sid:
            SESSION_MGR.release_session(sid)
        self._send_json(200, _resp(True))

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
