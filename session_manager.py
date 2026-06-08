"""
Session Manager - 会话管理与自动持久化

职责：
  - 创建/恢复/销毁编辑会话
  - 每个会话绑定一个数据文件，所有变更自动落盘
  - 会话超时自动清理
  - 与 HTTP 层完全解耦，可独立测试

设计原则：
  - 线程安全（适合 ThreadingHTTPServer）
  - 模块化：不 import api_server，不感知 HTTP
"""

import json
import os
import threading
import time
import toml
import uuid
from typing import Optional


class FileLockedError(Exception):
    """文件已被其他会话占用。"""
    pass

# 数据模型从 api_server 导入（循环依赖通过延迟导入解决）
# 实际使用时由 api_server 注入模型类

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SESSION_TIMEOUT = 30 * 60  # 30 分钟无操作自动过期
HEARTBEAT_TIMEOUT = 30       # 30 秒无心跳则视为离线，自动释放文件锁
HEARTBEAT_CHECK_INTERVAL = 30  # 每 30 秒检查一次心跳超时


class Session:
    """单个编辑会话。"""

    def __init__(self, session_id: str, file_path: str, db):
        self.id = session_id
        self.file_path = file_path          # 绑定的数据文件绝对路径
        self.db = db                         # CanDatabase 实例
        self.created_at = time.time()
        self.last_access = time.time()

    def touch(self):
        self.last_access = time.time()

    def is_expired(self, timeout: float = SESSION_TIMEOUT) -> bool:
        return time.time() - self.last_access > timeout

    def to_info(self) -> dict:
        return {
            "session_id": self.id,
            "file_path": self.file_path,
            "file_name": os.path.basename(self.file_path),
            "message_count": len(self.db.messages),
            "signal_count": sum(len(m.signals) for m in self.db.messages.values()),
            "db_name": self.db.name,
            "created_at": self.created_at,
            "last_access": self.last_access,
        }


