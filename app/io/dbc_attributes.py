"""DBC 属性白名单与导入提示收集。

本模块是 DBC 属性策略的单一事实来源：

- ``ADOPTED_ATTRIBUTES``：进入内部模型，可持久化、可导出
- ``DERIVED_ATTRIBUTES``：不直接存储，但由模型字段完整表达
- ``SILENT_ATTRIBUTES``：按既定语义接受，但不单独存储、不告警
- 其余属性：导入时报告，导出时不输出

同时负责检测 cantools 不建模的结构记录（SIG_GROUP_、EV_ 等）。
"""

from __future__ import annotations

import re
from typing import Any

# (level, attribute_name)
ADOPTED_ATTRIBUTES: frozenset[tuple[str, str]] = frozenset({
    ("DB", "BusType"),
    ("BO", "GenMsgCycleTime"),
})

# 由 is_fd / is_extended_frame / BusType 派生，导出时由 cantools 重新生成
DERIVED_ATTRIBUTES: frozenset[tuple[str, str]] = frozenset({
    ("BO", "VFrameFormat"),
})

# 按既定语义接受，不存储、不告警
SILENT_ATTRIBUTES: frozenset[tuple[str, str]] = frozenset({
    # cantools 直接把它作为信号名使用
    ("SG", "SystemSignalLongSymbol"),
})

_LEVEL_LABELS = {
    "DB": "数据库",
    "BO": "报文",
    "SG": "信号",
    "BU": "节点",
    "STRUCT": "结构",
    "EV": "环境变量",
}

_EXAMPLE_LIMIT = 5


def is_known_attribute(level: str, name: str) -> bool:
    """属性是否已被采用、派生或静默接受。"""
    key = (level, name)
    return (
        key in ADOPTED_ATTRIBUTES
        or key in DERIVED_ATTRIBUTES
        or key in SILENT_ATTRIBUTES
    )


def _attribute_value(attr: Any) -> Any:
    return getattr(attr, "value", attr)


def _add(
    buckets: dict[tuple[str, str, str], dict],
    code: str,
    level: str,
    name: str,
    example: str,
) -> None:
    key = (code, level, name)
    entry = buckets.get(key)
    if entry is None:
        buckets[key] = {
            "code": code,
            "level": level,
            "level_label": _LEVEL_LABELS.get(level, level),
            "name": name,
            "count": 1,
            "examples": [example],
        }
        return
    entry["count"] += 1
    if example and len(entry["examples"]) < _EXAMPLE_LIMIT:
        entry["examples"].append(example)


def _collect_attribute_map(
    buckets: dict[tuple[str, str, str], dict],
    attrs: Any,
    level: str,
    target: str,
) -> None:
    if not attrs:
        return
    for name in attrs:
        if is_known_attribute(level, name):
            continue
        _add(buckets, "unsupported_attribute", level, str(name), target)


def _vframe_format_name(can_msg: Any) -> str | None:
    """读取 VFrameFormat 的枚举名，兼容索引值。"""
    dbc = getattr(can_msg, "dbc", None)
    attributes = getattr(dbc, "attributes", None) or {}
    attr = attributes.get("VFrameFormat")
    if attr is None:
        return None
    value = _attribute_value(attr)
    definitions = getattr(dbc, "attribute_definitions", None) or {}
    definition = definitions.get("VFrameFormat")
    choices = getattr(definition, "choices", None) or []
    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value < len(choices):
            return str(choices[value])
        return None
    return str(value)


def is_extended_frame(can_msg: Any) -> bool:
    """判断 DBC 报文是否为扩展帧。

    cantools 的 ``is_extended_frame`` 只认 ID 的 bit31；部分工具只写
    ``VFrameFormat=ExtendedCAN``，因此需要同时检查枚举名。
    """
    if bool(getattr(can_msg, "is_extended_frame", False)):
        return True
    return _vframe_format_name(can_msg) in ("ExtendedCAN", "ExtendedCAN_FD")


_STRUCTURE_TOKENS: tuple[str, ...] = (
    "SIG_GROUP_",
    "SGTYPE_VAL_",
    "SGTYPE_",
    "BA_DEF_SGTYPE_",
    "BA_SGTYPE_",
    "SIG_TYPE_REF_",
    "ENVVAR_DATA_",
    "EV_",
    "BA_DEF_DEF_REL_",
    "BA_DEF_REL_",
    "BA_REL_",
    "BU_SG_REL_",
    "BU_EV_REL_",
    "BU_BO_REL_",
)

_NODE_COMMENT_RE = re.compile(r"(?m)^\s*CM_\s+BU_\s+(\S+)")
_BO_LINE_RE = re.compile(r"(?m)^\s*BO_\s+(\d+)\s+([^:\r\n]+?)\s*:")


