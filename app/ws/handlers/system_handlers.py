"""
system_handlers.py — 系统级 WS Handler

Undo / Redo / ReleaseLock / StealLock / GetSummary / GetSessionInfo / GetStatus / GetSnapshotDebug
"""

import json
import os

from app.ws.router import HandlerResult, HandlerError
from ._common import pure_file_name as _pure_file_name


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
            result = self._sm.undo(sid)
            if not result["success"]:
                raise HandlerError("UNDO_FAILED", result.get("message", "撤销失败"))

            messages_data = [
                {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
                 "dlc": m.dlc, "cycle_time": m.cycle_time, "signal_count": len(m.signals)}
                for mid, m in sorted(db.messages.items())
            ]
            message_details = {str(mid): m.to_dict() for mid, m in db.messages.items()}
            new_version = db._bump_version()

        events = [{
            "type": "undo_applied",
            "data": {
                "messages": messages_data,
                "message_details": message_details,
                "status": {"modified": db.modified,
                           "undo_count": len(session.undo_stack),
                           "redo_count": len(session.redo_stack)},
            },
            "data_version": new_version,
        }]
        return HandlerResult(data={"undo_count": len(session.undo_stack),
                                   "redo_count": len(session.redo_stack)},
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
            result = self._sm.redo(sid)
            if not result["success"]:
                raise HandlerError("REDO_FAILED", result.get("message", "重做失败"))

            messages_data = [
                {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
                 "dlc": m.dlc, "cycle_time": m.cycle_time, "signal_count": len(m.signals)}
                for mid, m in sorted(db.messages.items())
            ]
            message_details = {str(mid): m.to_dict() for mid, m in db.messages.items()}
            new_version = db._bump_version()

        events = [{
            "type": "redo_applied",
            "data": {
                "messages": messages_data,
                "message_details": message_details,
                "status": {"modified": db.modified,
                           "undo_count": len(session.undo_stack),
                           "redo_count": len(session.redo_stack)},
            },
            "data_version": new_version,
        }]
        return HandlerResult(data={"undo_count": len(session.undo_stack),
                                   "redo_count": len(session.redo_stack)},
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
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        with db.with_lock():
            msgs = list(db.messages.values())
            data = {
                "name": db.name, "message_count": len(msgs),
                "signal_count": db.total_signals(), "modified": db.modified,
                "messages": [{"id": m.id, "id_hex": f"0x{m.id:X}", "name": m.name,
                              "dlc": m.dlc, "signal_count": len(m.signals)}
                             for m in sorted(msgs, key=lambda m: m.id)],
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
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        with db.with_lock():
            status_data = {
                "message_count": len(db.messages), "signal_count": db.total_signals(),
                "modified": db.modified, "session_id": sid,
                "file_name": _pure_file_name(session) if session else None,
            }
        if session:
            status_data["undo_count"] = len(session.undo_stack)
            status_data["redo_count"] = len(session.redo_stack)
            status_data["save_error"] = session.save_error
        return HandlerResult(data=status_data, session_id=sid)


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
