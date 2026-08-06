"""app.ws.handlers 共享工具函数。"""
import os


def pure_file_name(session) -> str:
    """从 session 中提取纯文件名。"""
    return os.path.basename(session.file_path)


def _single_message_summary(m) -> dict:
    """构建单条报文摘要 dict。"""
    return {
        "id": m.id, "id_hex": f"0x{m.id:X}", "name": m.name,
        "dlc": m.dlc, "cycle_time": m.cycle_time,
        "is_fd": m.is_fd, "sender": m.sender, "comment": m.comment,
        "signal_count": len(m.signals),
        "total_signal_bits": sum(s.length for s in m.signals.values()),
    }


def build_messages_summary(db) -> dict[str, dict]:
    """构建报文摘要 dict（keyed by msg_id），供 full_sync / undo / redo / get_messages 复用。"""
    return {
        str(mid): _single_message_summary(m)
        for mid, m in sorted(db.messages.items())
    }


def build_undo_redo_events(session, db, action_type: str) -> tuple[list, int, list]:
    """构建 undo/redo 事件的公共逻辑。在 db.with_lock() 内调用。

    Returns: (events, new_version, integrity_errors)
    """
    messages_data = build_messages_summary(db)
    message_details = {str(mid): m.to_dict() for mid, m in db.messages.items()}
    new_version = db._bump_version()
    integrity_errors = db.full_validate()

    events = [{
        "type": action_type,
        "data": {
            "messages": messages_data,
            "message_details": message_details,
            "bus_type": db.bus_type,
            "value_tables": {k: dict(v) for k, v in db.value_tables.items()},
            "status": {"modified": db.modified,
                       "undo_count": len(session.undo_stack),
                       "redo_count": len(session.redo_stack)},
        },
        "data_version": new_version,
    }, {
        "type": "data_errors_changed",
        "data": {"errors": integrity_errors},
        "data_version": new_version,
    }]
    return events, new_version, integrity_errors


def validate_file_name(file_name: str) -> str:
    """校验文件名安全性，防止路径穿越和头注入。返回清洗后的文件名。

    Raises:
        ValueError: 文件名不安全
    """
    if not file_name or not isinstance(file_name, str):
        raise ValueError("Invalid file name")
    if '\x00' in file_name:
        raise ValueError("Null byte in file name")
    # Windows 文件系统保留字符（含 HTTP 头注入字符 "）
    _WIN_ILLEGAL = set(':*?"<>|')
    if any(c in _WIN_ILLEGAL for c in file_name):
        raise ValueError("Invalid characters in file name")
    if '/' in file_name or '\\' in file_name:
        raise ValueError("Path separator in file name")
    # 阻止 HTTP 头注入字符（CR/LF）
    if '\r' in file_name or '\n' in file_name:
        raise ValueError("Invalid characters in file name")
    if os.path.isabs(file_name):
        raise ValueError("Absolute path not allowed")
    clean = os.path.basename(os.path.normpath(file_name))
    if not clean or clean != file_name:
        raise ValueError("Invalid file name")
    return clean


def push_data_errors(events: list, db, new_version: int, affected_msg_ids: set[int]) -> None:
    """追加 data_errors_changed 事件到事件列表（增量数据完整性校验）。

    Args:
        affected_msg_ids: 受影响的报文 ID 集合，传给 validate_data_integrity()。
    """
    errors = db.validate_data_integrity(affected_msg_ids)
    events.append({
        "type": "data_errors_changed",
        "data": {"errors": errors},
        "data_version": new_version,
    })
