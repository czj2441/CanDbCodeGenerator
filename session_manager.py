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
import uuid
from typing import Optional


class FileLockedError(Exception):
    """文件已被其他会话占用。"""
    pass


class FileNameExistsError(Exception):
    """文件名已存在（不允许重名）。"""
    pass

# 打包后数据目录放在用户 AppData，未打包时在源码目录
import sys as _sys
if getattr(_sys, 'frozen', False):
    # PyInstaller 打包：使用 %APPDATA%/CanMatrixEditor/data
    _app_data = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CanMatrixEditor')
    DATA_DIR = os.path.join(_app_data, 'data')
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HEARTBEAT_TIMEOUT = 30       # 30 秒无心跳则视为离线，自动释放文件锁
HEARTBEAT_CHECK_INTERVAL = 30  # 每 30 秒检查一次心跳超时
MAX_ORPHAN_STACKS = 20         # 孤儿撤销栈最大保留数量（LRU 淘汰）


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
        self._active_files: dict[str, set[str]] = {}  # file_path -> {session_ids}
        self._lock = threading.RLock()  # 可重入锁，避免嵌套调用死锁
        self._model_factory = None  # 由外部注入
        self._heartbeats: dict[str, float] = {}  # session_id -> last_heartbeat_time
        self._heartbeat_timer: Optional[threading.Timer] = None
        # 已销毁会话的撤销栈（重新打开页面时可恢复）
        self._orphan_stacks: dict[str, dict] = {}
        # 锁释放回调（WS 架构下用于广播 lock_stolen）
        self._lock_released_callback: Optional[callable] = None
        # list_history 磁盘解析缓存: fname -> (mtime, size, msg_count, sig_count)
        self._history_cache: dict[str, tuple] = {}
        os.makedirs(self._data_dir, exist_ok=True)
        self._start_heartbeat_checker()

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
        import re
        m = re.match(r'^[0-9a-f]{12}_(.+\.properties)$', fname)
        return m.group(1) if m else fname

    def _rename_legacy_file(self, old_fname: str) -> str:
        """将旧格式文件重命名为新格式，返回新文件名。

        若目标已存在则使用 _resolve_duplicate 生成不冲突的名称。
        """
        new_fname = self._strip_legacy_prefix(old_fname)
        if new_fname == old_fname:
            return old_fname  # 非旧格式，无需处理
        old_path = os.path.join(self._data_dir, old_fname)
        new_path = os.path.join(self._data_dir, new_fname)
        if os.path.isfile(new_path):
            new_fname = self._resolve_duplicate(new_fname)
            new_path = os.path.join(self._data_dir, new_fname)
        try:
            os.replace(old_path, new_path)
        except OSError:
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
        import re
        pattern = re.compile(r'^[0-9a-f]{12}_' + re.escape(clean_fname) + r'$')
        if not os.path.isdir(self._data_dir):
            return ''
        for fname in os.listdir(self._data_dir):
            if pattern.match(fname):
                return fname
        return ''

    def _resolve_duplicate(self, base_name: str) -> str:
        """重名时生成递增序号的 fallback 文件名。 Untitled.properties → Untitled_1.properties"""
        name, ext = os.path.splitext(base_name)
        i = 1
        while True:
            candidate = f"{name}_{i}{ext}"
            if not os.path.isfile(os.path.join(self._data_dir, candidate)):
                return candidate
            i += 1

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
        target_path = os.path.join(self._data_dir, file_name)
        if os.path.isfile(target_path):
            raise FileNameExistsError(f"File '{file_name}' already exists")
        with self._lock:
            for s in self._sessions.values():
                if os.path.basename(s.file_path) == file_name:
                    raise FileNameExistsError(f"File '{file_name}' is already open")

        file_path = os.path.join(self._data_dir, file_name)
        with self._lock:
            session = Session(session_id, file_path, db)
            self._sessions[session_id] = session
            self._register_active(session_id, file_path)

        # 立即落盘（持有 db 锁确保序列化原子性）
        with db.with_lock():
            self._write_file(session)
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
                    if exclude_session and session.id != exclude_session:
                        if self.is_file_locked(session.file_path, exclude_session=exclude_session):
                            raise FileLockedError(f"File '{file_name}' is opened in another tab")
                    self._register_active(session.id, session.file_path)
                    session.touch()
                    return session

            # 从磁盘加载（精确路径）
            file_path = os.path.join(self._data_dir, file_name)
            if not os.path.isfile(file_path):
                # 尝试查找旧格式文件并透明重命名
                legacy_fname = self._find_legacy_file(file_name)
                if legacy_fname:
                    file_name = self._rename_legacy_file(legacy_fname)
                    file_path = os.path.join(self._data_dir, file_name)
                else:
                    return None

            # 检查文件锁（排除当前会话自身）
            if self.is_file_locked(file_path, exclude_session=exclude_session):
                raise FileLockedError(f"File '{file_name}' is opened in another tab")

            db = self._load_file(file_path)
            if db is None:
                return None

            # 每次打开都生成新 session_id
            new_sid = uuid.uuid4().hex[:12]
            session = Session(new_sid, file_path, db)
            self._sessions[new_sid] = session
            self._register_active(new_sid, file_path)
            # 恢复之前保留的撤销栈（以 file_name 为键）
            orphan = self._orphan_stacks.pop(file_name, None)
            if orphan:
                session.undo_stack = orphan["undo_stack"]
                session.redo_stack = orphan["redo_stack"]
            return session

    def rename(self, session_id: str, new_name: str) -> bool:
        """重命名会话的数据库名称并同步更新文件名。

        Raises:
            FileNameExistsError: 如果新文件名已存在
        """
        session = self.get(session_id)
        if not session:
            return False

        # 提取纯名称（去掉 .properties 后缀）
        pure_name = new_name
        if pure_name.endswith(".properties"):
            pure_name = pure_name[:-11]

        # 名称不能为空（含纯下划线）
        if not pure_name or not pure_name.strip("_"):
            pure_name = "Untitled"

        old_path = session.file_path
        # 新文件名: {pure_name}.properties（不含 ID 前缀）
        new_file_name = f"{pure_name}.properties"
        new_path = os.path.join(self._data_dir, new_file_name)

        # 重名检查（排除自身）
        if os.path.normpath(old_path) != os.path.normpath(new_path):
            if os.path.isfile(new_path):
                raise FileNameExistsError(f"File '{new_file_name}' already exists")
            with self._lock:
                for s in self._sessions.values():
                    if s.id != session_id and os.path.basename(s.file_path) == new_file_name:
                        raise FileNameExistsError(f"File '{new_file_name}' is already open")

        # 如果新旧路径不同，移动文件
        if os.path.normpath(old_path) != os.path.normpath(new_path):
            with self._lock:
                self._unregister_active(session_id)
            try:
                if os.path.isfile(old_path):
                    os.replace(old_path, new_path)
                else:
                    print(f"[SessionManager] rename: old file not found, will recreate: {old_path}")
            except OSError:
                with self._lock:
                    session.file_path = old_path
                    self._register_active(session_id, old_path)
                return False
            with self._lock:
                session.file_path = new_path
                self._register_active(session_id, new_path)

        session.db.name = pure_name
        with session.db.with_lock():
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

    def save_all_dirty(self) -> int:
        """遍历所有活跃会话，保存所有已修改的。

        用于进程退出时保存（atexit）。（线程安全，不长期持锁）

        Returns:
            成功保存的会话数量
        """
        with self._lock:
            sids = list(self._sessions.keys())
        saved = 0
        for sid in sids:
            session = self.get(sid)
            if not session:
                continue
            if not session.db.modified:
                continue
            saved_ok = False
            try:
                saved_ok = self.save(sid)
            except Exception as e:
                session.save_error = str(e)    # 异常：记录错误
                print(f"[WARN] save_all_dirty: failed to save {sid[:8]}: {e}")

            if saved_ok:
                saved += 1
                session.save_error = None  # 成功：清除旧错误
            else:
                if not session.save_error:
                    session.save_error = "Session disappeared during save"
                    print(f"[WARN] save_all_dirty: save returned False for {sid[:8]}")
                # 紧急备份：save 失败时写入独立备份文件，与心跳超时路径保护级别一致
                try:
                    os.makedirs(self._data_dir, exist_ok=True)
                    content = session.db.to_properties_str()
                    emergency_path = os.path.join(
                        self._data_dir, f"{sid}_EMERGENCY.properties")
                    with open(emergency_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    print(f"[SessionManager] emergency backup written: {emergency_path}")
                except Exception as e2:
                    print(f"[SessionManager] CRITICAL: emergency backup also failed for {sid[:8]}: {e2}")
        return saved

    def destroy(self, session_id: str) -> bool:
        """销毁会话（内存 + 磁盘文件）。"""
        with self._lock:
            return self._destroy(session_id)

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
                        pass
                    self._history_cache[fname] = (mtime, size, msg_count, sig_count)
            
            entry = {
                "file_name": display_fname,
                "name": name,
                "_disk_fname": fname,  # 实际磁盘文件名（内部使用）
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
                self._unregister_active(sid)
                self._heartbeats.pop(sid, None)
            # 删除磁盘文件
            file_path = os.path.join(self._data_dir, file_name)
            self._history_cache.pop(file_name, None)
            self._orphan_stacks.pop(file_name, None)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                except OSError:
                    return False
                return True
            # 尝试查找并删除旧格式文件
            legacy_fname = self._find_legacy_file(file_name)
            if legacy_fname:
                legacy_path = os.path.join(self._data_dir, legacy_fname)
                self._history_cache.pop(legacy_fname, None)
                self._orphan_stacks.pop(legacy_fname, None)
                try:
                    os.remove(legacy_path)
                except OSError:
                    return False
                return True
            return bool(sids_to_remove)

    # ── 撤销/重做栈管理 ──

    def push_undo(self, session_id: str, snapshot: dict) -> bool:
        """
        推入撤销快照。
        
        Args:
            session_id: 会话 ID
            snapshot: 撤销快照，包含 type, prev, next, data 等字段
            
        Returns:
            是否成功推入
        """
        session = self.get(session_id)
        if not session:
            return False
        
        with session._undo_lock:
            # 深度克隆快照（避免引用污染）
            try:
                snap_copy = json.loads(json.dumps(snapshot))
            except (TypeError, ValueError):
                snap_copy = dict(snapshot)  # 浅拷贝回退
            
            session.undo_stack.append(snap_copy)
            
            # 限制栈大小
            if len(session.undo_stack) > session.MAX_UNDO_SIZE:
                session.undo_stack.pop(0)  # 移除最早的记录
            
            # 新操作清空 redo 栈（标准行为）
            session.redo_stack.clear()
            
            return True

    def undo(self, session_id: str) -> dict:
        """
        执行撤销操作。
        
        Args:
            session_id: 会话 ID
            
        Returns:
            {"success": bool, "message": str, "data": dict}
        """
        session = self.get(session_id)
        if not session:
            return {"success": False, "message": "Session not found"}
        
        with session._undo_lock:
            if not session.undo_stack:
                return {"success": False, "message": "No operation to undo"}
            
            snap = session.undo_stack.pop()
            
            # 推入 redo 栈
            session.redo_stack.append(snap)
            
            # 执行撤销逻辑（统一持有 db 锁，保证原子性）
            # 不立即落盘，由手动保存处理
            try:
                with session.db.with_lock():
                    self._execute_undo(session, snap)
                    session.db.modified = True  # undo 绕过 CRUD，需显式标记
                
                return {
                    "success": True,
                    "message": "Undo successful",
                    "data": {
                        "undo_count": len(session.undo_stack),
                        "redo_count": len(session.redo_stack),
                    }
                }
            except Exception as e:
                # 撤销失败，恢复 undo 栈
                session.undo_stack.append(snap)
                return {"success": False, "message": f"Undo failed: {str(e)}"}

    def redo(self, session_id: str) -> dict:
        """
        执行重做操作。
        
        Args:
            session_id: 会话 ID
            
        Returns:
            {"success": bool, "message": str, "data": dict}
        """
        session = self.get(session_id)
        if not session:
            return {"success": False, "message": "Session not found"}
        
        with session._undo_lock:
            if not session.redo_stack:
                return {"success": False, "message": "No operation to redo"}
            
            snap = session.redo_stack.pop()
            
            # 推回 undo 栈
            session.undo_stack.append(snap)
            
            # 执行重做逻辑（统一持有 db 锁，保证原子性）
            # 不立即落盘，由手动保存处理
            try:
                with session.db.with_lock():
                    self._execute_redo(session, snap)
                    session.db.modified = True  # redo 绕过 CRUD，需显式标记
                
                return {
                    "success": True,
                    "message": "Redo successful",
                    "data": {
                        "undo_count": len(session.undo_stack),
                        "redo_count": len(session.redo_stack),
                    }
                }
            except Exception as e:
                # 重做失败，恢复 redo 栈
                session.redo_stack.append(snap)
                return {"success": False, "message": f"Redo failed: {str(e)}"}

    def clear_undo_stacks(self, session_id: str) -> bool:
        """清空撤销/重做栈（会话切换或清理时调用）。"""
        session = self.get(session_id)
        if not session:
            return False
        
        with session._undo_lock:
            session.undo_stack.clear()
            session.redo_stack.clear()
            return True

    # ── 撤销/重做执行逻辑（策略模式） ──

    def _execute_undo(self, session: Session, snap: dict):
        """执行撤销操作（根据 type 分发到不同处理器）。"""
        snap_type = snap.get("type")
        
        if snap_type == "message_delete":
            # 撤销删除报文 = 恢复报文
            self._restore_message(session, snap["data"])
        elif snap_type == "signal_delete":
            # 撤销删除信号 = 恢复信号
            self._restore_signal(session, snap["msgId"], snap["data"])
        elif snap_type == "message_update":
            # 撤销报文修改 = 恢复旧值
            self._restore_message_update(session, snap["msgId"], snap["prev"])
        elif snap_type == "signal_update":
            # 撤销信号修改 = 恢复旧值
            self._restore_signal_update(session, snap["msgId"], snap["sigUuid"], snap["prev"])
        elif snap_type == "message_add":
            # 撤销添加报文 = 删除报文
            self._delete_message(session, snap["msgId"])
        elif snap_type == "signal_add":
            # 撤销添加信号 = 删除信号
            self._delete_signal(session, snap["msgId"], snap["sigUuid"])
        elif snap_type == "batch_signal_add":
            # 撤销批量添加信号 = 逐个删除
            for sig in snap["signals"]:
                self._delete_signal(session, snap["msgId"], sig["uuid"])
        else:
            raise ValueError(f"Unknown undo type: {snap_type}")

    def _execute_redo(self, session: Session, snap: dict):
        """执行重做操作（撤销的逆操作）。"""
        snap_type = snap.get("type")
        
        if snap_type == "message_delete":
            # 重做删除报文 = 再次删除
            self._delete_message(session, snap["data"]["id"])
        elif snap_type == "signal_delete":
            # 重做删除信号 = 再次删除
            self._delete_signal(session, snap["msgId"], snap["data"]["uuid"])
        elif snap_type == "message_update":
            # 重做报文修改 = 应用新值
            self._restore_message_update(session, snap["msgId"], snap["next"])
        elif snap_type == "signal_update":
            # 重做信号修改 = 应用新值
            self._restore_signal_update(session, snap["msgId"], snap["sigUuid"], snap["next"])
        elif snap_type == "message_add":
            # 重做添加报文 = 再次创建
            self._restore_message(session, snap["data"])
        elif snap_type == "signal_add":
            # 重做添加信号 = 再次创建
            self._restore_signal(session, snap["msgId"], snap["data"])
        elif snap_type == "batch_signal_add":
            # 重做批量添加信号 = 逐个重新创建
            for sig in snap["signals"]:
                self._restore_signal(session, snap["msgId"], sig["data"])
        else:
            raise ValueError(f"Unknown redo type: {snap_type}")

    # ── 撤销/重做辅助方法 ──

    def _restore_message(self, session: Session, msg_data: dict):
        """恢复报文（含所有信号）。"""
        from models import Signal, Message
        
        msg_id = msg_data["id"]
        signals = []
        for sig_data in msg_data.get("signals", []):
            # sig_data 应该是字典（经过 JSON 序列化/反序列化）
            if isinstance(sig_data, dict):
                sig = Signal.from_dict(sig_data)
            else:
                # 如果已经是 Signal 对象（异常情况），直接使用
                sig = sig_data
            signals.append(sig)
        
        msg = Message(
            id=msg_id,
            name=msg_data["name"],
            dlc=msg_data.get("dlc", 8),
            cycle_time=msg_data.get("cycle_time", 0),
            sender=msg_data.get("sender", ""),
            comment=msg_data.get("comment", ""),
            signals=signals,
        )
        
        session.db.messages[msg_id] = msg

    def _restore_signal(self, session: Session, msg_id: int, sig_data: dict):
        """恢复信号。"""
        from models import Signal
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")
        
        sig = Signal.from_dict(sig_data)
        msg.signals.append(sig)

    def _restore_message_update(self, session: Session, msg_id: int, updates: dict):
        """恢复报文属性更新。"""
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")
        
        for key, value in updates.items():
            if hasattr(msg, key):
                setattr(msg, key, value)

    def _restore_signal_update(self, session: Session, msg_id: int, sig_uuid: str, updates: dict):
        """恢复信号属性更新。"""
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")
        
        # signals 是列表，需要查找
        sig = next((s for s in msg.signals if s.uuid == sig_uuid), None)
        if not sig:
            raise ValueError(f"Signal {sig_uuid} not found")
        
        for key, value in updates.items():
            if hasattr(sig, key):
                setattr(sig, key, value)

    def _delete_message(self, session: Session, msg_id: int):
        """删除报文。"""
        session.db.messages.pop(msg_id, None)

    def _delete_signal(self, session: Session, msg_id: int, sig_uuid: str):
        """删除信号。"""
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")
        
        # ✅ 原地修改，保持列表引用不变
        msg.signals[:] = [s for s in msg.signals if s.uuid != sig_uuid]

    # ── 内部方法 ──

    def _destroy(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        # 保留撤销栈，以便重新打开页面后仍可撤销
        file_name = os.path.basename(session.file_path)
        with session._undo_lock:
            self._orphan_stacks[file_name] = {
                "undo_stack": list(session.undo_stack),
                "redo_stack": list(session.redo_stack),
            }
        self._unregister_active(session_id)
        self._heartbeats.pop(session_id, None)
        # 不删除磁盘文件（用户数据保留），仅清理内存
        # LRU 淘汰：保留最近的 MAX_ORPHAN_STACKS 个孤儿栈
        while len(self._orphan_stacks) > MAX_ORPHAN_STACKS:
            oldest_key = next(iter(self._orphan_stacks))
            self._orphan_stacks.pop(oldest_key)
        return True

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

    def release_session(self, session_id: str, abort: bool = False) -> bool:
        """释放指定 session 的文件锁。

        Args:
            session_id: 会话 ID
            abort: 是否同时销毁 session（丢弃未保存变更）

        Returns:
            是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                return False
            if abort:
                return self._destroy(session_id)
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

    def set_lock_released_callback(self, cb: callable):
        """注册锁释放回调。WS 架构下用于广播 lock_stolen 事件。"""
        self._lock_released_callback = cb

    def fire_lock_released(self, session_id: str):
        """显式触发锁释放回调（供 StealLockHandler 等主动释放锁的场景调用）。"""
        if self._lock_released_callback:
            try:
                self._lock_released_callback(session_id)
            except Exception as e:
                print(f"[SessionManager] lock_released_callback error: {e}")

    def has_lock(self, session_id: str) -> bool:
        """检查指定 session 是否仍持有文件锁。"""
        with self._lock:
            return session_id in self._heartbeats

    def mark_stale(self, session_id: str):
        """将心跳前推至即将超时，使 _cleanup_stale_heartbeats 尽快释放锁。
        WS disconnection finally 块中调用。"""
        with self._lock:
            if session_id in self._heartbeats:
                self._heartbeats[session_id] = time.time() - (HEARTBEAT_TIMEOUT - 10)

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
            # 销毁 session（保留 orphan stack 以便恢复）
            with self._lock:
                self._destroy(sid)
            # 锁释放回调（WS 架构下广播 lock_stolen）
            self.fire_lock_released(sid)

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


    def _write_file(self, session: Session):
        """将会话数据以 Properties 格式写入磁盘。
    
        调用方必须已持有 session.db 的锁（通过 with_lock()），
        因为 to_properties_str() 内部会获取同一把 RLock，外部持锁可避免
        嵌套并保证写操作原子性。
        """
        content = session.db.to_properties_str()
        base = os.path.basename(session.file_path)
        if not base.endswith(".properties"):
            base += ".properties"
        check = base[:-11].strip() if base.endswith('.properties') else base.strip()
        if not check or not check.strip("_"):
            base = "Untitled.properties"
        # 非 UI 上下文（atexit 保存等）：重名时自动递增 fallback
        target = os.path.join(self._data_dir, base)
        if os.path.isfile(target) and session.file_path != target:
            base = self._resolve_duplicate(base)
            target = os.path.join(self._data_dir, base)
        file_path = target
        session.file_path = file_path
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, file_path)

    def _load_file(self, file_path: str):
        """从磁盘加载 Properties 数据文件，返回 CanDatabase 实例。"""
        if not os.path.isfile(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            if self._model_factory:
                return self._model_factory.from_properties_str(content)
            return None
        except Exception:
            return None



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
