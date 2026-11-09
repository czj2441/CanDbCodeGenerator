"""Message dataclass — CAN 报文定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .can_id import parse_key, parse_ref, to_key
from .signal import Signal


@dataclass
class Message:
    """一个 CAN 报文及其信号定义。

    报文身份由 ``key`` 表示（``0x100:std`` / ``0x100:ext``），
    ``can_id`` 只保存原始 CAN ID，不再承担字典键职责。
    """

    can_id: int = 0
    name: str = ""
    dlc: int = 8
    cycle_time: int = 0  # ms, 0 = event-triggered
    comment: str = ""
    sender: str = ""
    is_fd: bool = False  # True = CAN FD, False = Classic CAN
    is_extended_frame: bool = False
    signals: dict[str, Signal] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """报文唯一身份 key。"""
        return to_key(self.can_id, self.is_extended_frame)

    @property
    def sort_key(self) -> tuple[int, bool]:
        """稳定排序键：先按 CAN ID，再按标准/扩展。"""
        return (self.can_id, self.is_extended_frame)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。信号按 start_bit 升序输出为 dict。"""
        sorted_sigs = sorted(self.signals.values(), key=lambda s: s.start_bit)
        return {
            "key": self.key,
            "id": self.can_id,
            "is_extended_frame": self.is_extended_frame,
            "name": self.name,
            "dlc": self.dlc,
            "cycle_time": self.cycle_time,
            "comment": self.comment,
            "sender": self.sender,
            "is_fd": self.is_fd,
            "signals": {sig.name: sig.to_dict() for sig in sorted_sigs},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """从字典创建。

        反序列化优先使用 ``key``；没有时使用 ``id`` + ``is_extended_frame``；
        两者都没有时按旧整数规则解析。
        """
        raw_signals = data.get("signals", {})
        signals: dict[str, Signal] = {}
        for _key, sig_data in raw_signals.items():
            sig = Signal.from_dict(sig_data)
            signals[sig.name] = sig

        key = data.get("key")
        if key:
            can_id, is_extended = parse_key(str(key))
        elif "is_extended_frame" in data:
            raw_id = data.get("id", 0)
            can_id = int(raw_id, 0) if isinstance(raw_id, str) else int(raw_id)
            is_extended = bool(data.get("is_extended_frame", False))
            # 显式标志优先，但仍做范围校验
            from .can_id import validate_id

            validate_id(can_id, is_extended)
        else:
            can_id, is_extended = parse_ref(data.get("id", 0))

        return cls(
            can_id=can_id,
            name=str(data.get("name", "")),
            dlc=int(data.get("dlc", 8)),
            cycle_time=int(data.get("cycle_time", 0)),
            comment=str(data.get("comment", "")),
            sender=str(data.get("sender", "")),
            is_fd=bool(data.get("is_fd", False)),
            is_extended_frame=is_extended,
            signals=signals,
        )