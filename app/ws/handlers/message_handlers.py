"""
message_handlers.py — 报文相关 WS Handler

EditMessage / AddMessage / DeleteMessage / DuplicateMessage / GetMessage / GetMessages
"""
from __future__ import annotations

from app.models import Message
from app.services import FileNameExistsError
from app.ws.router import HandlerResult, HandlerError


def _parse_id(s) -> int | None:
    """解析报文 ID。仅接受 int 或十进制整数字符串。"""
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        try:
            return int(s.strip())
        except ValueError:
            return None
    return None


class EditMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]
        original_msg_id = msg_id
        fields = data.get("fields", {})

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            ok, err, info = db.validate_message_fields(msg_id, fields)
            if not ok:
                raise HandlerError("VALUE_INVALID", err, info)
            old_values = {}
            for key in fields:
                if key != "id" and hasattr(msg, key):
                    old_values[key] = getattr(msg, key)
            new_id = _parse_id(fields.get("id", msg_id))
            if new_id is None:
                raise HandlerError("VALUE_INVALID", "Invalid new ID")
            if new_id != msg_id:
                if not db.move_message(msg_id, new_id):
                    raise HandlerError("CONFLICT", f"报文 0x{new_id:X} 已存在")
                msg_id = new_id
            db.update_message(msg_id, **{k: v for k, v in fields.items() if k != "id"})
            if old_values or new_id != original_msg_id:
                prev = dict(old_values)
                nxt = {k: v for k, v in fields.items() if k != "id"}
                if new_id != original_msg_id:
                    prev["id"] = original_msg_id
                    nxt["id"] = new_id
                self._sm.push_undo(sid, {"type": "message_update", "msgId": msg_id,
                                         "prev": prev, "next": nxt})
            new_version = db._bump_version()
            updated_msg = db.get_message(msg_id)
            evt_data = {"message": {
                "id": msg_id, "id_hex": f"0x{msg_id:X}", "name": updated_msg.name,
                "dlc": updated_msg.dlc, "cycle_time": updated_msg.cycle_time,
                "sender": updated_msg.sender, "comment": updated_msg.comment,
                "signal_count": len(updated_msg.signals)}}
            if new_id != original_msg_id:
                evt_data["old_id"] = original_msg_id
            events = [
                {"type": "message_updated", "data": evt_data,
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            # 仅 DLC 变更会影响信号位布局（越界/重叠），其他字段(name/sender/comment/cycle_time)无影响
            if 'dlc' in fields:
                errs = db.validate_all_signals(msg_id)
                events.append({"type": "signal_errors_changed",
                               "data": {"msg_id": msg_id, "errors": errs},
                               "data_version": new_version})
            return HandlerResult(data=updated_msg.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)


class AddMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_data = data.get("message", data)

        db = session.db
        with db.with_lock():
            msg_id = _parse_id(msg_data.get("id", ""))
            if msg_id is None:
                raise HandlerError("VALUE_INVALID", "Invalid or missing message ID")
            if "name" in msg_data:
                name = msg_data["name"]
                if not isinstance(name, str) or not name.strip():
                    raise HandlerError("VALUE_INVALID", "Message name cannot be empty",
                                       {"error_code": "message_name_empty", "field": "name"})
            if "dlc" in msg_data:
                dlc = msg_data["dlc"]
                if dlc is None or not isinstance(dlc, (int, float)):
                    raise HandlerError("VALUE_INVALID", "Invalid DLC value",
                                       {"error_code": "dlc_invalid", "field": "dlc"})
                dlc_int = int(dlc)
                if dlc_int not in db.VALID_DLC_VALUES:
                    raise HandlerError("VALUE_INVALID", f"Invalid DLC",
                                       {"error_code": "dlc_invalid", "field": "dlc",
                                        "valid_values": sorted(db.VALID_DLC_VALUES)})
            msg = Message.from_dict(msg_data)
            msg.id = msg_id
            if not db.add_message(msg):
                raise HandlerError("CONFLICT", f"报文 0x{msg_id:X} 已存在")
            self._sm.push_undo(sid, {"type": "message_add", "msgId": msg_id, "data": msg.to_dict()})
            new_version = db._bump_version()
            summary = {"id": msg_id, "id_hex": f"0x{msg_id:X}", "name": msg.name,
                       "dlc": msg.dlc, "cycle_time": msg.cycle_time,
                       "sender": msg.sender, "comment": msg.comment,
                       "signal_count": len(msg.signals)}
            events = [
                {"type": "message_added", "data": {"message": summary}, "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            return HandlerResult(data=msg.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)


class DeleteMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            msg_data = msg.to_dict()
            db.remove_message(msg_id)
            self._sm.push_undo(sid, {"type": "message_delete", "data": msg_data})
            new_version = db._bump_version()
            events = [
                {"type": "message_deleted", "data": {"msg_id": msg_id}, "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            return HandlerResult(data={"deleted": f"0x{msg_id:X}"}, events=events,
                                 new_version=new_version, session_id=sid)


class DuplicateMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]
        new_id = data.get("new_id")

        db = session.db
        with db.with_lock():
            orig = db.messages.get(msg_id)
            if not orig:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            if new_id is None:
                max_id = max(db.messages.keys()) if db.messages else 0
                new_id = max_id + 0x10
            new_name = orig.name + "_copy"
            msg_data = orig.to_dict()
            msg_data["id"] = new_id
            msg_data["name"] = new_name
            msg = Message.from_dict(msg_data)
            msg.id = new_id
            if not db.add_message(msg):
                raise HandlerError("CONFLICT", f"报文 0x{new_id:X} 已存在")
            self._sm.push_undo(sid, {"type": "message_add", "msgId": new_id, "data": msg.to_dict()})
            new_version = db._bump_version()
            summary = {"id": new_id, "id_hex": f"0x{new_id:X}", "name": msg.name,
                       "dlc": msg.dlc, "cycle_time": msg.cycle_time,
                       "sender": msg.sender, "comment": msg.comment,
                       "signal_count": len(msg.signals)}
            events = [
                {"type": "message_added", "data": {"message": summary}, "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            return HandlerResult(data=msg.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)


class GetMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = _parse_id(data.get("msg_id", ""))
        if msg_id is None:
            raise HandlerError("VALUE_INVALID", "Invalid message ID")
        msg = db.get_message(msg_id)
        if not msg:
            raise HandlerError("MESSAGE_NOT_FOUND", f"报文 0x{msg_id:X} 不存在")
        return HandlerResult(data=msg.to_dict(), session_id=sid)


class GetMessagesHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        with db.with_lock():
            messages = [
                {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
                 "dlc": m.dlc, "cycle_time": m.cycle_time, "signal_count": len(m.signals)}
                for mid, m in sorted(db.messages.items())
            ]
        return HandlerResult(data=messages, session_id=sid)
