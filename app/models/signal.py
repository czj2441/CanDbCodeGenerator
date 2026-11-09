"""Signal dataclass — CAN 信号定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalValueType(str, Enum):
    """信号的原始值类型（DBC 语义）。

    - ``UINT``：无符号整数
    - ``INT``：有符号整数
    - ``FLOAT``：32-bit IEEE 754 单精度
    - ``DOUBLE``：64-bit IEEE 754 双精度
    """

    UINT = "uint"
    INT = "int"
    FLOAT = "float"
    DOUBLE = "double"

    def __str__(self) -> str:
        # 兼容 Python 3.9/3.10：str, Enum 默认返回 ``SignalValueType.UINT``
        return self.value


_INTEGER_TYPES = (SignalValueType.UINT, SignalValueType.INT)
_FLOAT_TYPES = (SignalValueType.FLOAT, SignalValueType.DOUBLE)


@dataclass
class Signal:
    """单个 CAN 信号定义（per-message 实体）。"""

    name: str = ""
    start_bit: int = 0
    length: int = 8
    byte_order: str = "motorola"  # "intel" | "motorola"
    value_type: SignalValueType = SignalValueType.UINT
    factor: float = 1.0
    offset: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    unit: str = ""
    comment: str = ""
    receivers: list[str] = field(default_factory=list)
    multiplexer_mode: str = "none"  # "none" | "multiplexer" | "multiplexed"
    multiplexer_value: int = 0
    value_table_name: str = ""

    @property
    def is_signed(self) -> bool:
        """是否为有符号整数（浮点类型恒为 False）。"""
        return self.value_type == SignalValueType.INT

    @property
    def is_float(self) -> bool:
        """是否为浮点类型。"""
        return self.value_type in _FLOAT_TYPES

    @property
    def float_bits(self) -> int | None:
        """浮点类型的位宽；整数类型返回 None。"""
        if self.value_type == SignalValueType.FLOAT:
            return 32
        if self.value_type == SignalValueType.DOUBLE:
            return 64
        return None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "name": self.name,
            "start_bit": self.start_bit,
            "length": self.length,
            "byte_order": self.byte_order,
            "value_type": str(self.value_type),
            "factor": self.factor,
            "offset": self.offset,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "unit": self.unit,
            "comment": self.comment,
            "receivers": self.receivers[:],
            "multiplexer_mode": self.multiplexer_mode,
            "multiplexer_value": self.multiplexer_value,
            "value_table_name": self.value_table_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """从字典创建。``value_type`` 必须是合法枚举值。"""
        raw_value_type = data.get("value_type", SignalValueType.UINT.value)
        try:
            value_type = SignalValueType(raw_value_type)
        except ValueError as e:
            valid = ", ".join(t.value for t in SignalValueType)
            raise ValueError(
                f"Invalid signal value_type {raw_value_type!r}; valid: {valid}"
            ) from e

        return cls(
            name=str(data.get("name", "")),
            start_bit=int(data.get("start_bit", 0)),
            length=int(data.get("length", 8)),
            byte_order=str(data.get("byte_order", "motorola")),
            value_type=value_type,
            factor=float(data.get("factor", 1.0)),
            offset=float(data.get("offset", 0.0)),
            min_val=float(data.get("min_val", 0.0)),
            max_val=float(data.get("max_val", 0.0)),
            unit=str(data.get("unit", "")),
            comment=str(data.get("comment", "")),
            receivers=list(data.get("receivers", [])),
            multiplexer_mode=str(data.get("multiplexer_mode", "none")),
            multiplexer_value=int(data.get("multiplexer_value", 0)),
            value_table_name=str(data.get("value_table_name", "")),
        )