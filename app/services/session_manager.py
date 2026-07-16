"""
Session Manager - 会话管理与自动持久化

职责：
  - 创建/恢复/销毁编辑会话
  - 每个会话绑定一个数据文件，所有变更自动落盘
  - 会话超时自动清理
  - 与 HTTP 层完全解耦，不感知 HTTP

设计原则：
  - 线程安全（适合 ThreadingHTTPServer）
  - 模块化：不 import api_server，不感知 HTTP
  - 文件锁管理委托给 FileLockManager
  - 撤销/重做逻辑委托给 UndoEngine
"""

import logging
import os
import re
import threading
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

from .session import Session
from .file_persistence import (
    DATA_DIR, HEARTBEAT_TIMEOUT, HEARTBEAT_CHECK_INTERVAL, MAX_ORPHAN_STACKS,
    write_session_file, load_session_file, resolve_duplicate,
)
from .file_lock import FileLockManager
from .undo_engine import UndoEngine


class FileLockedError(Exception):
    """文件已被其他会话占用。"""
    pass


class FileNameExistsError(Exception):
    """文件名已存在（不允许重名）。"""
    pass


class SessionManager:
    """
    会话管理器。

    用法::

        mgr = SessionManager(data_dir="./data")
        mgr.set_model_factory(CanDatabase)       # 注入数据模型

        # 创建会话
        sid = mgr.create("project.properties", db_instance)

        # 获取会话
        session = mgr.get(sid)
        db = session.db  # 直接操作

        # 自动保存
        mgr.save(sid)

        # 恢复会话
        session = mgr.restore(sid)
    """

    def __init__(self, data_dir: str | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()  # 可重入锁，避免嵌套调用死锁
        self._file_lock = FileLockManager(self._lock)  # 文件锁管理（共享锁）
        self._undo = UndoEngine()  # 撤销/重做引擎
        self._model_factory = None  # 由外部注入
        self._heartbeat_timer: Optional[threading.Timer] = None
        # list_history 磁盘解析缓存: fname -> (mtime, size, msg_count, sig_count)
        self._history_cache: dict[str, tuple] = {}
        os.makedirs(self._data_dir, exist_ok=True)
        self._data_dir_real = os.path.realpath(self._data_dir)
        self._start_heartbeat_checker()

    # ── 路径安全 ──

    def _safe_path(self, file_name: str) -> str:
        """构造路径并验证不超出 data_dir 边界。"""
        path = os.path.join(self._data_dir, file_name)
        real = os.path.realpath(path)
        if not real.startswith(self._data_dir_real + os.sep) and real != self._data_dir_real:
            raise ValueError(f"Path traversal detected: {file_name}")
        return path

    # ── 依赖注入 ──

    def set_model_factory(self, factory):
        """注入数据模型工厂（如 CanDatabase 类）。"""
        self._model_factory = factory

    # ── 会话 CRUD ──

    @staticmethod
    def _strip_legacy_prefix(fname: str) -> str:
        """剥离旧格式 {12-hex}_{name}.properties 中的 session_id 前缀。

        若匹配旧格式，返回 {name}.properties；否则原样返回。
        """
        m = re.match(r'^[0-9a-f]{12}_(.+\.properties)$', fname)
        return m.group(1) if m else fname

    def _rename_legacy_file(self, old_fname: str) -> str:
        """将旧格式文件重命名为新格式，返回新文件名。

        若目标已存在则使用 resolve_duplicate 生成不冲突的名称。
        """
        new_fname = self._strip_legacy_prefix(old_fname)
        if new_fname == old_fname:
            return old_fname  # 非旧格式，无需处理
        old_path = os.path.join(self._data_dir, old_fname)
        new_path = os.path.join(self._data_dir, new_fname)
        if os.path.isfile(new_path):
            new_fname = resolve_duplicate(new_fname, self._data_dir)
            new_path = os.path.join(self._data_dir, new_fname)
        try:
            os.replace(old_path, new_path)
        except OSError as e:
            logger.warning("Failed to rename legacy file %s -> %s: %s", old_path, new_path, e)
            return old_fname  # 重命名失败，保持旧名
        # 迁移缓存
        cached = self._history_cache.pop(old_fname, None)
        if cached:
            self._history_cache[new_fname] = cached
        return new_fname

    def _find_legacy_file(self, clean_fname: str) -> str:
        """在 data 目录中查找匹配 clean_fname 的旧格式文件。

        例如 clean_fname="Untitled.properties" 可能对应磁盘上的
        "0fc9257db538_Untitled.properties"。
        返回找到的旧格式文件名，未找到则返回空字符串。
        """
        pattern = re.compile(r'^[0-9a-f]{12}_' + re.escape(clean_fname) + r'$')
        if not os.path.isdir(self._data_dir):
            return ''
        for fname in os.listdir(self._data_dir):
            if pattern.match(fname):
                return fname
        return ''

    def create(self, file_name: str, db) -> str:
        """
        创建新会话。

        Args:
            file_name: 文件名（不含路径），如 "project.properties"
            db: CanDatabase 实例

        Returns:
            session_id

        Raises:
            FileNameExistsError: 如果同名文件已存在
        """
        session_id = uuid.uuid4().hex[:12]
        # 校验文件名：去掉 .properties 后不能为空（含纯下划线）
        base_name = file_name[:-11].strip() if file_name.endswith('.properties') else file_name.strip()
        if not base_name or not base_name.strip("_"):
            file_name = "Untitled.properties"

        # 重名检查（create 始终由 UI 触发，严格拒绝）
        target_path = self._safe_path(file_name)
        if os.path.isfile(target_path):
            raise FileNameExistsError(f"File '{file_name}' already exists")
        with self._lock:
            for s in self._sessions.values():
                if os.path.basename(s.file_path) == file_name:
                    raise FileNameExistsError(f"File '{file_name}' is already open")

        file_path = self._safe_path(file_name)
        with self._lock:
            session = Session(session_id, file_path, db)
            self._sessions[session_id] = session
            self._file_lock.register(session_id, file_path)

        # 立即落盘（持有 db 锁确保序列化原子性）
        with db.with_lock():
            write_session_file(session, self._data_dir)
        logger.info("Session created: sid=%s -> %s", session_id, file_name)
        return session_id

    def get(self, session_id: str) -> Optional[Session]:
        """获取会话（自动续期）。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.touch()
            return session

    def restore(self, file_name: str, exclude_session: str = ''):
        """
        从磁盘恢复会话。

        Args:
            file_name: 文件名（如 "project.properties"）
            exclude_session: 排除的会话 ID（当前已打开的会话不视为锁定）
            
        Returns:
            Session 或 None（文件不存在/数据损坏）
            
        Raises:
            FileLockedError: 如果文件已被其他会话占用
        """
        with self._lock:
            # 先检查内存中是否已有该文件打开
            for session in self._sessions.values():
                if os.path.basename(session.file_path) == file_name:
                    # 检查锁
                    if session.id != exclude_session:
                        if self.is_file_locked(session.file_path, exclude_session=exclude_session):
                            raise FileLockedError(f"File '{file_name}' is opened in another tab")
                    self._file_lock.register(session.id, session.file_path)
                    session.touch()
                    return session

            # 从磁盘加载（精确路径）
            file_path = self._safe_path(file_name)
            if not os.path.isfile(file_path):
                # 尝试查找旧格式文件并透明重命名
                legacy_fname = self._find_legacy_file(file_name)
                if legacy_fname:
                    file_name = self._rename_legacy_file(legacy_fname)
                    file_path = self._safe_path(file_name)
                else:
                    return None

            # 检查文件锁（排除当前会话自身）
            if self.is_file_locked(file_path, exclude_session=exclude_session):
                raise FileLockedError(f"File '{file_name}' is opened in another tab")

            db = load_session_file(file_path, self._model_factory)
            if db is None:
                return None

            # 每次打开都生成新 session_id
            new_sid = uuid.uuid4().hex[:12]
            session = Session(new_sid, file_path, db)
            self._sessions[new_sid] = session
            self._file_lock.register(new_sid, file_path)
            # 恢复之前保留的撤销栈（以 file_name 为键）
            self._undo.restore_orphan(file_name, session)
            logger.info("Session restored: sid=%s from %s (%d messages)",
                        new_sid, file_name, len(db.messages))
            return session

    def save_as(self, original_session_id: str, new_name: str) -> str:
        """另存为：克隆当前会话数据到新文件，创建新 session 并切换。

        原始会话在 WS 切换后由 server 层 mark_stale，心跳超时后自动清理。

        Returns:
            新 session_id

        Raises:
            FileNameExistsError: 文件名与当前文件相同或磁盘同名文件已存在
            ValueError: session 不存在
        """
        session = self.get(original_session_id)
        if not session:
            raise ValueError("Session not found")

        # 名称清洗
        pure_name = new_name
        if pure_name.endswith(".properties"):
            pure_name = pure_name[:-11]
        if not pure_name or not pure_name.strip("_"):
            pure_name = "Untitled"

        file_name = f"{pure_name}.properties"

        # 与当前文件同名 → 直接拒绝
        current_file_name = os.path.basename(session.file_path)
        if file_name == current_file_name:
            raise FileNameExistsError(f"File '{file_name}' already exists")

        # 磁盘文件冲突时自动追加后缀
        target_path = self._safe_path(file_name)
        if os.path.isfile(target_path):
            try:
                file_name = resolve_duplicate(file_name, self._data_dir)
            except FileExistsError:
                raise FileNameExistsError(
                    f"Cannot find available name for '{file_name}' (too many duplicates)"
                )
            pure_name = file_name[:-11]  # 去掉 .properties

        # 深克隆 db（使用 type() 获取实际类，避免硬编码 CanDatabase）
        with session.db.with_lock():
            clone = type(session.db).from_dict(session.db.to_dict())
        clone.name = pure_name

        # 创建新 session（含文件锁注册）并落盘
        new_sid = self.create(file_name, clone)
        logger.info("Save-as: sid=%s -> %s (new_sid=%s)",
                    original_session_id[:8], file_name, new_sid)
        return new_sid

    def save(self, session_id: str) -> bool:
        """手动保存会话到磁盘，成功后重置 modified 标志。"""
        session = self.get(session_id)
        if not session:
            return False
        with session.db.with_lock():
            if not session.db.modified:
                return True
            logger.info("Saving session %s to %s", session_id[:8],
                        os.path.basename(session.file_path))
            try:
                write_session_file(session, self._data_dir)
            except OSError as e:
                logger.error("Failed to save session %s: %s", session_id[:8], e, exc_info=True)
                raise
            session.db.modified = False
        return True

    def save_all_dirty(self) -> int:
        """遍历所有活跃会话，保存所有已修改的。

        用于进程退出时保存（atexit）。（线程安全，不长期持锁）

        Returns:
            成功保存的会话数量
        """
        with self._lock:
            sids = list(self._sessions.keys())

        # 预检：统计脏会话数，无脏会话时静默返回
        dirty_sids = [sid for sid in sids
                      if self.get(sid) and self.get(sid).db.modified]
        if not dirty_sids:
            return 0
        logger.info("save_all_dirty: saving %d dirty session(s) out of %d total",
                    len(dirty_sids), len(sids))

        saved = 0
        failed = 0
        for sid in sids:
            session = self.get(sid)
            if not session:
                continue
            saved_ok = False
            try:
                saved_ok = self.save(sid)
            except Exception as e:
                session.save_error = str(e)    # 异常：记录错误
                logger.warning("save_all_dirty: failed to save %s: %s", sid[:8], e)

            if saved_ok:
                saved += 1
                session.save_error = None  # 成功：清除旧错误
            else:
                failed += 1
                if not session.save_error:
                    session.save_error = "Session disappeared during save"
                    logger.warning("save_all_dirty: save returned False for %s", sid[:8])
                # 紧急备份：save 失败时写入独立备份文件，与心跳超时路径保护级别一致
                try:
                    os.makedirs(self._data_dir, exist_ok=True)
                    content = session.db.to_properties_str()
                    emergency_path = os.path.join(
                        self._data_dir, f"{sid}_EMERGENCY.properties")
                    with open(emergency_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    logger.info("emergency backup written: %s", emergency_path)
                except Exception as e2:
                    logger.critical("emergency backup also failed for %s: %s", sid[:8], e2)
        logger.info("save_all_dirty: complete — %d succeeded, %d failed", saved, failed)
        return saved

    def destroy(self, session_id: str) -> bool:
        """销毁会话（内存 + 磁盘文件）。"""
        with self._lock:
            result = self._destroy(session_id)
        if result:
            logger.info("Session destroyed: sid=%s", session_id[:8])
        return result

    def list_sessions(self) -> list[dict]:
        """列出所有活跃会话信息。"""
        with self._lock:
            return [s.to_info() for s in self._sessions.values()]

    def list_history(self, exclude_session: str = '') -> list[dict]:
        """扫描 data 目录，返回所有历史文件记录。
        
        Args:
            exclude_session: 排除的会话 ID（当前已打开的会话不视为锁定）
        """
        import javaproperties

        history = []
        if not os.path.isdir(self._data_dir):
            return history
        
        # 构建 basename -> Session 的映射（用于优先使用内存数据）
        with self._lock:
            active_by_fname = {os.path.basename(s.file_path): s for s in self._sessions.values()}
        
        def _safe_mtime(n):
            try:
                return os.path.getmtime(os.path.join(self._data_dir, n))
            except OSError:
                return 0

        for fname in sorted(os.listdir(self._data_dir), key=_safe_mtime, reverse=True):
            if not fname.endswith(".properties"):
                continue
            # 透明处理旧格式文件：剥离 {session_id}_ 前缀
            display_fname = self._strip_legacy_prefix(fname)
            name = display_fname[:-11]  # 去掉 .properties 即为纯名称
            fpath = os.path.join(self._data_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                size = os.path.getsize(fpath)
            except OSError:
                continue
            
            # 优先从内存中的活跃 session 获取数据
            if fname in active_by_fname:
                session = active_by_fname[fname]
                with session.db.with_lock():
                    msg_count = len(session.db.messages)
                    sig_count = sum(len(m.signals) for m in session.db.messages.values())
                    is_modified = session.db.modified
            else:
                is_modified = False
                cached = self._history_cache.get(fname)
                if cached and cached[0] == mtime and cached[1] == size:
                    msg_count, sig_count = cached[2], cached[3]
                else:
                    msg_count = 0
                    sig_count = 0
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = javaproperties.loads(f.read())
                        msg_ids = set()
                        for k in data:
                            if k.startswith("messages."):
                                rest = k[len("messages."):]
                                mid_key = rest.split(".", 1)[0]
                                msg_ids.add(mid_key)
                                if ".signals." in rest and ".uuid" in rest:
                                    sig_count += 1
                        msg_count = len(msg_ids)
                    except Exception:
                        logger.debug("Failed to parse history file %s", fname, exc_info=True)
                    self._history_cache[fname] = (mtime, size, msg_count, sig_count)
            
            entry = {
                "file_name": display_fname,
                "name": name,
                "_disk_fname": fname,  # 实际磁盘文件名（内部用）
                "mtime": mtime,
                "size": size,
                "message_count": msg_count,
                "signal_count": sig_count,
                "is_locked": self.is_file_locked(os.path.normpath(fpath), exclude_session=exclude_session),
                "is_modified": is_modified,
            }
            # 活跃文件提供 session_id（供 steal_lock 使用）
            if fname in active_by_fname:
                entry["session_id"] = active_by_fname[fname].id
            history.append(entry)
        return history

    def delete_history(self, file_name: str) -> bool:
        """删除历史文件（内存 session + 磁盘文件）。"""
        # 清理内存中打开此文件的 session
        with self._lock:
            sids_to_remove = [
                sid for sid, s in self._sessions.items()
                if os.path.basename(s.file_path) == file_name
            ]
            for sid in sids_to_remove:
                self._sessions.pop(sid, None)
                self._file_lock.unregister(sid)
                self._file_lock.pop_heartbeat(sid)
            # 删除磁盘文件
            file_path = self._safe_path(file_name)
            self._history_cache.pop(file_name, None)
            self._undo.remove_orphan(file_name)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError as e:
                    logger.error("Failed to delete file %s: %s", file_path, e)
                    return False
                logger.info("History file deleted: %s", file_name)
                return True
            # 尝试查找并删除旧格式文件
            legacy_fname = self._find_legacy_file(file_name)
            if legacy_fname:
                legacy_path = self._safe_path(legacy_fname)
                self._history_cache.pop(legacy_fname, None)
                self._undo.remove_orphan(legacy_fname)
                try:
                    os.remove(legacy_path)
                except OSError as e:
                    logger.error("Failed to delete legacy file %s: %s", legacy_path, e)
                    return False
                logger.info("Legacy history file deleted: %s", legacy_fname)
                return True
            return bool(sids_to_remove)

    # ── 内部方法 ──

    def _destroy(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        file_name = os.path.basename(session.file_path)
        logger.info("Internal destroy: sid=%s file=%s", session_id[:8], file_name)
        # 保存孤儿撤销栈（委托给 UndoEngine）
        self._undo.save_orphan(file_name, session)
        # 释放文件锁和心跳（委托给 FileLockManager）
        self._file_lock.unregister(session_id)
        self._file_lock.pop_heartbeat(session_id)
        return True

    # ── 文件锁委托（保持原有 API 签名） ──

    def is_file_locked(self, file_path: str, exclude_session: str = '') -> bool:
        """检查文件是否被其他 session 占用。"""
        return self._file_lock.is_file_locked(file_path, exclude_session)

    def release_session(self, session_id: str, abort: bool = False) -> bool:
        """释放并销毁指定 session（幂等）。abort 参数保留兼容但无行为差异。"""
        with self._lock:
            if session_id not in self._sessions:
                return False
            logger.info("Session released: sid=%s abort=%s", session_id[:8], abort)
            return self._destroy(session_id)

    def update_heartbeat(self, session_id: str) -> bool:
        """更新指定 session 的心跳时间。"""
        return self._file_lock.update_heartbeat(session_id)

    def set_lock_released_callback(self, cb: callable):
        """注册锁释放回调。"""
        self._file_lock.set_lock_released_callback(cb)

    def fire_lock_released(self, session_id: str):
        """显式触发锁释放回调。"""
        self._file_lock.fire_lock_released(session_id)

    def has_lock(self, session_id: str) -> bool:
        """检查指定 session 是否仍持有文件锁。"""
        return self._file_lock.has_lock(session_id)

    def mark_stale(self, session_id: str):
        """将心跳前推至即将超时。"""
        self._file_lock.mark_stale(session_id)

    # ── 撤销/重做委托（保持原有 API 签名） ──

    def push_undo(self, session_id: str, snapshot: dict) -> bool:
        """推入撤销快照。"""
        session = self.get(session_id)
        if not session:
            return False
        return self._undo.push_undo(session, snapshot)

    def undo(self, session_id: str) -> dict:
        """执行撤销操作。"""
        session = self.get(session_id)
        if not session:
            return {"success": False, "message": "Session not found"}
        return self._undo.undo(session)

    def redo(self, session_id: str) -> dict:
        """执行重做操作。"""
        session = self.get(session_id)
        if not session:
            return {"success": False, "message": "Session not found"}
        return self._undo.redo(session)

    def clear_undo_stacks(self, session_id: str) -> bool:
        """清空撤销/重做栈。"""
        session = self.get(session_id)
        if not session:
            return False
        return self._undo.clear_stacks(session)

    # ── 心跳机制 ──

    def _cleanup_stale_heartbeats(self):
        """清理超时未心跳的 session，自动释放其文件锁。"""
        stale_sids = self._file_lock.get_stale_sessions(HEARTBEAT_TIMEOUT)

        for sid in stale_sids:
            try:
                with self._lock:
                    self._destroy(sid)
                self._file_lock.fire_lock_released(sid)
                logger.warning("Stale session cleaned: sid=%s (heartbeat timeout)", sid[:8])
            except Exception as e:
                logger.error("Error cleaning stale session %s: %s", sid[:8], e, exc_info=True)

        self._start_heartbeat_checker()

    def _start_heartbeat_checker(self):
        """启动心跳检查定时器。"""
        self._heartbeat_timer = threading.Timer(
            HEARTBEAT_CHECK_INTERVAL, self._cleanup_stale_heartbeats
        )
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _stop_heartbeat_checker(self):
        """停止心跳检查定时器。"""
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None


# ── 全局单例（由 api_server 初始化） ──
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def init_session_manager(data_dir: str | None = None) -> SessionManager:
    global _session_manager
    _session_manager = SessionManager(data_dir)
    return _session_manager
