"""
save_diff_handler.py — 保存差异 WS Handler。

计算磁盘文件与内存数据之间的字段级差异，
供前端保存按钮悬停浮窗展示。
"""

import os

from app.models import CanDatabase
from app.services.file_persistence import load_session_file
from app.services.diff_engine import compute_save_diff
from app.ws.router import HandlerResult, HandlerError


class GetSaveDiffHandler:
    """计算内存数据与磁盘文件的字段级差异（只读操作）。"""

    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        file_path = session.file_path

        # 磁盘文件不存在 → 空 CanDatabase 作为基准，所有内容显示为 added
        if not os.path.isfile(file_path):
            disk_db = CanDatabase()
            entries = compute_save_diff(disk_db, session.db)
            return HandlerResult(
                data={"entries": entries, "count": len(entries)},
                session_id=sid,
            )

        # 读取磁盘文件作为基准
        disk_db = load_session_file(file_path, CanDatabase)
        if disk_db is None:
            raise HandlerError("DIFF_FAILED", "磁盘文件读取失败")

        entries = compute_save_diff(disk_db, session.db)
        return HandlerResult(
            data={"entries": entries, "count": len(entries)},
            session_id=sid,
        )
