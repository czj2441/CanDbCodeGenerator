"""
message_handlers.py — 报文相关 WS Handler

EditMessage / AddMessage / DeleteMessage / GetMessage / GetMessages / BatchEditMessages / BatchDeleteMessages
"""
from __future__ import annotations

from app.models import Message
from app.models.can_id import CanIdError
from app.ws.router import HandlerResult, HandlerError
from ._common import (
    build_messages_summary,
    parse_msg_key,
    push_data_errors,
    _single_message_summary,
)


def _parse_id(value) -> int | None:
    """解析原始 CAN ID（int / 十进制或 0x 字符串）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip(), 0)
        except ValueError:
            return None
    return None


def _request_msg_keys(data: dict) -> list[str]:
    """读取批量请求中的报文 key 列表，兼容旧 ``msg_ids``。"""
    raw = data.get("msg_keys")
    if raw is None:
        raw = data.get("msg_ids", [])
    return [parse_msg_key(v) for v in raw]


class EditMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        original_key = parse_msg_key(data.get("msg_key", data.get("msg_id")))
        fields = data.get("fields", {})

        db = session.db
        with db.with_lock():
            msg = db.messages.get(original_key)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {original_key} 不存在")
            ok, err, info = db.validate_message_fields(original_key, fields)
            if not ok:
                raise HandlerError("VALUE_INVALID", err, info)

            old_values = {}
            for key in fields:
                if key not in ("id", "is_extended_frame") and hasattr(msg, key):
                    old_values[key] = getattr(msg, key)

            target_id = _parse_id(fields.get("id", msg.can_id))
            if target_id is None:
                raise HandlerError("VALUE_INVALID", "Invalid new ID")
            target_ext = fields.get("is_extended_frame", msg.is_extended_frame)
            if not isinstance(target_ext, bool):
                raise HandlerError("VALUE_INVALID", "is_extended_frame must be a boolean")

            new_key = original_key
            if target_id != msg.can_id or target_ext != msg.is_extended_frame:
                moved = db.move_message(original_key, target_id, target_ext)
                if moved is None:
                    raise HandlerError(
                        "CONFLICT",
                        f"报文 0x{target_id:X}"
                        f"{':ext' if target_ext else ':std'} 已存在",
                    )
                new_key = moved

            db.update_message(
                new_key,
                **{k: v for k, v in fields.items()
                   if k not in ("id", "is_extended_frame")},
            )

            if old_values or new_key != original_key:
                prev = dict(old_values)
                nxt = {k: v for k, v in fields.items()
                       if k not in ("id", "is_extended_frame")}
                self._sm.push_undo(session, {
                    "type": "message_update",
                    "msgKey": new_key,
                    "prevKey": original_key,
                    "nextKey": new_key,
                    "prev": prev,
                    "next": nxt,
                })

            new_version = db._bump_version()
            updated_msg = db.get_message(new_key)
            evt_data = {"message": _single_message_summary(updated_msg)}
            if new_key != original_key:
                evt_data["old_key"] = original_key
            events = [
                {"type": "message_updated", "data": evt_data,
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {original_key, new_key})
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
                    raise HandlerError("VALUE_INVALID", "Invalid DLC",
                                       {"error_code": "dlc_invalid", "field": "dlc",
                                        "valid_values": sorted(db.VALID_DLC_VALUES)})
            if not msg_data.get("key") and msg_data.get("id") in (None, ""):
                raise HandlerError(
                    "VALUE_INVALID",
                    "Message ID or key is required",
                    {"error_code": "message_id_required", "field": "id"},
                )
            try:
                msg = Message.from_dict(msg_data)
            except (CanIdError, ValueError, TypeError) as e:
                raise HandlerError("VALUE_INVALID", f"Invalid message: {e}")
            if not db.add_message(msg):
                raise HandlerError(
                    "CONFLICT",
                    f"报文 {msg.key} 已存在",
                )
            self._sm.push_undo(session, {
                "type": "message_add", "msgKey": msg.key, "data": msg.to_dict(),
            })
            new_version = db._bump_version()
            summary = _single_message_summary(msg)
            events = [
                {"type": "message_added", "data": {"message": summary}, "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {msg.key})
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
        msg_key = parse_msg_key(data.get("msg_key", data.get("msg_id")))

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_key)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_key} 不存在")
            msg_data = msg.to_dict()
            db.remove_message(msg_key)
            self._sm.push_undo(session, {"type": "message_delete", "data": msg_data})
            new_version = db._bump_version()
            events = [
                {"type": "message_deleted", "data": {"msg_key": msg_key}, "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            # 报文已从 dict 消失，必须全量扫描
            integrity_errors = db.full_validate()
            events.append({"type": "data_errors_changed",
                           "data": {"errors": integrity_errors},
                           "data_version": new_version})
            return HandlerResult(data={"deleted": msg_key}, events=events,
                                 new_version=new_version, session_id=sid)


class GetMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        db = session.db
        try:
            msg_key = parse_msg_key(data.get("msg_key", data.get("msg_id")))
        except HandlerError:
            msg_key = None
        msg = db.get_message(msg_key) if msg_key is not None else None
        if not msg:
            label = msg_key or str(data.get("msg_key", data.get("msg_id", "")))
            raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {label} 不存在")
        return HandlerResult(data=msg.to_dict(), session_id=sid)


class GetMessagesHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        db = session.db
        with db.with_lock():
            messages = build_messages_summary(db)
        return HandlerResult(data=messages, session_id=sid)


# 批量编辑时禁止的字段（唯一标识字段）
_BATCH_EDIT_FORBIDDEN_FIELDS = {'id', 'is_extended_frame', 'key', 'name'}


class BatchEditMessagesHandler:
    """批量编辑多个报文的指定字段。

    请求格式: { session_id, msg_keys: [str], fields: { field: value } }
    兼容旧 ``msg_ids: [int]``。
    """
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        msg_keys = _request_msg_keys(data)
        fields = data.get("fields", {})

        if not msg_keys:
            raise HandlerError("VALUE_INVALID", "msg_keys 不能为空")
        if not fields:
            raise HandlerError("VALUE_INVALID", "fields 不能为空")

        for field in fields:
            if field in _BATCH_EDIT_FORBIDDEN_FIELDS:
                raise HandlerError("FIELD_NOT_EDITABLE",
                                   f"字段 {field} 不允许批量编辑",
                                   {"field": field})

        db = session.db
        with db.with_lock():
            prev = []   # [{msgKey: key, field: old_value, ...}, ...]
            updated_msgs = []
            errors = []

            for msg_key in msg_keys:
                msg = db.messages.get(msg_key)
                if not msg:
                    errors.append({"msg_key": msg_key, "error": "报文不存在"})
                    continue

                old_vals = {"msgKey": msg_key}
                for field in fields:
                    if hasattr(msg, field):
                        old_vals[field] = getattr(msg, field)

                ok, err, info = db.validate_message_fields(msg_key, fields)
                if not ok:
                    errors.append({"msg_key": msg_key, "error": err})
                    continue

                db.update_message(msg_key, **fields)
                prev.append(old_vals)
                updated_msgs.append(db.get_message(msg_key))

            if not updated_msgs:
                raise HandlerError("VALUE_INVALID", "没有报文被更新",
                                   {"errors": errors})

            self._sm.push_undo(session, {
                "type": "batch_message_update",
                "prev": prev,
                "next": dict(fields),
            })

            new_version = db._bump_version()

            events = []
            for updated_msg in updated_msgs:
                summary = _single_message_summary(updated_msg)
                events.append({
                    "type": "message_updated",
                    "data": {"message": summary},
                    "data_version": new_version,
                })
            events.append({
                "type": "status_changed",
                "data": {"modified": True,
                         "undo_count": len(session.undo_stack),
                         "redo_count": len(session.redo_stack)},
                "data_version": new_version,
            })
            # 批量操作涉及多个报文，全量校验
            integrity_errors = db.full_validate()
            events.append({
                "type": "data_errors_changed",
                "data": {"errors": integrity_errors},
                "data_version": new_version,
            })

            return HandlerResult(
                data={"updated": len(updated_msgs), "errors": errors},
                events=events,
                new_version=new_version,
                session_id=sid,
            )


class BatchDeleteMessagesHandler:
    """批量删除多个报文。

    请求格式: { session_id, msg_keys: [str] }
    兼容旧 ``msg_ids: [int]``。
    """
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        msg_keys = _request_msg_keys(data)
        if not msg_keys:
            raise HandlerError("VALUE_INVALID", "msg_keys 不能为空")

        db = session.db
        with db.with_lock():
            deleted = []
            errors = []

            for msg_key in msg_keys:
                msg = db.messages.get(msg_key)
                if not msg:
                    errors.append({"msg_key": msg_key, "error": "报文不存在"})
                    continue
                msg_data = msg.to_dict()
                db.remove_message(msg_key)
                deleted.append(msg_data)

            if not deleted:
                raise HandlerError("VALUE_INVALID", "没有报文被删除",
                                   {"errors": errors})

            self._sm.push_undo(session, {
                "type": "batch_message_delete",
                "messages": deleted,
            })

            new_version = db._bump_version()

            events = []
            for msg_data in deleted:
                events.append({
                    "type": "message_deleted",
                    "data": {"msg_key": msg_data["key"]},
                    "data_version": new_version,
                })
            events.append({
                "type": "status_changed",
                "data": {"modified": True,
                         "undo_count": len(session.undo_stack),
                         "redo_count": len(session.redo_stack)},
                "data_version": new_version,
            })
            integrity_errors = db.full_validate()
            events.append({
                "type": "data_errors_changed",
                "data": {"errors": integrity_errors},
                "data_version": new_version,
            })

            return HandlerResult(
                data={"deleted": len(deleted), "errors": errors},
                events=events,
                new_version=new_version,
                session_id=sid,
            )