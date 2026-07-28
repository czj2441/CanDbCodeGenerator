"""app.ws.handlers 共享工具函数。"""
import os


def pure_file_name(session) -> str:
    """从 session 中提取纯文件名。"""
    return os.path.basename(session.file_path)


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
