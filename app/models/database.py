"""CanDatabase — 顶层 CAN 数据库。

信号是 per-message 定义，无全局信号注册表。
包含完整的 CRUD、验证、序列化功能。
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from .signal import Signal
from .message import Message


# ---------------------------------------------------------------------------
# 信号默认值表（用于 Properties 序列化时省略默认值）
# ---------------------------------------------------------------------------

_SIGNAL_DEFAULTS = {
    "uuid": "",
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


# ---------------------------------------------------------------------------
# Properties dotted keys 辅助函数
# ---------------------------------------------------------------------------

def _make_signal_key(sig: Signal, seen: set[str]) -> str:
    """为信号生成唯一 Properties key。优先用 name，空名/重名时回退到 uuid。"""
    name = sig.name.strip() if sig.name else ""
    if name and name not in seen:
        seen.add(name)
        return name
    fallback = sig.uuid or uuid.uuid4().hex[:8]
    if fallback in seen:
        counter = len(seen)
        while f"{fallback}_{counter}" in seen:
            counter += 1
        fallback = f"{fallback}_{counter}"
    seen.add(fallback)
    return fallback


class CanDatabase:
    """顶层 CAN 数据库。

    信号是 per-message 定义，无全局信号注册表。
    包含完整的 CRUD、验证、序列化功能。
    """

    # 合法 DLC 值集合（CAN 2.0B + CAN FD）
    VALID_DLC_VALUES = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64})

    def __init__(self, name: str = "Untitled") -> None:
        self.name: str = name
        self.messages: dict[int, Message] = {}
        self.modified: bool = False
        self.__lock = threading.RLock()
        self.data_version: int = 0  # WS 版本号，每次变更 +1

    def with_lock(self):
        """返回锁上下文管理器，供外部需要原子操作时使用。"""
        return self.__lock

    def _bump_version(self) -> int:
        """原子递增版本号。必须在 __lock 持有下调用。
        返回新版本号，调用方应使用返回值而非再次读取 data_version。"""
        self.data_version += 1
        return self.data_version

    def _bump_version_safe(self) -> int:
        """带锁的安全版本，供锁外调用方使用。"""
        with self.__lock:
            self.data_version += 1
            return self.data_version

    # ── 报文操作 ─────────────────────────────────────────────────────────

    def add_message(self, msg: Message) -> bool:
        """添加或替换报文。"""
        with self.__lock:
            if msg.id in self.messages:
                return False
            self.messages[msg.id] = msg
            self.modified = True
            return True

    def remove_message(self, msg_id: int) -> Message | None:
        """删除报文。"""
        with self.__lock:
            msg = self.messages.pop(msg_id, None)
            if msg:
                self.modified = True
            return msg

    def get_message(self, msg_id: int) -> Message | None:
        """获取报文。"""
        with self.__lock:
            return self.messages.get(msg_id)

    def update_message(self, msg_id: int, **kwargs: Any) -> bool:
        """更新报文属性。"""
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            kwargs.pop("id", None)  # ID 不可修改
            changed = False
            for k, v in kwargs.items():
                if hasattr(msg, k) and getattr(msg, k) != v:
                    setattr(msg, k, v)
                    changed = True
            if changed:
                self.modified = True
            return True

    def validate_message_fields(self, msg_id: int, updates: dict) -> tuple[bool, str, dict]:
        """校验报文更新字段。返回 (ok, error_msg, details)。"""
        # #3: name 非空
        if "name" in updates:
            name = updates["name"]
            if not isinstance(name, str) or not name.strip():
                return False, "Message name cannot be empty", {
                    "error_code": "message_name_empty", "field": "name"
                }

        # #4: DLC 范围
        if "dlc" in updates:
            dlc = updates["dlc"]
            if dlc is None or not isinstance(dlc, (int, float)):
                return False, f"Invalid DLC value, valid: {sorted(self.VALID_DLC_VALUES)}", {
                    "error_code": "dlc_invalid", "field": "dlc",
                    "valid_values": sorted(self.VALID_DLC_VALUES)
                }
            try:
                dlc_int = int(dlc)
            except (ValueError, TypeError):
                return False, f"Invalid DLC value, valid: {sorted(self.VALID_DLC_VALUES)}", {
                    "error_code": "dlc_invalid", "field": "dlc",
                    "valid_values": sorted(self.VALID_DLC_VALUES)
                }
            if dlc_int not in self.VALID_DLC_VALUES:
                return False, f"Invalid DLC value, valid: {sorted(self.VALID_DLC_VALUES)}", {
                    "error_code": "dlc_invalid", "field": "dlc",
                    "valid_values": sorted(self.VALID_DLC_VALUES)
                }
            # DLC 缩小时检查现有信号是否越界
            msg = self.messages.get(msg_id)
            if msg and dlc_int < msg.dlc:
                max_bits = dlc_int * 8
                for sig in msg.signals:
                    sig_bits = self._get_signal_bits(sig.start_bit, sig.length, sig.byte_order)
                    oob = [b for b in sig_bits if b >= max_bits]
                    if oob:
                        return False, f"DLC reduction would make signal '{sig.name}' out of bounds", {
                            "error_code": "dlc_reduce_conflict", "field": "dlc",
                            "name": sig.name, "new_max_bit": max_bits - 1
                        }

        return True, "", {"error_code": "ok"}

    def move_message(self, old_id: int, new_id: int) -> bool:
        """修改报文 ID。"""
        with self.__lock:
            if new_id in self.messages or old_id not in self.messages:
                return False
            msg = self.messages.pop(old_id)
            msg.id = new_id
            self.messages[new_id] = msg
            self.modified = True
            return True

    # ── 信号操作 ─────────────────────────────────────────────────────────

    def _ensure_sig_uuid_unique(
        self, msg: Message, sig: Signal, exclude_sig: Signal | None = None
    ) -> None:
        """若 sig.uuid 与 msg 中其他信号冲突，则重新生成。"""
        existing = {s.uuid for s in msg.signals if s is not exclude_sig}
        while sig.uuid in existing:
            sig.uuid = uuid.uuid4().hex[:8]

    def add_signal_to_message(self, msg_id: int, sig: Signal) -> bool:
        """添加信号到报文。"""
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            self._ensure_sig_uuid_unique(msg, sig)
            msg.signals.append(sig)
            self.modified = True
            return True

    def remove_signal_from_message(self, msg_id: int, sig_uuid: str) -> bool:
        """从报文中删除信号。"""
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
        """更新信号属性。"""
        with self.__lock:
            msg = self.messages.get(msg_id)
            if not msg:
                return False
            for sig in msg.signals:
                if sig.uuid == sig_uuid:
                    changed = False
                    new_uuid = kwargs.get("uuid")
                    if new_uuid is not None and new_uuid != sig.uuid:
                        if any(s.uuid == new_uuid for s in msg.signals if s is not sig):
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
        """获取信号总数。"""
        with self.__lock:
            return sum(len(m.signals) for m in self.messages.values())

    # ── 信号有效性检查（DBC 标准）───────────────────────────────────────

    @staticmethod
    def _get_signal_bits(start_bit: int, length: int, byte_order: str) -> set[int]:
        """将信号按字节序展开为占用的物理 bit 集合。"""
        bits: set[int] = set()
        bo = str(byte_order).lower() if byte_order else "motorola"
        if bo == "motorola":
            current_bit = start_bit
            for _ in range(length):
                bits.add(current_bit)
                if current_bit % 8 == 0:
                    current_bit = current_bit + 15
                else:
                    current_bit = current_bit - 1
        else:
            for i in range(length):
                bits.add(start_bit + i)
        return bits

    def _find_next_available_start_bit(
        self, msg: Message, length: int, byte_order: str, exclude_uuid: str | None = None
    ) -> dict | None:
        """在报文中寻找第一个足够大的空闲区间。"""
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
        """验证信号是否可以加入/更新到报文中。返回 (is_valid, error_message, details)。"""
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
        occupied = self._get_signal_bits(sig.start_bit, sig.length, sig.byte_order)
        oob = [b for b in occupied if b < 0 or b >= max_bits]
        if oob:
            suggestion = self._find_next_available_start_bit(
                msg, sig.length, sig.byte_order, exclude_uuid
            )
            return False, f"Signal out of bounds (DLC={msg.dlc}, max bit={max_bits - 1})", {
                "type": "out_of_bounds",
                "error_code": "signal_out_of_bounds",
                "signal_name": sig.name,
                "start_bit": sig.start_bit,
                "length": sig.length,
                "byte_order": sig.byte_order,
                "dlc": msg.dlc,
                "max_bit": max_bits - 1,
                "out_of_bounds_bits": sorted(oob)[:10],
                "suggestion": suggestion,
            }
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
                    "error_code": "signal_overlap",
                    "name": sig.name,
                    "other": existing.name,
                    "signal_name": sig.name,
                    "conflicts_with": existing.name,
                    "conflicts_uuid": existing.uuid,
                    "overlapping_bits": sorted(overlap),
                    "suggestion": suggestion,
                }
        return True, "", {"type": "ok"}

    def validate_all_signals(self, msg_id: int) -> list[dict]:
        """验证报文中所有信号，返回全部错误列表。"""
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

    # ── 序列化 ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（API 响应使用）。"""
        with self.__lock:
            return {
                "name": self.name,
                "messages": {
                    f"0x{mid:X}": m.to_dict() for mid, m in sorted(self.messages.items())
                },
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """从字典创建。"""
        db = cls(name=data.get("name", "Untitled"))
        for mid_str, mdata in data.get("messages", {}).items():
            try:
                mid = int(mid_str, 16) if mid_str.startswith("0x") else int(mid_str)
            except (ValueError, TypeError):
                continue
            mdata["id"] = mid
            msg = Message.from_dict(mdata)
            db.messages[mid] = msg
        return db

    def to_json_dict(self) -> dict[str, Any]:
        """JSON 序列化（与 to_dict 相同）。"""
        return self.to_dict()

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """JSON 反序列化。"""
        return cls.from_dict(data)

    def to_flat_dict(self) -> dict[str, Any]:
        """扁平字典结构（供 XML 等格式复用）。"""
        with self.__lock:
            return {
                "database": {"name": self.name},
                "messages": [
                    msg.to_dict()
                    for msg in sorted(self.messages.values(), key=lambda m: m.id)
                ],
            }

    @classmethod
    def from_flat_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """从扁平字典创建。"""
        db_info = data.get("database", {})
        db = cls(name=str(db_info.get("name", "Untitled")))
        for msg_data in data.get("messages", []):
            msg = Message.from_dict(msg_data)
            db.messages[msg.id] = msg
        return db

    def to_properties_str(self) -> str:
        """序列化为 Java Properties 字符串（O(n) 线性性能）。"""
        import json as _json
        import javaproperties

        with self.__lock:
            props: dict[str, str] = {}
            props["database.name"] = self.name

            for mid in sorted(self.messages):
                msg = self.messages[mid]
                mid_key = f"0x{mid:X}"
                mp = f"messages.{mid_key}"

                props[f"{mp}.name"] = msg.name
                props[f"{mp}.dlc"] = str(msg.dlc)
                props[f"{mp}.cycle_time"] = str(msg.cycle_time)
                if msg.sender:
                    props[f"{mp}.sender"] = msg.sender
                if msg.comment:
                    props[f"{mp}.comment"] = msg.comment

                if msg.signals:
                    seen: set[str] = set()
                    for sig in msg.signals:
                        sig_key = _make_signal_key(sig, seen)
                        sp = f"{mp}.signals.{sig_key}"

                        props[f"{sp}.uuid"] = sig.uuid
                        props[f"{sp}.name"] = sig.name
                        props[f"{sp}.start_bit"] = str(sig.start_bit)
                        props[f"{sp}.length"] = str(sig.length)
                        props[f"{sp}.byte_order"] = sig.byte_order

                        if sig.is_signed != _SIGNAL_DEFAULTS["is_signed"]:
                            props[f"{sp}.is_signed"] = str(sig.is_signed).lower()
                        if sig.factor != _SIGNAL_DEFAULTS["factor"]:
                            props[f"{sp}.factor"] = repr(sig.factor)
                        if sig.offset != _SIGNAL_DEFAULTS["offset"]:
                            props[f"{sp}.offset"] = repr(sig.offset)
                        if sig.min_val != _SIGNAL_DEFAULTS["min_val"]:
                            props[f"{sp}.min_val"] = repr(sig.min_val)
                        if sig.max_val != _SIGNAL_DEFAULTS["max_val"]:
                            props[f"{sp}.max_val"] = repr(sig.max_val)
                        if sig.unit:
                            props[f"{sp}.unit"] = sig.unit
                        if sig.comment:
                            props[f"{sp}.comment"] = sig.comment
                        if sig.receivers:
                            props[f"{sp}.receivers"] = _json.dumps(sig.receivers)
                        if sig.multiplexer_mode != _SIGNAL_DEFAULTS["multiplexer_mode"]:
                            props[f"{sp}.multiplexer_mode"] = sig.multiplexer_mode
                            if sig.multiplexer_mode == "multiplexed":
                                props[f"{sp}.multiplexer_value"] = str(sig.multiplexer_value)

            return javaproperties.dumps(
                props,
                comments="CanMatrix Editor - CAN Database Definition",
                timestamp=False,
                ensure_ascii=False,
            )

    @classmethod
    def from_properties_str(cls, content: str) -> CanDatabase:
        """从 Java Properties 字符串创建（O(n) 性能）。"""
        import json as _json
        import javaproperties

        props = javaproperties.loads(content)
        db_name = props.get("database.name", "Untitled")
        db = cls(name=db_name)

        messages_data: dict[str, dict] = {}

        for key, value in props.items():
            if not key.startswith("messages."):
                continue
            rest = key[len("messages."):]
            parts = rest.split(".", 1)
            if len(parts) < 2:
                continue
            mid_key, field_path = parts

            if mid_key not in messages_data:
                messages_data[mid_key] = {"signals": {}}
            msg_d = messages_data[mid_key]

            if not field_path.startswith("signals."):
                msg_d[field_path] = value
            else:
                sig_rest = field_path[len("signals."):]
                sig_parts = sig_rest.split(".", 1)
                if len(sig_parts) == 2:
                    sig_key, sig_field = sig_parts
                    if sig_key not in msg_d["signals"]:
                        msg_d["signals"][sig_key] = {}
                    msg_d["signals"][sig_key][sig_field] = value

        for mid_key, msg_d in messages_data.items():
            try:
                mid = int(mid_key, 16) if mid_key.startswith("0x") else int(mid_key)
            except (ValueError, TypeError):
                continue

            msg = Message(
                id=mid,
                name=msg_d.get("name", ""),
                dlc=int(msg_d.get("dlc", 8)),
                cycle_time=int(msg_d.get("cycle_time", 0)),
                sender=msg_d.get("sender", ""),
                comment=msg_d.get("comment", ""),
            )

            for _sig_key, sig_d in msg_d.get("signals", {}).items():
                receivers_raw = sig_d.get("receivers", "")
                if receivers_raw:
                    try:
                        receivers = _json.loads(receivers_raw)
                    except (ValueError, TypeError):
                        receivers = []
                else:
                    receivers = []

                msg.signals.append(Signal.from_dict({
                    "uuid": sig_d.get("uuid", ""),
                    "name": sig_d.get("name", ""),
                    "start_bit": int(sig_d.get("start_bit", 0)),
                    "length": int(sig_d.get("length", 8)),
                    "byte_order": sig_d.get("byte_order", "motorola"),
                    "is_signed": sig_d.get("is_signed", "false").lower() == "true",
                    "factor": float(sig_d.get("factor", 1.0)),
                    "offset": float(sig_d.get("offset", 0.0)),
                    "min_val": float(sig_d.get("min_val", 0.0)),
                    "max_val": float(sig_d.get("max_val", 0.0)),
                    "unit": sig_d.get("unit", ""),
                    "comment": sig_d.get("comment", ""),
                    "receivers": receivers,
                    "multiplexer_mode": sig_d.get("multiplexer_mode", "none"),
                    "multiplexer_value": int(sig_d.get("multiplexer_value", 0)),
                }))

            db.messages[mid] = msg
        return db

    def to_xml_dict(self) -> dict[str, Any]:
        """XML 友好的字典结构。"""
        return self.to_flat_dict()

    @classmethod
    def from_xml_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """从 XML 字典创建。"""
        return cls.from_flat_dict(data)

    # ── DBC 序列化 ─────────────────────────────────────────────────────

    def to_dbc_str(self) -> str:
        """导出为 DBC 格式字符串（使用 cantools 库）。"""
        import cantools.database
        from cantools.database.conversion import IdentityConversion, LinearConversion
        
        with self.__lock:
            can_db = cantools.database.Database()
            
            for msg in sorted(self.messages.values(), key=lambda m: m.id):
                can_signals = []
                
                for sig in msg.signals:
                    if sig.factor == 1.0 and sig.offset == 0.0:
                        conversion = IdentityConversion(is_float=False)
                    else:
                        conversion = LinearConversion(
                            scale=sig.factor,
                            offset=sig.offset,
                            is_float=False,
                        )
                    
                    can_sig = cantools.database.Signal(
                        name=sig.name,
                        start=sig.start_bit,
                        length=sig.length,
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
            
            return can_db.as_dbc_string()

    def to_c_header_str(self) -> str:
        """导出为 C 头文件字符串（Jinja2 模板渲染）。"""
        from app.io.c_code_gen import to_c_header_str
        return to_c_header_str(self)

    def to_c_source_str(self) -> str:
        """导出为 C 源文件字符串（Jinja2 模板渲染）。"""
        from app.io.c_code_gen import to_c_source_str
        return to_c_source_str(self)

    @classmethod
    def from_dbc_str(cls, content: str) -> CanDatabase:
        """从 DBC 格式解析（使用 cantools 库）。"""
        import cantools.database
        
        can_db = cantools.database.load_string(content, database_format='dbc')
        db = cls(name="Imported from DBC")
        
        for can_msg in can_db.messages:
            cycle_time = 0
            try:
                if can_msg.cycle_time is not None:
                    cycle_time = int(can_msg.cycle_time)
            except Exception:
                pass
            sender = ""
            try:
                senders = getattr(can_msg, "senders", None)
                if senders and isinstance(senders, list) and len(senders) > 0:
                    sender = str(senders[0])
            except Exception:
                pass
            msg = Message.from_dict({
                "id": can_msg.frame_id,
                "name": can_msg.name,
                "dlc": can_msg.length,
                "cycle_time": cycle_time,
                "comment": str(can_msg.comment) if can_msg.comment else "",
                "sender": sender,
            })
            
            for can_sig in can_msg.signals:
                bo = can_sig.byte_order
                order_str = bo.name.lower() if hasattr(bo, "name") else str(bo).lower()
                if order_str in ("little", "little_endian", "intel"):
                    order_str = "intel"
                elif order_str in ("big", "big_endian", "motorola"):
                    order_str = "motorola"
                mux_mode = "none"
                mux_value = 0
                if can_sig.is_multiplexer:
                    mux_mode = "multiplexer"
                elif can_sig.multiplexer_ids:
                    mux_mode = "multiplexed"
                    mux_value = can_sig.multiplexer_ids[0]
                sig = Signal.from_dict({
                    "name": can_sig.name,
                    "start_bit": can_sig.start,
                    "length": can_sig.length,
                    "byte_order": order_str,
                    "is_signed": can_sig.is_signed,
                    "factor": float(can_sig.scale) if hasattr(can_sig, 'scale') else 1.0,
                    "offset": float(can_sig.offset) if hasattr(can_sig, 'offset') else 0.0,
                    "min_val": can_sig.minimum or 0.0,
                    "max_val": can_sig.maximum or 0.0,
                    "unit": str(can_sig.unit) if can_sig.unit else "",
                    "comment": str(can_sig.comment) if can_sig.comment else "",
                    "receivers": list(can_sig.receivers) if can_sig.receivers else [],
                    "multiplexer_mode": mux_mode,
                    "multiplexer_value": mux_value,
                })
                msg.signals.append(sig)
            
            db.messages[msg.id] = msg
        
        return db

    def _escape_dbc_string(self, s: str) -> str:
        """转义 DBC 字符串中的特殊字符。"""
        if not s:
            return ""
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