def _collect_structure(
    buckets: dict[tuple[str, str, str], dict], content: str
) -> None:
    """按行检测结构记录，跳过 NS_ 里的纯 token 声明。"""
    counts: dict[str, list[str]] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for record in _STRUCTURE_TOKENS:
            if not stripped.startswith(record):
                continue
            rest = stripped[len(record):]
            if not rest.strip():
                # NS_ 命名空间声明，例如 "\tSIG_GROUP_"
                break
            if rest[0] not in (" ", "\t", ";"):
                continue
            counts.setdefault(record, []).append(stripped[:120])
            break

    for record, examples in counts.items():
        _add(buckets, "unsupported_record", "STRUCT", record, examples[0])
        entry = buckets[("unsupported_record", "STRUCT", record)]
        entry["count"] = len(examples)
        entry["examples"] = examples[:_EXAMPLE_LIMIT]

    node_matches = _NODE_COMMENT_RE.findall(content)
    if node_matches:
        _add(buckets, "unsupported_record", "BU", "CM_ BU_", node_matches[0])
        entry = buckets[("unsupported_record", "BU", "CM_ BU_")]
        entry["count"] = len(node_matches)
        entry["examples"] = node_matches[:_EXAMPLE_LIMIT]


def collect_import_warnings(can_db: Any, content: str) -> list[dict]:
    """收集 DBC 中未被内部模型保留的属性与结构记录。

    Returns:
        按 ``(code, level, name)`` 聚合的提示列表；无提示时返回空列表。
    """
    buckets: dict[tuple[str, str, str], dict] = {}

    # DB 级属性
    dbc = getattr(can_db, "dbc", None)
    _collect_attribute_map(
        buckets, getattr(dbc, "attributes", None), "DB", "database"
    )

    # 报文 / 信号级属性、多发送方、扩展复用、非法浮点长度
    for can_msg in getattr(can_db, "messages", []):
        msg_name = str(getattr(can_msg, "name", ""))
        _collect_attribute_map(
            buckets, getattr(getattr(can_msg, "dbc", None), "attributes", None),
            "BO", msg_name,
        )
        if len(getattr(can_msg, "senders", None) or []) > 1:
            _add(
                buckets, "multiple_senders", "BO", "BO_TX_BU_",
                f"{msg_name}: {', '.join(can_msg.senders)}",
            )
        for can_sig in getattr(can_msg, "signals", []):
            sig_name = f"{msg_name}.{getattr(can_sig, 'name', '')}"
            _collect_attribute_map(
                buckets, getattr(getattr(can_sig, "dbc", None), "attributes", None),
                "SG", sig_name,
            )
            mux_ids = getattr(can_sig, "multiplexer_ids", None) or []
            if len(mux_ids) > 1:
                _add(buckets, "extended_multiplexing", "SG", "SG_MUL_VAL_", sig_name)
            if bool(getattr(can_sig, "is_float", False)) and int(
                getattr(can_sig, "length", 0)
            ) not in (32, 64):
                _add(buckets, "invalid_float_length", "SG", "SIG_VALTYPE_", sig_name)

    # 节点属性
    for node in getattr(can_db, "nodes", []):
        _collect_attribute_map(
            buckets, getattr(getattr(node, "dbc", None), "attributes", None),
            "BU", str(getattr(node, "name", "")),
        )

    # 结构记录
    _collect_structure(buckets, content)

    return sorted(
        buckets.values(),
        key=lambda w: (w["code"], w["level"], w["name"]),
    )


def collect_source_warnings(content: str) -> list[dict]:
    """检测解析前就会互相覆盖的重复报文声明。

    cantools 在加载阶段遇到相同报文 ID 时会用后者覆盖前者，并只在日志里
    提示；这里直接从原始 ``BO_`` 行提取，确保用户能在导入提示中看到。
    """
    seen: dict[str, str] = {}
    duplicate_count = 0
    examples: list[str] = []

    for match in _BO_LINE_RE.finditer(content):
        raw_id = int(match.group(1))
        name = match.group(2).strip()
        is_extended = bool(raw_id & 0x80000000)
        can_id = raw_id & 0x1FFFFFFF
        key = f"0x{can_id:X}:{'ext' if is_extended else 'std'}"
        first_name = seen.get(key)
        if first_name is None:
            seen[key] = name
            continue
        duplicate_count += 1
        if len(examples) < _EXAMPLE_LIMIT:
            examples.append(f"{first_name} / {name} ({key})")

    if duplicate_count == 0:
        return []
    return [{
        "code": "message_duplicate",
        "level": "BO",
        "level_label": _LEVEL_LABELS["BO"],
        "name": "BO_",
        "count": duplicate_count,
        "examples": examples,
    }]


def drop_attribute_definitions(content: str, names: set[str]) -> str:
    """删除指定属性的 BA_DEF_ / BA_DEF_DEF_ 行（用于 cantools 自动附加的定义）。"""
    if not names:
        return content
    kept: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        removed = False
        for name in names:
            pattern = re.compile(
                r'^BA_DEF(?:_DEF)?_\s+(?:(?:BO_|SG_|BU_|EV_)\s+)?"'
                + re.escape(name) + r'"\s'
            )
            if pattern.match(stripped):
                removed = True
                break
        if not removed:
            kept.append(line)
    return "".join(kept)


def summarize_import_warnings(warnings: list[dict]) -> str:
    """生成一行日志摘要。"""
    if not warnings:
        return ""
    parts = [
        f"{w['name']}×{w['count']}" for w in warnings
    ]
    return "; ".join(parts)


# 导出时必须满足的白名单（供测试断言）
EXPORTED_ATTRIBUTE_NAMES: frozenset[str] = frozenset({
    "VFrameFormat",
    "BusType",
    "GenMsgCycleTime",
})