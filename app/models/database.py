"""CanDatabase — 顶层 CAN 数据库。

信号是 per-message 定义，无全局信号注册表。
包含完整的 CRUD、验证、序列化功能。
"""

from __future__ import annotations

import logging
import math
import sys
import threading
from typing import Any

from .signal import Signal, SignalValueType
from .message import Message
from .can_id import CanIdError, parse_ref, to_key, validate_id

logger = logging.getLogger(__name__)

# IEEE 754 单精度最大有限值；双精度用 sys.float_info.max。
_FLT_MAX = 3.4028234663852886e38


def _as_float(value: int | float) -> float:
    """整数可能超过 float 上限；溢出按 ±inf 处理，随后统一钳制。"""
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


# ---------------------------------------------------------------------------
# 信号默认值表（用于 Properties 序列化时省略默认值）
# ---------------------------------------------------------------------------

_SIGNAL_DEFAULTS = {
    "name": "",
    "start_bit": 0,
    "length": 8,
    "byte_order": "motorola",
    "value_type": SignalValueType.UINT,
    "factor": 1.0,
    "offset": 0.0,
    "min_val": 0.0,
    "max_val": 0.0,
    "unit": "",
    "comment": "",
    "receivers": [],
    "multiplexer_mode": "none",
    "multiplexer_value": 0,
    "value_table_name": "",
}


# ---------------------------------------------------------------------------
# Properties dotted keys 辅助函数
# ---------------------------------------------------------------------------

