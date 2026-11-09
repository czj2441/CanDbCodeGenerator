"""
UndoEngine — 撤销/重做引擎。

从 SessionManager 提取的独立模块，管理撤销/重做栈和孤儿栈。
所有公共方法接受 Session 对象（而非 session_id），不依赖 SessionManager。
"""

import json
import logging

logger = logging.getLogger(__name__)

from .file_persistence import MAX_ORPHAN_STACKS


class UndoEngine:
    """撤销/重做引擎。

    管理 Session 的 undo_stack / redo_stack 和已销毁会话的孤儿栈。
    不持有 SessionManager 引用，通过 Session 对象操作数据。
    """

    def __init__(self, max_orphan_stacks: int = MAX_ORPHAN_STACKS):
        self._orphan_stacks: dict[str, dict] = {}  # file_name -> {undo_stack, redo_stack}
        self._max_orphan_stacks = max_orphan_stacks

    # ── 撤销/重做栈操作 ──

    def push_undo(self, session, snapshot: dict) -> bool:
        """推入撤销快照。"""
        with session._undo_lock:
            # 深度克隆快照（避免引用污染）
            try:
                snap_copy = json.loads(json.dumps(snapshot))
            except (TypeError, ValueError) as e:
                logger.warning("Deep copy failed for undo snapshot, using shallow copy: %s", e)
                snap_copy = dict(snapshot)  # 浅拷贝回退

            session.undo_stack.append(snap_copy)

            # 限制栈大小
            if len(session.undo_stack) > session.MAX_UNDO_SIZE:
                session.undo_stack.pop(0)  # 移除最早的记录
                logger.debug("Undo stack overflow: dropping oldest (max_size=%d)", session.MAX_UNDO_SIZE)

            # 新操作清空 redo 栈（标准行为）
            session.redo_stack.clear()

            return True

    def undo(self, session) -> dict:
        """执行撤销操作。"""
        with session._undo_lock:
            if not session.undo_stack:
                return {"success": False, "message": "No operation to undo"}

            snap = session.undo_stack.pop()

            try:
                with session.db.with_lock():
                    self._execute_undo(session, snap)
                    session.db.modified = True
            except Exception as e:
                session.undo_stack.append(snap)
                return {"success": False, "message": f"Undo failed: {str(e)}"}

            # 成功：此时才将 snap 转移到 redo_stack
            session.redo_stack.append(snap)

            return {
                "success": True,
                "message": "Undo successful",
                "data": {
                    "undo_count": len(session.undo_stack),
                    "redo_count": len(session.redo_stack),
                }
            }

    def redo(self, session) -> dict:
        """执行重做操作。"""
        with session._undo_lock:
            if not session.redo_stack:
                return {"success": False, "message": "No operation to redo"}

            snap = session.redo_stack.pop()

            try:
                with session.db.with_lock():
                    self._execute_redo(session, snap)
                    session.db.modified = True
            except Exception as e:
                session.redo_stack.append(snap)
                return {"success": False, "message": f"Redo failed: {str(e)}"}

            # 成功：此时才将 snap 转移到 undo_stack
            session.undo_stack.append(snap)

            return {
                "success": True,
                "message": "Redo successful",
                "data": {
                    "undo_count": len(session.undo_stack),
                    "redo_count": len(session.redo_stack),
                }
            }

    # ── 孤儿栈管理 ──

    def save_orphan(self, file_name: str, session):
        """保存会话的撤销栈为孤儿栈（会话销毁时调用）。"""
        with session._undo_lock:
            self._orphan_stacks[file_name] = {
                "undo_stack": list(session.undo_stack),
                "redo_stack": list(session.redo_stack),
            }
        # LRU 淘汰
        while len(self._orphan_stacks) > self._max_orphan_stacks:
            oldest_key = next(iter(self._orphan_stacks))
            self._orphan_stacks.pop(oldest_key)
            logger.debug("Orphan undo stack evicted: %s", oldest_key)

    def restore_orphan(self, file_name: str, session):
        """恢复孤儿栈到会话（会话恢复时调用）。"""
        orphan = self._orphan_stacks.pop(file_name, None)
        if orphan:
            session.undo_stack = orphan["undo_stack"]
            session.redo_stack = orphan["redo_stack"]

    def remove_orphan(self, file_name: str):
        """删除孤儿栈（文件删除时调用）。"""
        self._orphan_stacks.pop(file_name, None)

    # ── 撤销/重做执行逻辑（策略模式） ──

    def _execute_undo(self, session, snap: dict):
        """执行撤销操作（根据 type 分发到不同处理器）。"""
        snap_type = snap.get("type")

        if snap_type == "message_delete":
            self._restore_message(session, snap["data"])
        elif snap_type == "signal_delete":
            self._restore_signal(session, snap["msgKey"], snap["data"])
        elif snap_type == "message_update":
            self._restore_message_update(session, snap["msgKey"], snap, "prev")
        elif snap_type == "signal_update":
            self._restore_signal_update(session, snap["msgKey"], snap, "prev")
        elif snap_type == "message_add":
            self._delete_message(session, snap["msgKey"])
        elif snap_type == "signal_add":
            self._delete_signal(session, snap["msgKey"], snap["sigName"])
        elif snap_type == "batch_signal_add":
            for sig in snap["signals"]:
                self._delete_signal(session, snap["msgKey"], sig["name"])
        elif snap_type == "batch_signal_update":
            # prev: {sigName: {field: old_val}, ...}, next: {field: value}
            self._restore_batch_signal_update(session, snap["msgKey"], snap, "prev")
        elif snap_type == "batch_message_update":
            # prev: [{msgKey: key, field: old_val}, ...], next: {field: value}
            self._restore_batch_message_update(session, snap, "prev")
        elif snap_type == "batch_signal_delete":
            # signals: [{name, data: sig.to_dict()}, ...]
            for sig in snap["signals"]:
                self._restore_signal(session, snap["msgKey"], sig["data"])
        elif snap_type == "batch_message_delete":
            # messages: [msg.to_dict(), ...]
            for msg_data in snap["messages"]:
                self._restore_message(session, msg_data)
        elif snap_type == "database_update":
            self._restore_database_update(session, snap["prev"])
        elif snap_type == "value_table_add":
            session.db.value_tables.pop(snap["name"], None)
        elif snap_type == "value_table_remove":
            session.db.value_tables[snap["name"]] = dict(snap["entries"])
        elif snap_type == "value_table_update":
            session.db.value_tables[snap["name"]] = dict(snap["prev"])
        elif snap_type == "value_table_rename":
            old_name, new_name = snap["old_name"], snap["new_name"]
            if new_name in session.db.value_tables:
                session.db.value_tables[old_name] = session.db.value_tables.pop(new_name)
                self._cascade_rename_value_table(session.db, new_name, old_name)
        else:
            raise ValueError(f"Unknown undo type: {snap_type}")

    def _execute_redo(self, session, snap: dict):
        """执行重做操作（撤销的逆操作）。"""
        snap_type = snap.get("type")

        if snap_type == "message_delete":
            self._delete_message(session, snap["data"].get("key", ""))
        elif snap_type == "signal_delete":
            self._delete_signal(session, snap["msgKey"], snap["data"]["name"])
        elif snap_type == "message_update":
            self._restore_message_update(session, snap["msgKey"], snap, "next")
        elif snap_type == "signal_update":
            self._restore_signal_update(session, snap["msgKey"], snap, "next")
        elif snap_type == "message_add":
            self._restore_message(session, snap["data"])
        elif snap_type == "signal_add":
            self._restore_signal(session, snap["msgKey"], snap["data"])
        elif snap_type == "batch_signal_add":
            for sig in snap["signals"]:
                self._restore_signal(session, snap["msgKey"], sig["data"])
        elif snap_type == "batch_signal_update":
            # undo 的逆操作：用 next 重新应用变更
            self._restore_batch_signal_update(session, snap["msgKey"], snap, "next")
        elif snap_type == "batch_message_update":
            self._restore_batch_message_update(session, snap, "next")
        elif snap_type == "batch_signal_delete":
            for sig in snap["signals"]:
                self._delete_signal(session, snap["msgKey"], sig["name"])
        elif snap_type == "batch_message_delete":
            for msg_data in snap["messages"]:
                self._delete_message(session, msg_data.get("key", ""))
        elif snap_type == "database_update":
            self._restore_database_update(session, snap["next"])
        elif snap_type == "value_table_add":
            session.db.value_tables[snap["name"]] = dict(snap["entries"])
        elif snap_type == "value_table_remove":
            session.db.value_tables.pop(snap["name"], None)
        elif snap_type == "value_table_update":
            session.db.value_tables[snap["name"]] = dict(snap["next"])
        elif snap_type == "value_table_rename":
            old_name, new_name = snap["old_name"], snap["new_name"]
            if old_name in session.db.value_tables:
                session.db.value_tables[new_name] = session.db.value_tables.pop(old_name)
                self._cascade_rename_value_table(session.db, old_name, new_name)
        else:
            raise ValueError(f"Unknown redo type: {snap_type}")

    # ── 撤销/重做辅助方法 ──

    @staticmethod
    def _cascade_rename_value_table(db, from_name: str, to_name: str):
        """级联更新所有引用 from_name 的信号为 to_name。"""
        for m in db.messages.values():
            for s in m.signals.values():
                if s.value_table_name == from_name:
                    s.value_table_name = to_name

    def _restore_message(self, session, msg_data: dict):
        """恢复报文（含所有信号）。"""
        from app.models import Message

        msg = Message.from_dict(msg_data)
        session.db.messages[msg.key] = msg

    def _restore_signal(self, session, msg_key: str, sig_data: dict):
        """恢复信号。"""
        from app.models import Signal
        msg = session.db.messages.get(msg_key)
        if not msg:
            raise ValueError(f"Message {msg_key} not found")

        sig = Signal.from_dict(sig_data)
        msg.signals[sig.name] = sig

    def _restore_message_update(self, session, msg_key: str, snap: dict, direction: str):
        """恢复报文属性更新（含 key 变更）。

        Args:
            session: 当前会话
            msg_key: 快照中的报文 key（操作后的 key）
            snap: 完整快照，含 prevKey/nextKey 和 prev/next
            direction: "prev"（undo）或 "next"（redo）
        """
        from app.models.can_id import parse_key

        if direction == "prev":
            source_key = snap.get("nextKey", msg_key)
            target_key = snap.get("prevKey", source_key)
        else:
            source_key = snap.get("prevKey", msg_key)
            target_key = snap.get("nextKey", source_key)

        msg = session.db.messages.get(source_key)
        if msg is None:
            msg = session.db.messages.get(msg_key)
        if msg is None:
            raise ValueError(f"Message {msg_key} not found")

        if msg.key != target_key:
            can_id, is_extended = parse_key(target_key)
            moved = session.db.move_message(msg.key, can_id, is_extended)
            if moved is None:
                raise ValueError(
                    f"Cannot move message {msg.key} to {target_key}"
                )
            msg = session.db.messages[moved]

        for field, value in snap[direction].items():
            if field in ("id", "is_extended_frame", "key", "can_id"):
                continue  # move_message 已处理身份
            if hasattr(msg, field):
                setattr(msg, field, value)

    @staticmethod
    def _apply_signal_field(sig, field: str, value):
        """写入信号字段；value_type 统一恢复为枚举。"""
        if field == "value_type":
            from app.models.signal import SignalValueType
            value = SignalValueType(value)
        setattr(sig, field, value)

    def _restore_signal_update(self, session, msg_key: str, snap: dict, direction: str):
        """恢复信号属性更新。支持重命名回退。

        Args:
            snap: 完整快照，含 sigName / prev / next
            direction: "prev"（undo）或 "next"（redo）
        """
        msg = session.db.messages.get(msg_key)
        if not msg:
            raise ValueError(f"Message {msg_key} not found")

        updates = snap[direction]
        other_dir = "next" if direction == "prev" else "prev"
        sig_name = snap["sigName"]

        # 查找信号：sig_name 是快照时的名字，重命名后可能已失效
        sig = msg.signals.get(sig_name)
        if not sig:
            # 重命名场景：用反方向的 name 定位当前信号
            other_name = snap[other_dir].get("name")
            if other_name:
                sig = msg.signals.get(other_name)
        if not sig:
            raise ValueError(f"Signal {sig_name} not found")

        # 应用 updates 中的字段值
        new_name = updates.get("name")
        if new_name is not None and new_name != sig.name:
            # 重命名：更新 sig.name 和 dict key
            old_key = sig.name
            sig.name = new_name
            if old_key in msg.signals:
                del msg.signals[old_key]
            msg.signals[new_name] = sig

        for key, value in updates.items():
            if key == "name":
                continue  # 已在上面处理
            if hasattr(sig, key):
                self._apply_signal_field(sig, key, value)

    def _restore_batch_signal_update(self, session, msg_key: str, snap: dict, direction: str):
        """恢复批量信号属性更新。

        Args:
            snap: 完整快照，含 prev ({sigName: {field: old_val}}) / next ({field: value})
            direction: "prev"（undo）或 "next"（redo）
        """
        msg = session.db.messages.get(msg_key)
        if not msg:
            raise ValueError(f"Message {msg_key} not found")

        if direction == "prev":
            # undo: prev 是 {sigName: {field: old_val}, ...}，逐个恢复
            for sig_name, field_vals in snap["prev"].items():
                sig = msg.signals.get(sig_name)
                if not sig:
                    continue
                for field, value in field_vals.items():
                    if hasattr(sig, field):
                        self._apply_signal_field(sig, field, value)
        else:
            # redo: next 是 {field: value}，对所有在 prev 中的信号应用
            fields = snap["next"]
            for sig_name in snap["prev"]:
                sig = msg.signals.get(sig_name)
                if not sig:
                    continue
                for field, value in fields.items():
                    if hasattr(sig, field):
                        self._apply_signal_field(sig, field, value)

    def _restore_batch_message_update(self, session, snap: dict, direction: str):
        """恢复批量报文属性更新。

        Args:
            snap: 完整快照，含 prev ([{msgKey, field: old_val}, ...]) / next ({field: value})
            direction: "prev"（undo）或 "next"（redo）
        """
        if direction == "prev":
            # undo: prev 中每条含 msgKey + 旧值
            for entry in snap["prev"]:
                msg_key = entry["msgKey"]
                msg = session.db.messages.get(msg_key)
                if not msg:
                    continue
                for field, value in entry.items():
                    if field == "msgKey":
                        continue
                    if hasattr(msg, field):
                        setattr(msg, field, value)
        else:
            # redo: next 是 {field: value}，对所有在 prev 中的报文应用
            fields = snap["next"]
            for entry in snap["prev"]:
                msg_key = entry["msgKey"]
                msg = session.db.messages.get(msg_key)
                if not msg:
                    continue
                for field, value in fields.items():
                    if hasattr(msg, field):
                        setattr(msg, field, value)

    def _restore_database_update(self, session, updates: dict):
        """恢复数据库级属性更新。"""
        db = session.db
        for key, value in updates.items():
            if hasattr(db, key):
                setattr(db, key, value)

    def _delete_message(self, session, msg_key: str):
        """删除报文。"""
        session.db.messages.pop(msg_key, None)

    def _delete_signal(self, session, msg_key: str, sig_name: str):
        """删除信号。"""
        msg = session.db.messages.get(msg_key)
        if not msg:
            raise ValueError(f"Message {msg_key} not found")

        msg.signals.pop(sig_name, None)
