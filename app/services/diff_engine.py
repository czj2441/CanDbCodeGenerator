"""
diff_engine.py — 保存差异计算引擎。

比较两个 CanDatabase 实例（磁盘版本 vs 内存版本），
输出字段级 diff 列表供前端悬浮窗展示。
"""

from typing import Any

from app.models import CanDatabase

# ── 字段白名单 ──

_DB_FIELDS = ['name', 'bus_type']

_MESSAGE_FIELDS = ['name', 'dlc', 'cycle_time', 'comment', 'sender', 'is_fd']

_SIGNAL_FIELDS = [
    'name', 'start_bit', 'length', 'byte_order', 'is_signed',
    'factor', 'offset', 'min_val', 'max_val', 'unit', 'comment',
    'receivers', 'multiplexer_mode', 'multiplexer_value', 'value_table_name',
]


def _format_value(v: Any) -> str:
    """格式化值用于前端展示。"""
    if v is None:
        return '(空)'
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return f"{v:g}"
    if isinstance(v, list):
        return ', '.join(str(i) for i in v) if v else '(空)'
    if v == '':
        return '(空)'
    return str(v)


def _values_equal(a: Any, b: Any) -> bool:
    """比较两个值是否相等，对浮点数做容差处理。"""
    if isinstance(a, float) and isinstance(b, float):
        if a == b:
            return True
        denom = max(abs(a), abs(b), 1.0)
        return abs(a - b) / denom < 1e-9
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return a == b


def _msg_key_sort(key: str) -> int:
    """报文 key 按 ID 数值排序。"""
    return int(key, 16) if key.startswith("0x") else int(key)


def compute_save_diff(disk_db: CanDatabase, mem_db: CanDatabase) -> list[dict]:
    """计算磁盘版本与内存版本之间的差异。

    两侧均通过 to_dict() 获取结构化快照后进行比较。
    to_dict() 内部自带锁保护，无需调用方额外加锁。

    Returns:
        diff 条目列表，每条格式:
        {"type": "modified"|"added"|"removed",
         "path": str,
         "old": str|None,
         "new": str|None}
    """
    disk_dict = disk_db.to_dict()
    mem_dict = mem_db.to_dict()

    entries: list[dict] = []

    # ── 1. 数据库级字段 ──
    for field in _DB_FIELDS:
        old_val = disk_dict.get(field)
        new_val = mem_dict.get(field)
        if not _values_equal(old_val, new_val):
            entries.append({
                'type': 'modified',
                'path': f'database.{field}',
                'old': _format_value(old_val),
                'new': _format_value(new_val),
            })

    # ── 2. 报文级 diff ──
    disk_msgs = disk_dict.get('messages', {})
    mem_msgs = mem_dict.get('messages', {})
    all_msg_keys = sorted(
        set(disk_msgs.keys()) | set(mem_msgs.keys()),
        key=_msg_key_sort,
    )

    for mk in all_msg_keys:
        in_disk = mk in disk_msgs
        in_mem = mk in mem_msgs

        if in_mem and not in_disk:
            entries.append({
                'type': 'added',
                'path': f'报文 {mk} ({mem_msgs[mk].get("name", "")})',
                'old': None, 'new': None,
            })
            continue

        if in_disk and not in_mem:
            entries.append({
                'type': 'removed',
                'path': f'报文 {mk} ({disk_msgs[mk].get("name", "")})',
                'old': None, 'new': None,
            })
            continue

        # 两者都有：报文字段 diff
        disk_msg = disk_msgs[mk]
        mem_msg = mem_msgs[mk]
        msg_label = f'报文 {mk}'

        for field in _MESSAGE_FIELDS:
            old_val = disk_msg.get(field)
            new_val = mem_msg.get(field)
            if not _values_equal(old_val, new_val):
                entries.append({
                    'type': 'modified',
                    'path': f'{msg_label}.{field}',
                    'old': _format_value(old_val),
                    'new': _format_value(new_val),
                })

        # ── 信号级 diff ──
        disk_sigs = disk_msg.get('signals', {})
        mem_sigs = mem_msg.get('signals', {})
        all_sig_keys = sorted(set(disk_sigs.keys()) | set(mem_sigs.keys()))

        for sk in all_sig_keys:
            sig_in_disk = sk in disk_sigs
            sig_in_mem = sk in mem_sigs

            if sig_in_mem and not sig_in_disk:
                entries.append({
                    'type': 'added',
                    'path': f'{msg_label}.信号 "{sk}"',
                    'old': None, 'new': None,
                })
                continue

            if sig_in_disk and not sig_in_mem:
                entries.append({
                    'type': 'removed',
                    'path': f'{msg_label}.信号 "{sk}"',
                    'old': None, 'new': None,
                })
                continue

            # 两者都有：信号字段 diff
            disk_sig = disk_sigs[sk]
            mem_sig = mem_sigs[sk]

            for field in _SIGNAL_FIELDS:
                old_val = disk_sig.get(field)
                new_val = mem_sig.get(field)
                if not _values_equal(old_val, new_val):
                    entries.append({
                        'type': 'modified',
                        'path': f'{msg_label}.信号 "{sk}".{field}',
                        'old': _format_value(old_val),
                        'new': _format_value(new_val),
                    })

    # ── 3. 值描述表 diff ──
    disk_vts = disk_dict.get('value_tables', {})
    mem_vts = mem_dict.get('value_tables', {})
    all_vt_keys = sorted(set(disk_vts.keys()) | set(mem_vts.keys()))

    for vk in all_vt_keys:
        vt_in_disk = vk in disk_vts
        vt_in_mem = vk in mem_vts

        if vt_in_mem and not vt_in_disk:
            entries.append({
                'type': 'added',
                'path': f'值描述表 "{vk}"',
                'old': None, 'new': None,
            })
        elif vt_in_disk and not vt_in_mem:
            entries.append({
                'type': 'removed',
                'path': f'值描述表 "{vk}"',
                'old': None, 'new': None,
            })
        elif disk_vts[vk] != mem_vts[vk]:
            entries.append({
                'type': 'modified',
                'path': f'值描述表 "{vk}"',
                'old': f'{len(disk_vts[vk])} 条',
                'new': f'{len(mem_vts[vk])} 条',
            })

    return entries
