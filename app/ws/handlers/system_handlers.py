"""
system_handlers.py — 系统级 WS Handler

Undo / Redo / ReleaseLock / StealLock / GetSummary / GetSessionInfo / GetStatus / GetSnapshotDebug
"""

import json
import os

from app.ws.router import HandlerResult, HandlerError
from ._common import pure_file_name as _pure_file_name, build_undo_redo_events, build_messages_summary


def _build_action_desc(snap: dict) -> str:
    """根据撤销/重做快照生成操作描述。"""
    t = snap.get("type", "")
    try:
        if t == "message_add":
            msg_id = snap.get("msgId", 0)
            name = snap.get("data", {}).get("name", "")
            return f"添加报文 0x{msg_id:X} {name}"
        elif t == "message_delete":
            msg_id = snap.get("data", {}).get("id", 0)
            return f"删除报文 0x{msg_id:X}"
        elif t == "message_update":
            fields = ", ".join(k for k in snap.get("next", {}) if k != "id")
            return f"修改报文 {fields}"
        elif t == "signal_add":
            return f"添加信号 {snap.get('sigName', snap.get('data', {}).get('name', ''))}"
        elif t == "signal_delete":
            return f"删除信号 {snap.get('data', {}).get('name', '')}"
        elif t == "signal_update":
            sig = snap.get("sigName", "")
            fields = ", ".join(k for k in snap.get("next", {}) if k != "name")
            return f"修改信号 {sig}.{fields}"
        elif t == "batch_signal_add":
            count = len(snap.get("signals", []))
            return f"批量添加 {count} 个信号"
        elif t == "batch_signal_delete":
            count = len(snap.get("signals", []))
            return f"批量删除 {count} 个信号"
        elif t == "batch_signal_update":
            count = len(snap.get("prev", {}))
            return f"批量修改 {count} 个信号"
        elif t == "batch_message_update":
            count = len(snap.get("prev", []))
            return f"批量修改 {count} 个报文"
        elif t == "batch_message_delete":
            count = len(snap.get("messages", []))
            return f"批量删除 {count} 个报文"
        elif t == "database_update":
            return "修改数据库属性"
        elif t == "value_table_add":
            return f"新增值描述表 {snap.get('name', '')}"
        elif t == "value_table_remove":
            return f"删除值描述表 {snap.get('name', '')}"
        elif t == "value_table_update":
            return f"更新值描述表 {snap.get('name', '')}"
        elif t == "value_table_rename":
            return f"重命名值描述表 {snap.get('old_name', '')} → {snap.get('new_name', '')}"
        else:
            return "未知操作"
    except Exception:
        return "未知操作"


class UndoHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        db = session.db
        with db.with_lock():
            result = self._sm.undo(session)
            if not result["success"]:
                raise HandlerError("UNDO_FAILED", result.get("message", "撤销失败"))
            events, new_version, _ = build_undo_redo_events(session, db, "undo_applied")

        # undo 成功后，snap 已转移到 redo_stack 顶部
        snap = session.redo_stack[-1] if session.redo_stack else {}
        action_desc = _build_action_desc(snap)

        return HandlerResult(data={"undo_count": len(session.undo_stack),
                                   "redo_count": len(session.redo_stack),
                                   "action_desc": action_desc},
                             events=events, new_version=new_version, session_id=sid)


class RedoHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        db = session.db
        with db.with_lock():
            result = self._sm.redo(session)
            if not result["success"]:
                raise HandlerError("REDO_FAILED", result.get("message", "重做失败"))
            events, new_version, _ = build_undo_redo_events(session, db, "redo_applied")

        # redo 成功后，snap 已转移到 undo_stack 顶部
        snap = session.undo_stack[-1] if session.undo_stack else {}
        action_desc = _build_action_desc(snap)

        return HandlerResult(data={"undo_count": len(session.undo_stack),
                                   "redo_count": len(session.redo_stack),
                                   "action_desc": action_desc},
                             events=events, new_version=new_version, session_id=sid)


class ReleaseLockHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        abort = data.get("abort", False)
        if sid:
            self._sm.release_session(sid, abort=abort)
        return HandlerResult(data={"released": True}, session_id=sid)


class StealLockHandler:
    def __init__(self, session_mgr, transport=None):
        self._sm = session_mgr
        self._transport = transport

    def __call__(self, data: dict) -> HandlerResult:
        target_sid = data.get("target_session_id", "")
        if not target_sid:
            raise HandlerError("VALUE_INVALID", "target_session_id is required")
        target_session = self._sm.get(target_sid)
        if not target_session:
            raise HandlerError("SESSION_NOT_FOUND", "Target session not found")
        self._sm.release_session(target_sid)
        self._sm.fire_lock_released(target_sid)
        return HandlerResult(data={"released_session": target_sid},
                             session_id=data.get("current_session_id", ""))


class GetSummaryHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        db = session.db
        with db.with_lock():
            data = {
                "name": db.name, "bus_type": db.bus_type,
                "message_count": len(db.messages),
                "signal_count": db.total_signals(), "modified": db.modified,
                "messages": build_messages_summary(db),
            }
        return HandlerResult(data=data, session_id=sid)


class GetSessionInfoHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        s = self._sm.get(sid)
        if not s:
            raise HandlerError("SESSION_NOT_FOUND", "Session not found or expired")
        if self._sm.is_file_locked(s.file_path, exclude_session=sid):
            raise HandlerError("FILE_LOCKED", f"File '{_pure_file_name(s)}' is opened in another tab")
        return HandlerResult(data={
            "session_id": s.id, "file_name": _pure_file_name(s),
            "message_count": len(s.db.messages), "signal_count": s.db.total_signals(),
            "is_locked": False,
        }, session_id=sid)


class GetStatusHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        db = session.db
        with db.with_lock():
            status_data = {
                "message_count": len(db.messages), "signal_count": db.total_signals(),
                "modified": db.modified, "session_id": sid,
                "file_name": _pure_file_name(session),
            }
        status_data["undo_count"] = len(session.undo_stack)
        status_data["redo_count"] = len(session.redo_stack)
        status_data["save_error"] = session.save_error
        return HandlerResult(data=status_data, session_id=sid)


class EditDatabaseHandler:
    """修改数据库级属性（如 bus_type）。"""
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        fields = data.get("fields", {})
        db = session.db
        with db.with_lock():
            old_values = {}
            if "bus_type" in fields:
                bt = fields["bus_type"]
                if bt not in ("CAN", "CAN FD"):
                    raise HandlerError("VALUE_INVALID", "bus_type must be 'CAN' or 'CAN FD'")
                # CAN FD → CAN 时校验 DLC 和 is_fd：经典 CAN 仅支持 DLC 1-8 且不允许 CAN FD 报文
                if db.bus_type == "CAN FD" and bt == "CAN":
                    oversized = [m for m in db.messages.values() if m.dlc > 8]
                    fd_msgs = [m for m in db.messages.values() if m.is_fd]
                    if oversized or fd_msgs:
                        issues = []
                        if oversized:
                            names = ", ".join(m.name for m in oversized[:3])
                            issues.append(f"DLC > 8 的报文: {names}")
                        if fd_msgs:
                            fd_names = ", ".join(m.name for m in fd_msgs[:3])
                            issues.append(f"CAN FD 报文: {fd_names}")
                        raise HandlerError(
                            "CANFD_INCOMPATIBLE",
                            f"经典 CAN 不支持以下报文，请先修改：{'; '.join(issues)}",
                            {"bus_type": db.bus_type}
                        )
                old_values["bus_type"] = db.bus_type
                db.bus_type = bt
                db.modified = True
            if old_values:
                self._sm.push_undo(session, {
                    "type": "database_update",
                    "prev": old_values,
                    "next": fields,
                })
            new_version = db._bump_version()
            # bus_type 变更影响所有报文的 is_fd 兼容性，必须全量重验
            integrity_errors = db.full_validate()
        events = [
            {"type": "database_updated", "data": {"bus_type": db.bus_type},
             "data_version": new_version},
            {"type": "status_changed",
             "data": {"modified": True,
                      "undo_count": len(session.undo_stack),
                      "redo_count": len(session.redo_stack)},
             "data_version": new_version},
            {"type": "data_errors_changed", "data": {"errors": integrity_errors},
             "data_version": new_version},
        ]
        return HandlerResult(data={"bus_type": db.bus_type}, events=events,
                             new_version=new_version, session_id=sid)


class GetSnapshotDebugHandler:
    """返回快照系统的 debug 信息（内存状态 + 磁盘文件）。"""
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        from app.services.file_persistence import SNAPSHOT_DIR
        current_sid = data.get("session_id", "")

        # 内存中的快照候选（modified=True 的活跃 session）
        in_memory = []
        with self._sm._lock:
            for sid, session in self._sm._sessions.items():
                in_memory.append({
                    "session_id": sid,
                    "file_name": os.path.basename(session.file_path),
                    "modified": session.db.modified,
                    "message_count": len(session.db.messages),
                    "undo_count": len(session.undo_stack),
                    "redo_count": len(session.redo_stack),
                })

        # 磁盘上的快照文件
        on_disk = []
        if os.path.isdir(SNAPSHOT_DIR):
            for fname in os.listdir(SNAPSHOT_DIR):
                if not fname.endswith(".snapshot.json"):
                    continue
                path = os.path.join(SNAPSHOT_DIR, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        snap = json.load(f)
                    on_disk.append({
                        "session_id": snap.get("session_id", "?"),
                        "file_name": snap.get("file_name", "?"),
                        "snapshotted_at": snap.get("snapshotted_at", 0),
                        "size_bytes": os.path.getsize(path),
                        "db_name": snap.get("database", {}).get("name", "?"),
                        "message_count": len(snap.get("database", {}).get("messages", {})),
                    })
                except Exception:
                    on_disk.append({
                        "session_id": fname.replace(".snapshot.json", ""),
                        "file_name": "(parse error)",
                        "snapshotted_at": 0, "size_bytes": 0,
                    })

        return HandlerResult(data={
            "in_memory": in_memory,
            "on_disk": on_disk,
        }, session_id=current_sid)
