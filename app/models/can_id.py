"""CAN 报文 ID 与身份 key 工具。

报文身份统一使用自解释 key：

- 标准帧：``0x100:std``
- 扩展帧：``0x100:ext``

内部不再使用 bit31 编码。所有 key 的生成、解析与范围校验都集中在这里，
业务代码禁止自行拼接或解析。
"""

from __future__ import annotations

MAX_STD_ID = 0x7FF
MAX_EXT_ID = 0x1FFFFFFF

_STD_SUFFIX = "std"
_EXT_SUFFIX = "ext"


class CanIdError(ValueError):
    """CAN ID 或 key 非法。"""


def validate_id(can_id: int, is_extended: bool) -> None:
    """校验 CAN ID 是否在对应帧类型的合法范围内。

    Raises:
        CanIdError: ID 类型或范围非法
    """
    if isinstance(can_id, bool) or not isinstance(can_id, int):
        raise CanIdError(f"CAN ID must be an integer, got {type(can_id).__name__}")
    if can_id < 0:
        raise CanIdError(f"CAN ID must be non-negative, got {can_id}")
    limit = MAX_EXT_ID if is_extended else MAX_STD_ID
    if can_id > limit:
        kind = "extended" if is_extended else "standard"
        raise CanIdError(
            f"CAN ID 0x{can_id:X} out of range for {kind} frame (max 0x{limit:X})"
        )


def to_key(can_id: int, is_extended: bool) -> str:
    """生成报文的唯一身份 key。"""
    validate_id(can_id, is_extended)
    suffix = _EXT_SUFFIX if is_extended else _STD_SUFFIX
    return f"0x{can_id:X}:{suffix}"


def parse_key(key: str) -> tuple[int, bool]:
    """解析 ``0x100:std`` / ``0x100:ext`` 形式的 key。"""
    if not isinstance(key, str):
        raise CanIdError(f"Message key must be a string, got {type(key).__name__}")
    text = key.strip()
    if ":" not in text:
        raise CanIdError(f"Message key must contain ':std' or ':ext': {key!r}")
    id_part, suffix = text.rsplit(":", 1)
    suffix = suffix.strip().lower()
    if suffix not in (_STD_SUFFIX, _EXT_SUFFIX):
        raise CanIdError(f"Invalid message key suffix: {key!r}")
    try:
        can_id = int(id_part, 0)
    except ValueError as e:
        raise CanIdError(f"Invalid CAN ID in message key: {key!r}") from e
    is_extended = suffix == _EXT_SUFFIX
    validate_id(can_id, is_extended)
    return can_id, is_extended


def parse_ref(value: int | str) -> tuple[int, bool]:
    """解析报文引用（整数或 key），返回 ``(can_id, is_extended)``。

    兼容规则：

    - ``"0x100:ext"`` → 扩展帧 0x100
    - ``"0x100"`` / ``256`` → 标准帧（旧数据只有标准帧）
    - 整数 > 0x7FF → 按扩展帧原始 ID 处理（兼容旧 MCP 调用）
    """
    if isinstance(value, bool):
        raise CanIdError("CAN ID must not be a boolean")
    if isinstance(value, int):
        if value < 0:
            raise CanIdError(f"CAN ID must be non-negative, got {value}")
        is_extended = value > MAX_STD_ID
        validate_id(value, is_extended)
        return value, is_extended
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise CanIdError("CAN ID must not be empty")
        if ":" in text:
            return parse_key(text)
        try:
            can_id = int(text, 0)
        except ValueError as e:
            raise CanIdError(f"Invalid CAN ID: {value!r}") from e
        return parse_ref(can_id)
    raise CanIdError(f"Unsupported CAN ID reference type: {type(value).__name__}")


def format_id(can_id: int) -> str:
    """格式化为显示用 ID（不含帧类型）。"""
    return f"0x{can_id:X}"