"""
UndoEngine — 撤销/重做引擎。

从 SessionManager 提取的独立模块，管理撤销/重做栈和孤儿栈。
所有公共方法接受 Session 对象（而非 session_id），不依赖 SessionManager。
"""

import json

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
            except (TypeError, ValueError):
                snap_copy = dict(snapshot)  # 浅拷贝回退

            session.undo_stack.append(snap_copy)

            # 限制栈大小
            if len(session.undo_stack) > session.MAX_UNDO_SIZE:
                session.undo_stack.pop(0)  # 移除最早的记录

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

    def clear_stacks(self, session) -> bool:
        """清空撤销/重做栈。"""
        with session._undo_lock:
            session.undo_stack.clear()
            session.redo_stack.clear()
            return True

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
            self._restore_signal(session, snap["msgId"], snap["data"])
        elif snap_type == "message_update":
            self._restore_message_update(session, snap["msgId"], snap, "prev")
        elif snap_type == "signal_update":
            self._restore_signal_update(session, snap["msgId"], snap["sigUuid"], snap["prev"])
        elif snap_type == "message_add":
            self._delete_message(session, snap["msgId"])
        elif snap_type == "signal_add":
            self._delete_signal(session, snap["msgId"], snap["sigUuid"])
        elif snap_type == "batch_signal_add":
            for sig in snap["signals"]:
                self._delete_signal(session, snap["msgId"], sig["uuid"])
        else:
            raise ValueError(f"Unknown undo type: {snap_type}")

    def _execute_redo(self, session, snap: dict):
        """执行重做操作（撤销的逆操作）。"""
        snap_type = snap.get("type")

        if snap_type == "message_delete":
            self._delete_message(session, snap["data"]["id"])
        elif snap_type == "signal_delete":
            self._delete_signal(session, snap["msgId"], snap["data"]["uuid"])
        elif snap_type == "message_update":
            self._restore_message_update(session, snap["msgId"], snap, "next")
        elif snap_type == "signal_update":
            self._restore_signal_update(session, snap["msgId"], snap["sigUuid"], snap["next"])
        elif snap_type == "message_add":
            self._restore_message(session, snap["data"])
        elif snap_type == "signal_add":
            self._restore_signal(session, snap["msgId"], snap["data"])
        elif snap_type == "batch_signal_add":
            for sig in snap["signals"]:
                self._restore_signal(session, snap["msgId"], sig["data"])
        else:
            raise ValueError(f"Unknown redo type: {snap_type}")

    # ── 撤销/重做辅助方法 ──

    def _restore_message(self, session, msg_data: dict):
        """恢复报文（含所有信号）。"""
        from app.models import Signal, Message

        msg_id = msg_data["id"]
        signals = []
        for sig_data in msg_data.get("signals", []):
            if isinstance(sig_data, dict):
                sig = Signal.from_dict(sig_data)
            else:
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

    def _restore_signal(self, session, msg_id: int, sig_data: dict):
        """恢复信号。"""
        from app.models import Signal
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")

        sig = Signal.from_dict(sig_data)
        msg.signals.append(sig)

    def _restore_message_update(self, session, msg_id: int, snap: dict, direction: str):
        """恢复报文属性更新（含 ID 变更）。

        Args:
            session: 当前会话
            msg_id: 快照中的 msgId（消息在操作后的 ID）
            snap: 完整快照，含 prev/next 和可选的 id 变更
            direction: "prev"（undo）或 "next"（redo）
        """
        updates = snap[direction]
        other_dir = "next" if direction == "prev" else "prev"
        target_id = updates.get("id")

        if target_id is not None:
            # 含 ID 变更：source_id 来自快照的另一方向
            source_id = snap[other_dir].get("id", msg_id)
            msg = session.db.messages.get(source_id)
            if not msg:
                raise ValueError(f"Message 0x{source_id:X} not found")
            current_id = msg.id
            if target_id != current_id:
                if not session.db.move_message(current_id, target_id):
                    raise ValueError(f"Cannot move message 0x{current_id:X} to 0x{target_id:X}")
                msg = session.db.messages[target_id]
        else:
            # 无 ID 变更：标准属性恢复
            msg = session.db.messages.get(msg_id)
            if not msg:
                raise ValueError(f"Message {msg_id} not found")

        for key, value in updates.items():
            if key == "id":
                continue  # move_message 已处理 msg.id
            if hasattr(msg, key):
                setattr(msg, key, value)

    def _restore_signal_update(self, session, msg_id: int, sig_uuid: str, updates: dict):
        """恢复信号属性更新。"""
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")

        sig = next((s for s in msg.signals if s.uuid == sig_uuid), None)
        if not sig:
            raise ValueError(f"Signal {sig_uuid} not found")

        for key, value in updates.items():
            if hasattr(sig, key):
                setattr(sig, key, value)

    def _delete_message(self, session, msg_id: int):
        """删除报文。"""
        session.db.messages.pop(msg_id, None)

    def _delete_signal(self, session, msg_id: int, sig_uuid: str):
        """删除信号。"""
        msg = session.db.messages.get(msg_id)
        if not msg:
            raise ValueError(f"Message {msg_id} not found")

        # ✅ 原地修改，保持列表引用不变
        msg.signals[:] = [s for s in msg.signals if s.uuid != sig_uuid]