class SessionManager:
    """
    会话管理器。

    用法::

        mgr = SessionManager(data_dir="./data")
        mgr.set_model_factory(CanDatabase)       # 注入数据模型

        # 创建会话
        sid = mgr.create("project.canmatrix", db_instance)

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
        self._active_files: dict[str, set[str]] = {}  # file_path -> {session_ids}
        self._lock = threading.RLock()  # 可重入锁，避免嵌套调用死锁
        self._model_factory = None  # 由外部注入
        self._heartbeats: dict[str, float] = {}  # session_id -> last_heartbeat_time
        self._heartbeat_timer: Optional[threading.Timer] = None
        os.makedirs(self._data_dir, exist_ok=True)
        self._start_heartbeat_checker()

    # ── 依赖注入 ──

    def set_model_factory(self, factory):
        """注入数据模型工厂（如 CanDatabase 类）。"""
        self._model_factory = factory

    # ── 会话 CRUD ──

    def create(self, file_name: str, db) -> str:
        """
        创建新会话。

        Args:
            file_name: 文件名（不含路径），如 "project.toml"
            db: CanDatabase 实例

        Returns:
            session_id
        """
        session_id = uuid.uuid4().hex[:12]
        file_path = os.path.join(self._data_dir, file_name)

        with self._lock:
            session = Session(session_id, file_path, db)
            self._sessions[session_id] = session
            self._register_active(session_id, file_path)

        # 立即落盘
        self._write_file(session)
        return session_id

    def get(self, session_id: str) -> Optional[Session]:
        """获取会话（自动续期）。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                if session.is_expired():
                    self._destroy(session_id)
                    return None
                session.touch()
            return session

    def restore(self, session_id: str, exclude_session: str = ''):
        """
        从磁盘恢复会话。

        Args:
            session_id: 要恢复的会话 ID
            exclude_session: 排除的会话 ID（当前已打开的会话不视为锁定）
            
        Returns:
            Session 或 None（文件不存在/已过期/数据损坏）
            
        Raises:
            FileLockedError: 如果文件已被其他会话占用
        """
        with self._lock:
            # 先检查内存中是否已有
            session = self._sessions.get(session_id)
            if session:
                if session.is_expired():
                    self._destroy(session_id)
                    return None
                # 检查锁：如果内存中的 session 被其他标签页占用，拒绝恢复
                if exclude_session and session_id != exclude_session:
                    if self.is_file_locked(session.file_path, exclude_session=exclude_session):
                        raise FileLockedError(f"File '{_pure_file_name_from_path(session.file_path)}' is opened in another tab")
                # 重新注册活动文件（防止服务器重启后 _active_files 丢失）
                self._register_active(session_id, session.file_path)
                session.touch()
                return session

            # 尝试从磁盘加载
            file_path = self._find_session_file(session_id)
            if not file_path:
                return None

            # 检查文件锁（排除当前会话自身）
            if self.is_file_locked(file_path, exclude_session=exclude_session):
                raise FileLockedError(f"File '{_pure_file_name_from_path(file_path)}' is opened in another tab")

            db = self._load_file(file_path)
            if db is None:
                return None

            session = Session(session_id, file_path, db)
            self._sessions[session_id] = session
            self._register_active(session_id, file_path)
            return session

    def rename(self, session_id: str, new_name: str) -> bool:
        """重命名会话的数据库名称并同步更新文件名。"""
        session = self.get(session_id)
        if not session:
            return False

        # 防御性提取纯名称（去掉可能的 session_id 前缀和 .toml 后缀）
        pure_name = new_name
        if pure_name.startswith(session_id + "_"):
            pure_name = pure_name[len(session_id) + 1:]
        if pure_name.endswith(".toml"):
            pure_name = pure_name[:-5]

        old_path = session.file_path
        # 新文件名: {session_id}_{pure_name}.toml
        new_file_name = f"{session_id}_{pure_name}.toml"
        new_path = os.path.join(self._data_dir, new_file_name)

        # 如果新旧路径不同，移动文件
        if os.path.normpath(old_path) != os.path.normpath(new_path):
            # 更新活跃文件追踪
            self._unregister_active(session_id)
            # 删除可能已存在的目标文件
            if os.path.isfile(new_path):
                try:
                    os.remove(new_path)
                except OSError:
                    pass
            if os.path.isfile(old_path):
                try:
                    os.rename(old_path, new_path)
                except OSError:
                    # 移动失败，仍然尝试在新路径写入
                    pass
            session.file_path = new_path
            self._register_active(session_id, new_path)

        session.db.name = pure_name
        self._write_file(session)
        session.db.modified = False
        return True

    def save(self, session_id: str) -> bool:
        """手动保存会话到磁盘，成功后重置 modified 标志。"""
        session = self.get(session_id)
        if not session:
            return False
        with session.db.with_lock():
            self._write_file(session)
            session.db.modified = False
        return True

    def destroy(self, session_id: str) -> bool:
        """销毁会话（内存 + 磁盘文件）。"""
        with self._lock:
            return self._destroy(session_id)

    def list_sessions(self) -> list[dict]:
        """列出所有活跃会话信息。"""
        with self._lock:
            self._cleanup_expired()
            return [s.to_info() for s in self._sessions.values()]

    def list_history(self, exclude_session: str = '') -> list[dict]:
        """扫描 data 目录，返回所有历史会话记录（含已过期但文件仍在的）。
        
        Args:
            exclude_session: 排除的会话 ID（当前已打开的会话不视为锁定）
        """
        history = []
        if not os.path.isdir(self._data_dir):
            return history
        
        # 构建 session_id -> Session 的映射（用于优先使用内存数据）
        with self._lock:
            active_sessions = {s.id: s for s in self._sessions.values()}
        
        for fname in sorted(os.listdir(self._data_dir), key=lambda n: os.path.getmtime(os.path.join(self._data_dir, n)), reverse=True):
            if not fname.endswith(".toml"):
                continue
            # 文件名格式: {session_id}_{name}.toml
            parts = fname[:-5].split("_", 1)  # 去掉 .toml
            if len(parts) < 2:
                continue
            sid, name = parts[0], parts[1]
            fpath = os.path.join(self._data_dir, fname)
            mtime = os.path.getmtime(fpath)
            size = os.path.getsize(fpath)
            
            # 优先从内存中的活跃 session 获取数据
            if sid in active_sessions:
                session = active_sessions[sid]
                msg_count = len(session.db.messages)
                sig_count = sum(len(m.signals) for m in session.db.messages.values())
            else:
                # 从磁盘文件读取
                msg_count = 0
                sig_count = 0
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = toml.load(f)
                    msg_count = len(data.get("messages", []))
                    sig_count = sum(len(m.get("signals", [])) for m in data.get("messages", []))
                except Exception:
                    pass
            
            history.append({
                "session_id": sid,
                "file_name": fname,
                "name": name,
                "mtime": mtime,
                "size": size,
                "message_count": msg_count,
                "signal_count": sig_count,
                "is_locked": self.is_file_locked(os.path.normpath(fpath), exclude_session=exclude_session),
            })
        return history

    def load_history(self, session_id: str) -> Session | None:
        """从历史文件加载数据，创建一个新的独立会话（原 session 保留）。"""
        file_path = self._find_session_file(session_id)
        if not file_path:
            return None
        db = self._load_file(file_path)
        if db is None:
            return None
        # 创建新 session（新 ID），但数据来自历史文件
        new_sid = uuid.uuid4().hex[:12]
        base = os.path.basename(file_path)
        # 去掉旧 session_id 前缀
        if "_" in base:
            name_part = base.split("_", 1)[1]
        else:
            name_part = base
        new_file_name = f"{new_sid}_{name_part}"
        new_file_path = os.path.join(self._data_dir, new_file_name)
        # 先写入新文件（统一使用 TOML 格式）
        tmp_path = new_file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(db.to_toml_str())
        os.replace(tmp_path, new_file_path)

        session = Session(new_sid, new_file_path, db)
        with self._lock:
            self._sessions[new_sid] = session
        return session

    def delete_history(self, session_id: str) -> bool:
        """删除历史会话（内存 + 磁盘文件）。"""
        with self._lock:
            # 清理内存中的 session
            self._sessions.pop(session_id, None)
            # 删除磁盘文件
            file_path = self._find_session_file(session_id)
            if file_path and os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    return False
                return True
            return False

    def cleanup(self):
        """清理过期会话。"""
        with self._lock:
            self._cleanup_expired()

    # ── 内部方法 ──

    def _destroy(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        self._unregister_active(session_id)
        self._heartbeats.pop(session_id, None)
        # 不删除磁盘文件（用户数据保留），仅清理内存
        return True

    def _cleanup_expired(self):
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            self._unregister_active(sid)
            self._sessions.pop(sid, None)

    # ── 活跃文件锁管理 ──

    def _register_active(self, session_id: str, file_path: str):
        """注册文件被当前 session 占用。（调用方必须已持有 self._lock）"""
        norm_path = os.path.normpath(file_path)
        if norm_path not in self._active_files:
            self._active_files[norm_path] = set()
        self._active_files[norm_path].add(session_id)
        # 初始化心跳时间，给前端留出时间开始发送心跳
        self._heartbeats[session_id] = time.time()

    def _unregister_active(self, session_id: str):
        """注销 session 占用的所有文件。（调用方必须已持有 self._lock）"""
        for file_path, sids in list(self._active_files.items()):
            sids.discard(session_id)
            if not sids:
                del self._active_files[file_path]

    def is_file_locked(self, file_path: str, exclude_session: str = '') -> bool:
        """检查文件是否被其他 session 占用。（线程安全）"""
        with self._lock:
            norm_path = os.path.normpath(file_path)
            sids = self._active_files.get(norm_path, set())
            return bool(sids - {exclude_session})

    def release_session(self, session_id: str) -> bool:
        """释放指定 session 的文件锁。（公共 API，线程安全）"""
        with self._lock:
            if session_id not in self._sessions:
                return False
            self._unregister_active(session_id)
            self._heartbeats.pop(session_id, None)
            return True

    # ── 心跳机制 ──

    def update_heartbeat(self, session_id: str) -> bool:
        """更新指定 session 的心跳时间。（线程安全）

        由前端编辑器标签页定期调用，表明该标签页仍在活跃编辑中。
        """
        with self._lock:
            if session_id not in self._sessions:
                return False
            self._heartbeats[session_id] = time.time()
            return True

    def _cleanup_stale_heartbeats(self):
        """清理超时未心跳的 session，自动释放其文件锁。

        由后台定时器每 HEARTBEAT_CHECK_INTERVAL 秒调用一次。
        """
        now = time.time()
        stale_sids = []
        with self._lock:
            for sid, last_beat in list(self._heartbeats.items()):
                if now - last_beat > HEARTBEAT_TIMEOUT:
                    stale_sids.append(sid)

        for sid in stale_sids:
            self.release_session(sid)

        # 重新调度下一次检查
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

    def _find_session_file(self, session_id: str) -> Optional[str]:
        """在 data 目录中查找属于该 session 的文件（优先 .toml，兼容 .canmatrix）。"""
        if not os.path.isdir(self._data_dir):
            return None
        for fname in os.listdir(self._data_dir):
            if fname.startswith(session_id + "_") and fname.endswith(".toml"):
                return os.path.join(self._data_dir, fname)
        # 兼容旧格式
        for fname in os.listdir(self._data_dir):
            if fname.startswith(session_id + "_") and fname.endswith(".canmatrix"):
                return os.path.join(self._data_dir, fname)
        return None

    def _write_file(self, session: Session):
        """将会话数据以 TOML 格式写入磁盘。

        调用方必须已持有 session.db 的锁（通过 with_lock()），
        因为 to_toml_str() 内部也会获取同一把 RLock，外部持锁可避免
        三重嵌套并保证写操作原子性。
        """
        content = session.db.to_toml_str()
        # 文件名包含 session_id 前缀，便于恢复时查找
        base = os.path.basename(session.file_path)
        if not base.startswith(session.id):
            base = f"{session.id}_{base}"
        # 统一使用 .toml 后缀
        if base.endswith(".canmatrix"):
            base = base[:-10] + ".toml"
        elif not base.endswith(".toml"):
            base += ".toml"
        file_path = os.path.join(self._data_dir, base)
        session.file_path = file_path

        tmp_path = file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, file_path)  # 原子写入

    def _load_file(self, file_path: str):
        """从磁盘加载 TOML 数据文件，返回 CanDatabase 实例。"""
        if not os.path.isfile(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if self._model_factory:
                return self._model_factory.from_toml_str(content)
            return None
        except Exception:
            return None


def _pure_file_name_from_path(file_path: str) -> str:
    """从完整文件路径中提取纯名称（去掉 session_id 前缀和 .toml 后缀）。"""
    fname = os.path.basename(file_path)
    if fname.endswith('.toml'):
        fname = fname[:-5]
    parts = fname.split('_', 1)
    return parts[1] if len(parts) > 1 else fname


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
