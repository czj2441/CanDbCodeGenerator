"""C code generation (header + source) using Jinja2 templates.

Generates CanCom_UserDef_XXXX signal attribute data for AUTOSAR-style
CAN communication stacks.

Output:
  - .h header: signal attribute struct, signal ID enum, macros, extern declarations
  - .c source: signal attribute arrays per message
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, TYPE_CHECKING

import pypinyin
from pypinyin import Style as PinyinStyle

if TYPE_CHECKING:
    from app.models import CanDatabase, Message, Signal

logger = logging.getLogger(__name__)


# ── Template directory ─────────────────────────────────────────────────────────

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "c")


# ── Helper functions ────────────────────────────────────────────────────────────

def _sanitize_identifier(name: str) -> str:
    """Convert arbitrary string to valid C identifier component.
    
    - Replace non-alphanumeric characters with underscore
    - Use 'Unnamed' if empty
    """
    s = re.sub(r'[^a-zA-Z0-9_]', '_', name.strip() if name else '')
    if not s:
        s = 'Unnamed'
    return s


def _chinese_to_pinyin_identifier(text: str) -> str:
    """Convert text with possible Chinese characters to a C-safe identifier.

    Chinese characters are converted to pinyin (no tone marks).
    Non-Chinese characters are kept as-is.
    The result is passed through _sanitize_identifier().
    """
    if not text or not text.strip():
        return _sanitize_identifier(text or '')
    parts: list[str] = []
    for char in text.strip():
        if '\u4e00' <= char <= '\u9fff':
            py_list = pypinyin.pinyin(char, style=PinyinStyle.NORMAL)
            if py_list and py_list[0]:
                parts.append(py_list[0][0].capitalize())
        else:
            parts.append(char)
    return _sanitize_identifier(''.join(parts))


# ── C export filename ──────────────────────────────────────────────────────────

_C_EXPORT_PREFIX = "CanCom_UserDef_SigGen_"


def c_export_filename(db_name: str, kind: str) -> str:
    """生成 C 导出文件名: CanCom_UserDef_SigGen_{sanitized}.{h|c}
    
    Args:
        db_name: 原始数据库名（将被 sanitize）
        kind: 'h' 为头文件, 'c' 为源文件
    """
    sanitized = _sanitize_identifier(db_name)
    return f"{_C_EXPORT_PREFIX}{sanitized}{'.h' if kind == 'h' else '.c'}"


def _prepare_value_table_enums(db: "CanDatabase") -> list[dict]:
    """Build enum data for all value tables.

    Must be called while holding db.with_lock().
    """
    enums: list[dict] = []

    for vt_name in sorted(db.value_tables.keys()):
        vt_entries = db.value_tables[vt_name]

        # Type name: CanCom_UserDef_{Sanitized}_t  (原始大小写)
        sanitized_name = _chinese_to_pinyin_identifier(vt_name)

        entries: list[dict] = []
        seen_names: dict[str, int] = {}

        for key_str, desc in vt_entries.items():
            try:
                value = int(key_str)
            except (ValueError, TypeError):
                logger.warning("Value table '%s': skipping non-numeric key '%s'", vt_name, key_str)
                continue

            entry_name = _chinese_to_pinyin_identifier(desc)

            # Deduplicate entry names within the same enum
            if entry_name in seen_names:
                counter = seen_names[entry_name]
                while f"{entry_name}_{counter}" in seen_names:
                    counter += 1
                entry_name = f"{entry_name}_{counter}"
            seen_names[entry_name] = 1

            entries.append({
                'name': entry_name,
                'value': value,
                'comment': desc,
            })

        enums.append({
            'table_name': vt_name,
            'name_sanitized': sanitized_name,
            'entries': entries,
        })

    return enums


def _prepare_context(db: "CanDatabase") -> dict[str, Any]:
    """Transform CanDatabase into Jinja2 template context.
    
    MUST be called while holding db.with_lock().
    
    Returns:
        dict with keys: db_name, db_name_upper, generated_at, messages, signals, signal_count,
                        value_table_enums
    """
    db_name = _sanitize_identifier(db.name)
    
    messages_data = []
    all_signals = []
    global_idx = 0
    
    for msg_id in sorted(db.messages.keys()):
        msg = db.messages[msg_id]
        # Use PDU ID as identifier (no leading _; template separator provides it)
        msg_pdu = f"0x{msg.id:X}"
        
        msg_signals = []
        seen_sig_names: dict[str, int] = {}
        for sig in sorted(msg.signals.values(), key=lambda s: s.start_bit):
            sig_name = _sanitize_identifier(sig.name)
            # Signal-level dedup within same message
            if sig_name in seen_sig_names:
                sig_name = f"{sig_name}_{seen_sig_names[sig_name]}"
            else:
                seen_sig_names[sig_name] = 1
            
            sig_data = {
                'name': sig.name,
                'msg_name': msg.name,
                'msg_name_upper': msg_pdu.upper(),       # 0X100
                'sig_name': sig_name,
                'sig_name_upper': sig_name.upper(),
                'start_bit': sig.start_bit,
                'byte_order': sig.byte_order,
                'length': sig.length,
                'comment': sig.comment,
                'global_index': global_idx,
            }
            
            msg_signals.append(sig_data)
            all_signals.append(sig_data)
            global_idx += 1
        
        messages_data.append({
            'id': msg.id,
            'id_hex': f'0x{msg.id:X}',
            'name': msg.name,                             # comment: original name
            'name_sanitized': msg_pdu,                    # 0x100
            'name_upper': msg_pdu.upper(),                # 0X100
            'dlc': msg.dlc,
            'cycle_time': msg.cycle_time,
            'sender': msg.sender,
            'comment': msg.comment,
            'signals': msg_signals,
            'signal_count': len(msg_signals),
        })
    
    return {
        'db_name': db_name,
        'db_name_upper': db_name.upper(),
        'header_filename': f"{_C_EXPORT_PREFIX}{db_name}.h",
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'messages': messages_data,
        'signals': all_signals,
        'signal_count': global_idx,
        'value_table_enums': _prepare_value_table_enums(db),
    }


# ── Public API ──────────────────────────────────────────────────────────────────

def to_c_header_str(db: "CanDatabase") -> str:
    """Render C header file (.h). Thread-safe.
    
    Args:
        db: CanDatabase instance
        
    Returns:
        Generated C header code as string
    """
    import jinja2
    
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    
    template = env.get_template('signals.h.j2')
    
    with db.with_lock():
        context = _prepare_context(db)
        result = template.render(**context)
    logger.info("C header generated (%d signals)", context['signal_count'])
    return result


def to_c_source_str(db: "CanDatabase") -> str:
    """Render C source file (.c). Thread-safe.
    
    Args:
        db: CanDatabase instance
        
    Returns:
        Generated C source code as string
    """
    import jinja2
    
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    
    template = env.get_template('signals.c.j2')
    
    with db.with_lock():
        context = _prepare_context(db)
        result = template.render(**context)
    logger.info("C source generated (%d signals)", context['signal_count'])
    return result
