"""
Session 数据类 — 单个编辑会话的状态容器。
"""
from __future__ import annotations

import os
import threading
import time


class Session:
    """单个编辑会话。"""

    # 撤销栈最大深度
    MAX_UNDO_SIZE = 50

    def __init__(self, session_id: str, file_path: str, db):
        self.id = session_id
        self.file_path = file_path          # 绑定的数据文件绝对路径
        self.db = db                         # CanDatabase 实例
        self.created_at = time.time()
        self.last_access = time.time()
        
        # 撤销/重做栈（RAM 中存储）
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self._undo_lock = threading.RLock()  # 撤销操作并发保护
        self.save_error: str | None = None  # 自动保存失败时的错误信息

    def touch(self):
        self.last_access = time.time()

    def to_info(self) -> dict:
        with self.db.with_lock():
            return {
                "session_id": self.id,
                "file_path": self.file_path,
                "file_name": os.path.basename(self.file_path),
                "message_count": len(self.db.messages),
                "signal_count": sum(len(m.signals) for m in self.db.messages.values()),
                "db_name": self.db.name,
                "created_at": self.created_at,
                "last_access": self.last_access,
                "undo_count": len(self.undo_stack),
                "redo_count": len(self.redo_stack),
            }
