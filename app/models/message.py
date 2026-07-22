"""Message dataclass — CAN 报文定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .signal import Signal


@dataclass
class Message:
    """一个 CAN 报文及其信号定义。"""

    id: int = 0
    name: str = ""
    dlc: int = 8
    cycle_time: int = 0  # ms, 0 = event-triggered
    comment: str = ""
    sender: str = ""
    is_fd: bool = False  # True = CAN FD, False = Classic CAN
    signals: list[Signal] = field(default_factory=list)

    def to_dict(self, signals_as_dict: bool = True) -> dict[str, Any]:
        """序列化为字典。"""
        d = {
            "id": self.id,
            "name": self.name,
            "dlc": self.dlc,
            "cycle_time": self.cycle_time,
            "comment": self.comment,
            "sender": self.sender,
            "is_fd": self.is_fd,
        }
        if signals_as_dict:
            d["signals"] = [sig.to_dict() for sig in self.signals]
        else:
            d["signals"] = self.signals
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """从字典创建。id 字段应为整数。"""
        return cls(
            id=int(data.get("id", 0)),
            name=str(data.get("name", "")),
            dlc=int(data.get("dlc", 8)),
            cycle_time=int(data.get("cycle_time", 0)),
            comment=str(data.get("comment", "")),
            sender=str(data.get("sender", "")),
            is_fd=bool(data.get("is_fd", False)),
            signals=[Signal.from_dict(sig_data) for sig_data in data.get("signals", [])],
        )