def _make_signal_key(sig: Signal, seen: set[str]) -> str:
    """为信号生成唯一 Properties key。优先用 name，空名/重名时回退到 id(sig)。"""
    name = sig.name.strip() if sig.name else ""
    if name and name not in seen:
        seen.add(name)
        return name
    fallback = f"_unnamed_{id(sig)}"
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
        self.bus_type: str = "CAN"  # "CAN" 或 "CAN FD"，由用户显式配置
        self.messages: dict[str, Message] = {}
        self.modified: bool = False
        self.__lock = threading.RLock()
        self.data_version: int = 0  # WS 版本号，每次变更 +1
        self._validation_cache: dict[str, list[dict]] = {}  # msg_key -> 校验错误列表
        self.value_tables: dict[str, dict[str, str]] = {}  # 全局值描述表
        # DBC 导入产生的未采用属性/结构提示（瞬时，不持久化）
        self.import_warnings: list[dict] = []

    def with_lock(self):
        """返回锁上下文管理器，供外部需要原子操作时使用。"""
        return self.__lock

    def _bump_version(self) -> int:
        """原子递增版本号。必须在 __lock 持有下调用。
        返回新版本号，调用方应使用返回值而非再次读取 data_version。"""
        self.data_version += 1
        return self.data_version

    # ── 值描述表操作 ─────────────────────────────────────────────────

    def add_value_table(self, name: str, entries: dict[str, str]) -> bool:
        """新增全局值描述表。name 已存在返回 False。"""
        with self.__lock:
            if name in self.value_tables:
                return False
            self.value_tables[name] = dict(entries)
            self.modified = True
            return True

    def remove_value_table(self, name: str) -> tuple[bool, int]:
        """删除值描述表。有引用时拒绝。返回 (success, ref_count)。"""
        with self.__lock:
            if name not in self.value_tables:
                return False, 0
            ref_count = self._count_value_table_refs(name)
            if ref_count > 0:
                return False, ref_count
            del self.value_tables[name]
            self.modified = True
            return True, 0

    def update_value_table(self, name: str, entries: dict[str, str]) -> bool:
        """更新值描述表内容。name 不存在返回 False。"""
        with self.__lock:
            if name not in self.value_tables:
                return False
            self.value_tables[name] = dict(entries)
            self.modified = True
            return True

    def rename_value_table(self, old_name: str, new_name: str) -> bool:
        """重命名 + 级联更新引用信号。O(n) 全量扫描。"""
        with self.__lock:
            if old_name not in self.value_tables or new_name in self.value_tables:
                return False
            self.value_tables[new_name] = self.value_tables.pop(old_name)
            for m in self.messages.values():
                for s in m.signals.values():
                    if s.value_table_name == old_name:
                        s.value_table_name = new_name
            self.modified = True
            return True

    def get_value_tables(self) -> dict[str, dict[str, str]]:
        """返回全局值描述表的深拷贝。"""
        with self.__lock:
            return {k: dict(v) for k, v in self.value_tables.items()}

    def _count_value_table_refs(self, table_name: str) -> int:
        """统计引用计数。**不加锁**，必须在已有 __lock 内调用。"""
        return sum(1 for m in self.messages.values()
                   for s in m.signals.values() if s.value_table_name == table_name)

    # ── 报文操作 ─────────────────────────────────────────────────────────

    def sorted_keys(self) -> list[str]:
        """按 CAN ID + 帧类型排序的报文 key 列表。**不加锁**。"""
        return sorted(
            self.messages,
            key=lambda k: self.messages[k].sort_key,
        )

    def add_message(self, msg: Message) -> bool:
        """添加报文。"""
        with self.__lock:
            key = msg.key
            if key in self.messages:
                return False
            self.messages[key] = msg
            self.modified = True
            return True

    def remove_message(self, msg_key: str) -> Message | None:
        """删除报文。"""
        with self.__lock:
            msg = self.messages.pop(msg_key, None)
            if msg:
                self.modified = True
            return msg

    def get_message(self, msg_key: str) -> Message | None:
        """获取报文。"""
        with self.__lock:
            return self.messages.get(msg_key)

    def update_message(self, msg_key: str, **kwargs: Any) -> bool:
        """更新报文属性。"""
        with self.__lock:
            msg = self.messages.get(msg_key)
            if not msg:
                return False
            kwargs.pop("id", None)  # ID 通过 move_message 修改
            kwargs.pop("can_id", None)
            kwargs.pop("is_extended_frame", None)
            changed = False
            for k, v in kwargs.items():
                if hasattr(msg, k) and getattr(msg, k) != v:
                    setattr(msg, k, v)
                    changed = True
            if changed:
                self.modified = True
            return True

    # 经典 CAN 允许的 DLC 值（1~8）
    CLASSIC_CAN_DLC_VALUES = frozenset({1, 2, 3, 4, 5, 6, 7, 8})

    def validate_message_fields(self, msg_key: str, updates: dict) -> tuple[bool, str, dict]:
        """校验报文更新字段。返回 (ok, error_msg, details)。"""
        # #3: name 非空
        if "name" in updates:
            name = updates["name"]
            if not isinstance(name, str) or not name.strip():
                return False, "Message name cannot be empty", {
                    "error_code": "message_name_empty", "field": "name"
                }

        # CAN ID / 帧类型
        if "id" in updates or "is_extended_frame" in updates:
            msg = self.messages.get(msg_key)
            raw_id = updates.get("id", msg.can_id if msg else 0)
            if isinstance(raw_id, str):
                try:
                    raw_id = int(raw_id, 0)
                except ValueError:
                    return False, "Invalid CAN ID", {
                        "error_code": "message_id_invalid", "field": "id"
                    }
            if isinstance(raw_id, bool) or not isinstance(raw_id, int):
                return False, "Invalid CAN ID", {
                    "error_code": "message_id_invalid", "field": "id"
                }
            is_extended = updates.get(
                "is_extended_frame", msg.is_extended_frame if msg else False
            )
            if not isinstance(is_extended, bool):
                return False, "is_extended_frame must be a boolean", {
                    "error_code": "message_frame_type_invalid", "field": "is_extended_frame"
                }
            try:
                validate_id(raw_id, is_extended)
            except CanIdError as e:
                return False, str(e), {
                    "error_code": "message_id_out_of_range",
                    "field": "id",
                    "can_id": raw_id,
                    "is_extended_frame": is_extended,
                }

        # is_fd 类型校验
        if "is_fd" in updates:
            if not isinstance(updates["is_fd"], bool):
                return False, "is_fd must be a boolean", {
                    "error_code": "is_fd_invalid", "field": "is_fd"
                }
            # is_fd 切换兼容性校验：切换为经典 CAN 时，当前 DLC 必须 ≤ 8
            if not updates["is_fd"] and "dlc" not in updates:
                msg = self.messages.get(msg_key)
                if msg and msg.dlc not in self.CLASSIC_CAN_DLC_VALUES:
                    return False, f"Classic CAN only supports DLC 1-8, current DLC is {msg.dlc}", {
                        "error_code": "dlc_fd_only", "field": "is_fd",
                        "valid_values": sorted(self.CLASSIC_CAN_DLC_VALUES),
                        "is_fd": msg.is_fd  # 返回当前正确的值
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
            # 根据 is_fd 限制 DLC 范围
            is_fd = updates.get("is_fd")
            if is_fd is None:
                msg = self.messages.get(msg_key)
                is_fd = msg.is_fd if msg else False
            if not is_fd and dlc_int not in self.CLASSIC_CAN_DLC_VALUES:
                return False, f"Classic CAN only supports DLC 1-8, got {dlc_int}", {
                    "error_code": "dlc_fd_only", "field": "dlc",
                    "valid_values": sorted(self.CLASSIC_CAN_DLC_VALUES)
                }
            # A1 已延后：DLC 缩小导致的信号越界由 validate_data_integrity() 检测

        # sender 校验
        if "sender" in updates:
            sender = updates["sender"]
            if not isinstance(sender, str):
                return False, "sender must be a string", {
                    "error_code": "sender_invalid", "field": "sender"
                }
            if len(sender) > 128:
                return False, "sender must be at most 128 characters", {
                    "error_code": "sender_too_long", "field": "sender"
                }

        # comment 校验
        if "comment" in updates:
            comment = updates["comment"]
            if not isinstance(comment, str):
                return False, "comment must be a string", {
                    "error_code": "comment_invalid", "field": "comment"
                }
            if len(comment) > 1024:
                return False, "comment must be at most 1024 characters", {
                    "error_code": "comment_too_long", "field": "comment"
                }

        return True, "", {"error_code": "ok"}

    def move_message(
        self, old_key: str, new_can_id: int, new_is_extended: bool | None = None
    ) -> str | None:
        """修改报文 ID / 帧类型，返回新的 key；失败返回 None。"""
        with self.__lock:
            msg = self.messages.get(old_key)
            if msg is None:
                return None
            if new_is_extended is None:
                new_is_extended = msg.is_extended_frame
            try:
                new_key = to_key(new_can_id, new_is_extended)
            except CanIdError:
                return None
            if new_key == old_key:
                return old_key
            if new_key in self.messages:
                return None
            del self.messages[old_key]
            msg.can_id = new_can_id
            msg.is_extended_frame = new_is_extended
            self.messages[new_key] = msg
            self.modified = True
            return new_key

    # ── 信号操作 ─────────────────────────────────────────────────────────

    def add_signal_to_message(self, msg_key: str, sig: Signal) -> bool:
        """添加信号到报文。信号以 name 为 key 存入 dict。"""
        with self.__lock:
            msg = self.messages.get(msg_key)
            if not msg:
                return False
            msg.signals[sig.name] = sig
            self.modified = True
            return True

    def remove_signal_from_message(self, msg_key: str, sig_name: str) -> bool:
        """从报文中删除信号。"""
        with self.__lock:
            msg = self.messages.get(msg_key)
            if not msg:
                return False
            if sig_name in msg.signals:
                del msg.signals[sig_name]
                self.modified = True
                return True
            return False

    def update_signal_in_message(
        self, msg_key: str, sig_name: str, **kwargs: Any
    ) -> tuple[bool, str | None]:
        """更新信号属性。返回 (success, old_name_if_renamed)。

        重命名时自动更新 dict key。"""
        with self.__lock:
            msg = self.messages.get(msg_key)
            if not msg:
                return False, None
            sig = msg.signals.get(sig_name)
            if sig is None:
                return False, None
            changed = False
            old_name = None
            new_name = kwargs.pop("name", None)
            if new_name is not None and new_name != sig.name:
                # 重命名：检查新名是否冲突
                if new_name in msg.signals:
                    kwargs.pop("name", None)  # 新名冲突，忽略改名
                else:
                    old_name = sig.name
                    sig.name = new_name
                    # 更新 dict key
                    del msg.signals[old_name]
                    msg.signals[new_name] = sig
                    changed = True
            for k, v in kwargs.items():
                if hasattr(sig, k) and getattr(sig, k) != v:
                    setattr(sig, k, v)
                    changed = True
            if changed:
                self.modified = True
            return True, old_name

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

    @staticmethod
    def signal_physical_range(sig: Signal) -> tuple[float, float]:
        """按 value_type/length/factor/offset 计算物理可表示范围。"""
        if sig.factor == 0:
            return sig.offset, sig.offset

        if sig.value_type == SignalValueType.UINT:
            raw_min, raw_max = 0, (1 << sig.length) - 1
        elif sig.value_type == SignalValueType.INT:
            raw_min = -(1 << (sig.length - 1))
            raw_max = (1 << (sig.length - 1)) - 1
        elif sig.value_type == SignalValueType.FLOAT:
            raw_min, raw_max = -_FLT_MAX, _FLT_MAX
        else:
            raw_min, raw_max = -sys.float_info.max, sys.float_info.max

        a = _as_float(raw_min) * sig.factor + sig.offset
        b = _as_float(raw_max) * sig.factor + sig.offset
        lo, hi = min(a, b), max(a, b)
        return max(lo, -sys.float_info.max), min(hi, sys.float_info.max)

    def validate_signal(
        self, msg: Message, sig: Signal, exclude_name: str | None = None
    ) -> tuple[bool, str, dict]:
        """验证信号是否可以加入/更新到报文中。返回 (is_valid, error_message, details)。"""
        if sig.start_bit < 0:
            return False, "Start bit must be non-negative", {
                "error_code": "start_bit_invalid", "type": "invalid_param",
                "field": "start_bit", "value": sig.start_bit,
            }
        if sig.length < 1:
            return False, "Signal length must be at least 1", {
                "error_code": "signal_length_invalid", "type": "invalid_param",
                "field": "length", "value": sig.length,
            }
        if sig.value_type == SignalValueType.FLOAT and sig.length != 32:
            return False, "Float signal requires length 32", {
                "error_code": "signal_value_type_length_invalid", "type": "invalid_param",
                "field": "length", "value": sig.length,
            }
        if sig.value_type == SignalValueType.DOUBLE and sig.length != 64:
            return False, "Double signal requires length 64", {
                "error_code": "signal_value_type_length_invalid", "type": "invalid_param",
                "field": "length", "value": sig.length,
            }
        if sig.min_val == 0 and sig.max_val == 0:
            return True, "", {"type": "ok"}
        if sig.factor != 0:
            if not all(math.isfinite(v) for v in (
                sig.factor, sig.offset, sig.min_val, sig.max_val
            )):
                return False, "Signal min/max values must be finite", {
                    "error_code": "signal_min_max_invalid", "type": "invalid_param",
                    "field": "min_val", "min_val": sig.min_val, "max_val": sig.max_val,
                }
            if sig.min_val > sig.max_val:
                return False, "Signal min value must not exceed max value", {
                    "error_code": "signal_min_max_invalid", "type": "invalid_param",
                    "field": "max_val", "min_val": sig.min_val, "max_val": sig.max_val,
                }
            p_min, p_max = self.signal_physical_range(sig)
            if sig.min_val < p_min:
                return False, f"Signal min value {sig.min_val} is below {p_min}", {
                    "error_code": "signal_min_out_of_range", "type": "invalid_param",
                    "field": "min_val", "value": sig.min_val,
                    "min_allowed": p_min, "max_allowed": p_max,
                    "value_type": str(sig.value_type), "length": sig.length,
                }
            if sig.max_val > p_max:
                return False, f"Signal max value {sig.max_val} is above {p_max}", {
                    "error_code": "signal_max_out_of_range", "type": "invalid_param",
                    "field": "max_val", "value": sig.max_val,
                    "min_allowed": p_min, "max_allowed": p_max,
                    "value_type": str(sig.value_type), "length": sig.length,
                }
        # A3/A4 已延后：越界和重叠由 validate_all_signals() 非阻断检测
        return True, "", {"type": "ok"}

    def validate_all_signals(self, msg_key: str) -> list[dict]:
        """验证报文中所有信号，返回全部错误列表（越界 + 重叠）。"""
        msg = self.messages.get(msg_key)
        if not msg:
            return []
        errors: list[dict] = []
        max_bits = msg.dlc * 8
        sig_list = list(msg.signals.values())
        n = len(sig_list)
        for i in range(n):
            sig = sig_list[i]
            occupied = self._get_signal_bits(sig.start_bit, sig.length, sig.byte_order)
            oob = [b for b in occupied if b < 0 or b >= max_bits]
            if oob:
                errors.append({
                    "type": "out_of_bounds",
                    "signal_name": sig.name,
                    "start_bit": sig.start_bit,
                    "length": sig.length,
                    "out_of_bounds_bits": sorted(oob)[:10],
                    "suggestion": None,
                })
            for j in range(i + 1, n):
                other = sig_list[j]
                other_bits = self._get_signal_bits(other.start_bit, other.length, other.byte_order)
                overlap = occupied & other_bits
                if overlap:
                    errors.append({
                        "type": "overlap",
                        "signal_name": sig.name,
                        "conflicts_name": other.name,
                        "overlapping_bits": sorted(overlap),
                        "suggestion": None,
                    })
        return errors

    def _validate_single_message_integrity(self, msg_key: str) -> list[dict]:
        """验证单个报文的全部完整性错误。必须在 __lock 持有下调用。"""
        msg = self.messages.get(msg_key)
        if not msg:
            return []
        errors: list[dict] = []
        msg_ref = {
            "msg_key": msg_key,
            "msg_id": msg.can_id,
            "msg_id_hex": f"0x{msg.can_id:X}",
            "is_extended_frame": msg.is_extended_frame,
        }

        # ── 报文级 ──
        if not msg.name or not msg.name.strip():
            errors.append({
                "type": "message_name_empty",
                **msg_ref,
                "message": f"Message {msg_ref['msg_id_hex']} name is empty",
            })

        try:
            validate_id(msg.can_id, msg.is_extended_frame)
        except CanIdError as e:
            errors.append({
                "type": "message_id_out_of_range",
                **msg_ref,
                "message": str(e),
            })

        # ── CAN FD 兼容性 ──
        if msg.is_fd and self.bus_type == "CAN":
            errors.append({
                "type": "canfd_in_can_bus",
                **msg_ref,
                "message": f"Message {msg_ref['msg_id_hex']} is marked as CAN FD but bus type is CAN",
            })

        # ── 信号位布局 ──
        sig_errors = self.validate_all_signals(msg_key)
        for err in sig_errors:
            err.update(msg_ref)
            if err["type"] == "out_of_bounds":
                err["max_bit"] = msg.dlc * 8 - 1
        errors.extend(sig_errors)

        # ── 信号字段级 ──
        seen_names: set[str] = set()
        for sig in msg.signals.values():
            if sig.factor == 0:
                errors.append({
                    "type": "factor_zero",
                    **msg_ref,
                    "signal_name": sig.name,
                    "message": f"Signal '{sig.name}' factor is 0",
                })
            if sig.value_type == SignalValueType.FLOAT and sig.length != 32:
                errors.append({
                    "type": "signal_value_type_length_invalid",
                    **msg_ref,
                    "signal_name": sig.name,
                    "value_type": str(sig.value_type),
                    "length": sig.length,
                    "message": (
                        f"Signal '{sig.name}' is float but length is {sig.length}; "
                        "float requires 32 bits"
                    ),
                })
            elif sig.value_type == SignalValueType.DOUBLE and sig.length != 64:
                errors.append({
                    "type": "signal_value_type_length_invalid",
                    **msg_ref,
                    "signal_name": sig.name,
                    "value_type": str(sig.value_type),
                    "length": sig.length,
                    "message": (
                        f"Signal '{sig.name}' is double but length is {sig.length}; "
                        "double requires 64 bits"
                    ),
                })
            if not sig.name or not sig.name.strip():
                errors.append({
                    "type": "signal_name_empty",
                    **msg_ref,
                    "signal_name": "(empty)",
                    "message": f"Signal in message {msg_ref['msg_id_hex']} has empty name",
                })
            else:
                if sig.name in seen_names:
                    errors.append({
                        "type": "signal_name_duplicate",
                        **msg_ref,
                        "signal_name": sig.name,
                        "message": (
                            f"Signal name '{sig.name}' duplicated in message "
                            f"{msg_ref['msg_id_hex']}"
                        ),
                    })
                seen_names.add(sig.name)
            if sig.length < 1:
                errors.append({
                    "type": "signal_length_zero",
                    **msg_ref,
                    "signal_name": sig.name,
                    "message": f"Signal '{sig.name}' length must be ≥ 1",
                })
        return errors

    def validate_data_integrity(self, affected_msg_keys: set[str]) -> list[dict]:
        """增量数据完整性校验。仅重验 affected_msg_keys 中的报文，其余读缓存。

        必须在 __lock 持有下调用。调用方通过 push_data_errors() 间接调用。
        若 affected_msg_keys 含不存在的 key → 自动回退 full_validate()。
        """
        if not affected_msg_keys.issubset(self.messages.keys()):
            return self.full_validate()

        for msg_key in affected_msg_keys:
            self._validation_cache[msg_key] = self._validate_single_message_integrity(msg_key)

        errors: list[dict] = []
        for msg_key in self.sorted_keys():
            errors.extend(self._validation_cache.get(msg_key, []))
        return errors

    def full_validate(self) -> list[dict]:
        """全量数据完整性校验。扫描所有报文并重建缓存。

        必须在 __lock 持有下调用。
        """
        self._validation_cache.clear()
        all_errors: list[dict] = []
        for msg_key in self.sorted_keys():
            msg_errors = self._validate_single_message_integrity(msg_key)
            self._validation_cache[msg_key] = msg_errors
            all_errors.extend(msg_errors)
        return all_errors

    def validate_for_dbc_export(self) -> list[dict]:
        """DBC 导出前校验。返回阻断性错误列表，空列表表示可导出。"""
        return self.full_validate()

    # ── 序列化 ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（API 响应使用）。"""
        with self.__lock:
            return {
                "name": self.name,
                "bus_type": self.bus_type,
                "value_tables": {k: dict(v) for k, v in self.value_tables.items()},
                "messages": {
                    m.key: m.to_dict() for m in sorted(
                        self.messages.values(), key=lambda m: m.sort_key
                    )
                },
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """从字典创建。兼容旧 ``messages.0x100`` 键。"""
        db = cls(name=data.get("name", "Untitled"))
        bt = data.get("bus_type", "CAN")
        if bt in ("CAN", "CAN FD"):
            db.bus_type = bt
        for mid_str, mdata in data.get("messages", {}).items():
            if not isinstance(mdata, dict):
                continue
            payload = dict(mdata)
            if not payload.get("key"):
                try:
                    can_id, is_extended = parse_ref(mid_str)
                    payload["key"] = to_key(can_id, is_extended)
                except (CanIdError, ValueError):
                    logger.warning(
                        "Skipping message with invalid key in from_dict: %s", mid_str
                    )
                    continue
            try:
                msg = Message.from_dict(payload)
            except (CanIdError, ValueError, TypeError) as e:
                logger.warning("Skipping invalid message in from_dict: %s", e)
                continue
            db.messages[msg.key] = msg
        db.value_tables = {str(k): {str(ek): str(ev) for ek, ev in v.items()}
                           for k, v in data.get("value_tables", {}).items()}
        return db

    def to_properties_str(self) -> str:
        """序列化为 Java Properties 字符串（O(n) 线性性能）。"""
        import json as _json
        import javaproperties

        with self.__lock:
            props: dict[str, str] = {}
            props["database.name"] = self.name
            if self.bus_type != "CAN":
                props["database.bus_type"] = self.bus_type

            for msg_key in self.sorted_keys():
                msg = self.messages[msg_key]
                mp = f"messages.{msg_key}"

                props[f"{mp}.name"] = msg.name
                props[f"{mp}.dlc"] = str(msg.dlc)
                props[f"{mp}.cycle_time"] = str(msg.cycle_time)
                if msg.sender:
                    props[f"{mp}.sender"] = msg.sender
                if msg.comment:
                    props[f"{mp}.comment"] = msg.comment
                if msg.is_fd:
                    props[f"{mp}.is_fd"] = "true"

                if msg.signals:
                    seen: set[str] = set()
                    sorted_sigs = sorted(msg.signals.values(), key=lambda s: s.start_bit)
                    for sig in sorted_sigs:
                        sig_key = _make_signal_key(sig, seen)
                        sp = f"{mp}.signals.{sig_key}"

                        props[f"{sp}.name"] = sig.name
                        props[f"{sp}.start_bit"] = str(sig.start_bit)
                        props[f"{sp}.length"] = str(sig.length)
                        props[f"{sp}.byte_order"] = sig.byte_order

                        # value_type 是信号语义的一部分，始终写出，避免旧文件/稀疏输出导致类型歧义
                        props[f"{sp}.value_type"] = str(sig.value_type)
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
                        if sig.value_table_name:
                            props[f"{sp}.value_table_name"] = sig.value_table_name

            for vt_name in sorted(self.value_tables):
                props[f"value_tables.{vt_name}"] = _json.dumps(
                    self.value_tables[vt_name], ensure_ascii=False)

            return javaproperties.dumps(
                props,
                comments="CanDbCodeGenerator - CAN Database Definition",
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
        bt = props.get("database.bus_type", "CAN")
        if bt in ("CAN", "CAN FD"):
            db.bus_type = bt

        messages_data: dict[str, dict] = {}

        for key, value in props.items():
            if key.startswith("value_tables."):
                vt_name = key[len("value_tables."):]
                try:
                    db.value_tables[vt_name] = _json.loads(value)
                except (ValueError, TypeError):
                    db.value_tables[vt_name] = {}
                continue
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
                can_id, is_extended = parse_ref(mid_key)
            except (CanIdError, ValueError):
                logger.warning(
                    "Skipping message with invalid key in from_properties_str: %s", mid_key
                )
                continue

            msg = Message(
                can_id=can_id,
                is_extended_frame=is_extended,
                name=msg_d.get("name", ""),
                dlc=int(msg_d.get("dlc", 8)),
                cycle_time=int(msg_d.get("cycle_time", 0)),
                sender=msg_d.get("sender", ""),
                comment=msg_d.get("comment", ""),
                is_fd=msg_d.get("is_fd", "").lower() in ("true", "1", "yes"),
            )

            for _sig_key, sig_d in msg_d.get("signals", {}).items():
                receivers_raw = sig_d.get("receivers", "")
                if receivers_raw:
                    try:
                        receivers = _json.loads(receivers_raw)
                    except (ValueError, TypeError) as e:
                        logger.debug("Failed to parse receivers for signal %s: %s", _sig_key, e)
                        receivers = []
                else:
                    receivers = []

                sig = Signal.from_dict({
                    "name": sig_d.get("name", ""),
                    "start_bit": int(sig_d.get("start_bit", 0)),
                    "length": int(sig_d.get("length", 8)),
                    "byte_order": sig_d.get("byte_order", "motorola"),
                    "value_type": sig_d.get("value_type", SignalValueType.UINT.value),
                    "factor": float(sig_d.get("factor", 1.0)),
                    "offset": float(sig_d.get("offset", 0.0)),
                    "min_val": float(sig_d.get("min_val", 0.0)),
                    "max_val": float(sig_d.get("max_val", 0.0)),
                    "unit": sig_d.get("unit", ""),
                    "comment": sig_d.get("comment", ""),
                    "receivers": receivers,
                    "multiplexer_mode": sig_d.get("multiplexer_mode", "none"),
                    "multiplexer_value": int(sig_d.get("multiplexer_value", 0)),
                    "value_table_name": sig_d.get("value_table_name", ""),
                })
                msg.signals[sig.name] = sig

            db.messages[msg.key] = msg
        return db

    # ── DBC 序列化 ─────────────────────────────────────────────────────

    def to_dbc_str(self) -> str:
        """导出为 DBC 格式字符串（使用 cantools 库）。"""
        import cantools.database
        from cantools.database.conversion import BaseConversion
        from collections import OrderedDict
        from cantools.database.can.formats.dbc import (
            ATTRIBUTE_DEFINITION_VFRAMEFORMAT,
            ATTRIBUTE_DEFINITION_BUS_TYPE,
        )
        from cantools.database.can.formats.dbc_specifics import DbcSpecifics
        from cantools.database.can.attribute import Attribute
        from copy import copy

        from app.io.dbc_attributes import drop_attribute_definitions
        
        with self.__lock:
            can_db = cantools.database.Database()
            # 注册 VFrameFormat + BusType 属性定义
            vff = copy(ATTRIBUTE_DEFINITION_VFRAMEFORMAT)
            vff.default_value = 'reserved'
            # 使用用户显式配置的 bus_type，不做自动推断
            ct_value_tables = {}
            for vt_name, vt_entries in self.value_tables.items():
                converted = {}
                for k, v in vt_entries.items():
                    try:
                        converted[int(k)] = str(v)
                    except (ValueError, TypeError):
                        logger.warning("Value table '%s': skipping non-numeric key '%s'", vt_name, k)
                ct_value_tables[vt_name] = converted
            can_db._dbc = DbcSpecifics(
                attribute_definitions={
                    'VFrameFormat': vff,
                    'BusType': ATTRIBUTE_DEFINITION_BUS_TYPE,
                },
                attributes={
                    'BusType': Attribute(
                        definition=ATTRIBUTE_DEFINITION_BUS_TYPE,
                        value=self.bus_type,
                    ),
                },
                value_tables=ct_value_tables,
            )
            
            for msg in sorted(self.messages.values(), key=lambda m: m.sort_key):
                can_signals = []
                
                for sig in msg.signals.values():
                    if sig.value_type == SignalValueType.FLOAT and sig.length != 32:
                        raise ValueError(
                            f"Signal '{msg.name}.{sig.name}' is float but length is "
                            f"{sig.length}; float requires 32 bits"
                        )
                    if sig.value_type == SignalValueType.DOUBLE and sig.length != 64:
                        raise ValueError(
                            f"Signal '{msg.name}.{sig.name}' is double but length is "
                            f"{sig.length}; double requires 64 bits"
                        )
                    choices = None
                    if sig.value_table_name and sig.value_table_name in self.value_tables:
                        vt = self.value_tables[sig.value_table_name]
                        choices = OrderedDict()
                        for k, v in vt.items():
                            try:
                                choices[int(k)] = str(v)
                            except (ValueError, TypeError):
                                logger.warning("Signal '%s' value table: skipping non-numeric key '%s'", sig.name, k)
                    conversion = BaseConversion.factory(
                        scale=sig.factor, offset=sig.offset,
                        choices=choices, is_float=sig.is_float,
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
                    frame_id=msg.can_id,
                    name=msg.name,
                    length=msg.dlc,
                    signals=can_signals,
                    comment=msg.comment if msg.comment else None,
                    senders=[sender] if (sender := msg.sender) else [],
                    cycle_time=msg.cycle_time if msg.cycle_time > 0 else None,
                    is_fd=msg.is_fd,
                    is_extended_frame=msg.is_extended_frame,
                )
                can_db.messages.append(can_msg)
            
            content = can_db.as_dbc_string()
            # cantools 会在 CAN FD 总线上自动附加 CANFD_BRS 定义；本工具不采用该属性
            return drop_attribute_definitions(content, {"CANFD_BRS"})

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

        from app.io.dbc_attributes import (
            collect_import_warnings,
            collect_source_warnings,
            is_extended_frame,
            summarize_import_warnings,
        )

        can_db = cantools.database.load_string(content, database_format='dbc')
        db = cls(name="Imported from DBC")

        # 先提取全局值描述表 (VAL_TABLE_)，确保信号级 VAL_ 去重时能匹配
        dbc_specs = getattr(can_db, 'dbc', None) or getattr(can_db, '_dbc', None)
        if dbc_specs and getattr(dbc_specs, 'value_tables', None):
            for vt_name, vt_choices in dbc_specs.value_tables.items():
                db.value_tables[str(vt_name)] = {
                    str(k): str(v) for k, v in vt_choices.items()
                }

        # BusType：仅当 DBC 中存在显式 BA_ 时才采用；缺失时由调用方按 FD 报文推断
        import re as _re
        has_explicit_bus_type = _re.search(
            r'(?m)^\s*BA_\s+"BusType"\s+', content
        ) is not None
        explicit_bus_type = None
        if has_explicit_bus_type and dbc_specs is not None:
            attrs = getattr(dbc_specs, "attributes", None) or {}
            bus_attr = attrs.get("BusType")
            if bus_attr is not None:
                raw = str(getattr(bus_attr, "value", bus_attr)).strip()
                if raw in ("CAN", "CAN FD"):
                    explicit_bus_type = raw
                elif raw.upper().replace("_", "").replace("-", "").replace(" ", "") == "CANFD":
                    explicit_bus_type = "CAN FD"

        any_fd = False
        skipped_messages: list[str] = []
        for can_msg in can_db.messages:
            cycle_time = 0
            try:
                if can_msg.cycle_time is not None:
                    cycle_time = int(can_msg.cycle_time)
            except Exception as e:
                logger.debug("Failed to extract cycle_time from DBC message %s: %s", can_msg.name, e)
                pass
            sender = ""
            try:
                senders = getattr(can_msg, "senders", None)
                if senders and isinstance(senders, list) and len(senders) > 0:
                    sender = str(senders[0])
            except Exception as e:
                logger.debug("Failed to extract sender from DBC message %s: %s", can_msg.name, e)
                pass

            can_id = int(can_msg.frame_id)
            is_extended = is_extended_frame(can_msg)
            try:
                validate_id(can_id, is_extended)
            except CanIdError as e:
                logger.warning("Skipping DBC message %s: %s", can_msg.name, e)
                skipped_messages.append(f"{can_msg.name}: {e}")
                continue

            msg = Message(
                can_id=can_id,
                is_extended_frame=is_extended,
                name=can_msg.name,
                dlc=can_msg.length,
                cycle_time=cycle_time,
                comment=str(can_msg.comment) if can_msg.comment else "",
                sender=sender,
                is_fd=getattr(can_msg, 'is_fd', False),
            )
            any_fd = any_fd or msg.is_fd

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

                # 浮点信号只在长度 32/64 时有效；否则降级为整数并报告
                is_float = bool(getattr(can_sig, "is_float", False))
                if is_float and can_sig.length == 32:
                    value_type = SignalValueType.FLOAT
                elif is_float and can_sig.length == 64:
                    value_type = SignalValueType.DOUBLE
                else:
                    value_type = (
                        SignalValueType.INT if can_sig.is_signed
                        else SignalValueType.UINT
                    )

                # 提升信号内联 VAL_ choices 到全局值描述表
                sig_vt_name = ""
                if getattr(can_sig, 'choices', None):
                    choices_dict = {str(k): str(v) for k, v in can_sig.choices.items()}
                    auto_name = f"{can_sig.name}_Values"
                    existing_name = None
                    for en, ev in db.value_tables.items():
                        if ev == choices_dict:
                            existing_name = en
                            break
                    if existing_name:
                        sig_vt_name = existing_name
                    elif auto_name not in db.value_tables:
                        db.value_tables[auto_name] = choices_dict
                        sig_vt_name = auto_name
                    else:
                        counter = 2
                        while f"{auto_name}_{counter}" in db.value_tables:
                            counter += 1
                        auto_name = f"{auto_name}_{counter}"
                        db.value_tables[auto_name] = choices_dict
                        sig_vt_name = auto_name

                sig = Signal.from_dict({
                    "name": can_sig.name,
                    "start_bit": can_sig.start,
                    "length": can_sig.length,
                    "byte_order": order_str,
                    "value_type": value_type.value,
                    "factor": float(can_sig.scale) if hasattr(can_sig, 'scale') else 1.0,
                    "offset": float(can_sig.offset) if hasattr(can_sig, 'offset') else 0.0,
                    "min_val": can_sig.minimum if can_sig.minimum is not None else 0.0,
                    "max_val": can_sig.maximum if can_sig.maximum is not None else 0.0,
                    "unit": str(can_sig.unit) if can_sig.unit else "",
                    "comment": str(can_sig.comment) if can_sig.comment else "",
                    "receivers": list(can_sig.receivers) if can_sig.receivers else [],
                    "multiplexer_mode": mux_mode,
                    "multiplexer_value": mux_value,
                    "value_table_name": sig_vt_name,
                })
                msg.signals[sig.name] = sig

            db.messages[msg.key] = msg

        if explicit_bus_type is not None:
            db.bus_type = explicit_bus_type
        elif any_fd:
            db.bus_type = "CAN FD"

        warnings = collect_import_warnings(can_db, content)
        warnings.extend(collect_source_warnings(content))
        if skipped_messages:
            warnings.append({
                "code": "message_skipped",
                "level": "BO",
                "level_label": "报文",
                "name": "BO_",
                "count": len(skipped_messages),
                "examples": skipped_messages[:5],
            })
        if explicit_bus_type is None and any_fd:
            warnings.append({
                "code": "bus_type_inferred",
                "level": "DB",
                "level_label": "数据库",
                "name": "BusType",
                "count": 1,
                "examples": ["未找到 BusType，按 CAN FD 报文推断为 CAN FD"],
            })
        warnings.sort(key=lambda w: (w["code"], w["level"], w["name"]))
        db.import_warnings = warnings
        if warnings:
            logger.warning(
                "DBC import dropped or adjusted attributes: %s",
                summarize_import_warnings(warnings),
            )

        return db
