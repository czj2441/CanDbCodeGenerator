"""Signal dataclass — CAN 信号定义。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Signal:
    """单个 CAN 信号定义（per-message 实体）。"""

    uuid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    start_bit: int = 0
    length: int = 8
    byte_order: str = "motorola"  # "intel" | "motorola"
    is_signed: bool = False
    factor: float = 1.0
    offset: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    unit: str = ""
    comment: str = ""
    receivers: list[str] = field(default_factory=list)
    multiplexer_mode: str = "none"  # "none" | "multiplexer" | "multiplexed"
    multiplexer_value: int = 0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
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
            "receivers": self.receivers[:],
            "multiplexer_mode": self.multiplexer_mode,
            "multiplexer_value": self.multiplexer_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """从字典创建。"""
        return cls(
            uuid=str(data.get("uuid", uuid.uuid4().hex[:8])),
            name=str(data.get("name", "")),
            start_bit=int(data.get("start_bit", 0)),
            length=int(data.get("length", 8)),
            byte_order=str(data.get("byte_order", "motorola")),
            is_signed=bool(data.get("is_signed", False)),
            factor=float(data.get("factor", 1.0)),
            offset=float(data.get("offset", 0.0)),
            min_val=float(data.get("min_val", 0.0)),
            max_val=float(data.get("max_val", 0.0)),
            unit=str(data.get("unit", "")),
            comment=str(data.get("comment", "")),
            receivers=list(data.get("receivers", [])),
            multiplexer_mode=str(data.get("multiplexer_mode", "none")),
            multiplexer_value=int(data.get("multiplexer_value", 0)),
        )
