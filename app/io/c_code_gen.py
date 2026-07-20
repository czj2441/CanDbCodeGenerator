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

if TYPE_CHECKING:
    from app.models import CanDatabase, Message, Signal

logger = logging.getLogger(__name__)


# ── Template directory ─────────────────────────────────────────────────────────

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "c")


# ── Helper functions ────────────────────────────────────────────────────────────

def _sanitize_identifier(name: str) -> str:
    """Convert arbitrary string to valid C identifier.
    
    - Replace non-alphanumeric characters with underscore
    - Prefix with underscore if starts with digit
    - Use 'Unnamed' if empty
    """
    s = re.sub(r'[^a-zA-Z0-9_]', '_', name.strip() if name else '')
    if not s:
        s = 'Unnamed'
    elif s[0].isdigit():
        s = '_' + s
    return s


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


def _prepare_context(db: "CanDatabase") -> dict[str, Any]:
    """Transform CanDatabase into Jinja2 template context.
    
    MUST be called while holding db.with_lock().
    
    Returns:
        dict with keys: db_name, db_name_upper, generated_at, messages, signals, signal_count
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
        for sig in msg.signals:
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
