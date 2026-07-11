"""
FileLockManager — 文件锁 + 心跳超时管理。

从 SessionManager 提取的独立模块，管理会话对文件的独占访问和心跳检测。
与 SessionManager 共享同一把 RLock，保持锁语义一致。
"""

import os
import threading
import time
from typing import Optional

from .file_persistence import HEARTBEAT_TIMEOUT


class FileLockManager:
    """文件锁 + 心跳超时管理器。

    管理会话对文件的独占访问跟踪和心跳时间戳。
    与 SessionManager 共享同一把 RLock（由 SessionManager.__init__ 传入）。
    """

    def __init__(self, lock: threading.RLock):
        self._lock = lock  # 与 SessionManager 共享
        self._active_files: dict[str, set[str]] = {}  # norm_path -> {session_ids}
        self._heartbeats: dict[str, float] = {}  # session_id -> last_heartbeat_time
        self._lock_released_callback: Optional[callable] = None

    # ── 活跃文件注册 ──

    def register(self, session_id: str, file_path: str):
        """注册文件被当前 session 占用。（调用方必须已持有 self._lock）"""
        norm_path = os.path.normpath(file_path)
        if norm_path not in self._active_files:
            self._active_files[norm_path] = set()
        self._active_files[norm_path].add(session_id)
        self._heartbeats[session_id] = time.time()

    def unregister(self, session_id: str):
        """注销 session 占用的所有文件。（调用方必须已持有 self._lock）"""
        for file_path, sids in list(self._active_files.items()):
            sids.discard(session_id)
            if not sids:
                del self._active_files[file_path]

    # ── 锁状态查询 ──

    def is_file_locked(self, file_path: str, exclude_session: str = '') -> bool:
        """检查文件是否被其他 session 占用。（线程安全）"""
        with self._lock:
            norm_path = os.path.normpath(file_path)
            sids = self._active_files.get(norm_path, set())
            return bool(sids - {exclude_session})

    # ── 心跳管理 ──

    def update_heartbeat(self, session_id: str) -> bool:
        """更新指定 session 的心跳时间。（线程安全）"""
        with self._lock:
            if session_id not in self._heartbeats:
                return False
            self._heartbeats[session_id] = time.time()
            return True

    def has_lock(self, session_id: str) -> bool:
        """检查指定 session 是否仍持有文件锁。"""
        with self._lock:
            return session_id in self._heartbeats

    def mark_stale(self, session_id: str):
        """将心跳前推至即将超时，使心跳清理尽快释放锁。"""
        with self._lock:
            if session_id in self._heartbeats:
                self._heartbeats[session_id] = time.time() - (HEARTBEAT_TIMEOUT - 10)

    def get_stale_sessions(self, timeout: float) -> list[str]:
        """返回心跳超时的 session_id 列表。（线程安全）"""
        now = time.time()
        with self._lock:
            return [sid for sid, last_beat in list(self._heartbeats.items())
                    if now - last_beat > timeout]

    def cleanup_stale(self, session_ids: list[str]):
        """移除指定 session 的活跃注册和心跳。（线程安全）"""
        with self._lock:
            for sid in session_ids:
                self.unregister(sid)
                self._heartbeats.pop(sid, None)

    def pop_heartbeat(self, session_id: str):
        """移除单条心跳记录。（调用方必须已持有 self._lock）"""
        self._heartbeats.pop(session_id, None)

    # ── 回调 ──

    def set_lock_released_callback(self, cb: callable):
        """注册锁释放回调。WS 架构下用于广播 lock_stolen 事件。"""
        self._lock_released_callback = cb

    def fire_lock_released(self, session_id: str):
        """显式触发锁释放回调（供 StealLockHandler 等主动释放锁的场景调用）。"""
        if self._lock_released_callback:
            try:
                self._lock_released_callback(session_id)
            except Exception as e:
                print(f"[FileLockManager] lock_released_callback error: {e}")
