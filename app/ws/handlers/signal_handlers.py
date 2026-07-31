"""
signal_handlers.py — 信号相关 WS Handler

EditSignal / AddSignal / DeleteSignal / BatchAddSignals
"""
from __future__ import annotations

import math

from app.models import Signal
from app.ws.router import HandlerResult, HandlerError, EDITABLE_SIGNAL_FIELDS
from ._common import push_data_errors


def _validate_value_table_ref(db, value_table_name: str):
    """校验 value_table_name 引用是否存在。在 db.with_lock() 内调用。"""
    if value_table_name and value_table_name not in db.value_tables:
        raise HandlerError("VALUE_INVALID",
            f"值描述表 '{value_table_name}' 不存在",
            {"error_code": "value_table_not_found",
             "field": "value_table_name", "value": value_table_name})


def _validate_signal_fields(body: dict, msg, sig_uuid: str = None):
    """统一信号字段校验，供 add/edit/batch 复用。sig_uuid 非空时为编辑模式。"""
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip():
            raise HandlerError("VALUE_INVALID", "Signal name cannot be empty",
                               {"error_code": "signal_name_empty", "field": "name"})
        for existing in msg.signals:
            if existing.uuid != sig_uuid and existing.name == name.strip():
                raise HandlerError("VALUE_INVALID", f"Signal name '{name}' already exists",
                                   {"error_code": "signal_name_duplicate", "field": "name", "name": name})
    if "length" in body:
        length = body["length"]
        if length is None or not isinstance(length, (int, float)) or int(length) < 1:
            raise HandlerError("VALUE_INVALID", "Signal length must be at least 1",
                               {"error_code": "signal_length_invalid", "field": "length"})
    for num_field in ("factor", "offset", "min_val", "max_val"):
        if num_field in body:
            val = body[num_field]
            if val is None or not isinstance(val, (int, float)):
                raise HandlerError("VALUE_INVALID", f"Invalid {num_field} value",
                                   {"error_code": "invalid_number", "field": num_field})
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                raise HandlerError("VALUE_INVALID", f"{num_field} cannot be NaN or Infinity",
                                   {"error_code": "invalid_number", "field": num_field})
    # A2 已延后：factor==0 由 validate_data_integrity() 检测



class EditSignalHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        msg_id = data["msg_id"]
        sig_uuid = data["sig_uuid"]
        field = data["field"]
        value = data["value"]

        if field not in EDITABLE_SIGNAL_FIELDS:
            raise HandlerError("FIELD_NOT_EDITABLE", f"字段 {field} 不可编辑")

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            sig = next((s for s in msg.signals if s.uuid == sig_uuid), None)
            if not sig:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_uuid} 不存在")

            old_val = getattr(sig, field)

            try:
                _validate_signal_fields({field: value}, msg, sig_uuid)
            except HandlerError as e:
                if e.details is not None:
                    e.details[field] = old_val
                raise

            # value_table_name 引用校验
            if field == 'value_table_name':
                _validate_value_table_ref(db, value)

            test_sig = Signal.from_dict({**sig.to_dict(), field: value})
            ok, err, info = db.validate_signal(msg, test_sig, exclude_uuid=sig_uuid)
            if not ok:
                if info is None:
                    info = {}
                info[field] = old_val
                raise HandlerError("VALUE_INVALID", err, info)

            setattr(sig, field, value)
            db.modified = True
            self._sm.push_undo(session, {
                "type": "signal_update", "msgId": msg_id, "sigUuid": sig_uuid,
                "prev": {field: old_val}, "next": {field: value}
            })
            new_version = db._bump_version()
            events = [
                {"type": "signal_updated", "data": {"msg_id": msg_id, "signal": sig.to_dict()},
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {msg_id})
            return HandlerResult(data=sig.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)


class AddSignalHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]
        sig_data = data["signal"]

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            _validate_signal_fields(sig_data, msg)
            _validate_value_table_ref(db, sig_data.get("value_table_name", ""))
            sig = Signal.from_dict(sig_data)
            ok, err, info = db.validate_signal(msg, sig)
            if not ok:
                raise HandlerError("VALUE_INVALID", err, info)
            if not db.add_signal_to_message(msg_id, sig):
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            self._sm.push_undo(session, {"type": "signal_add", "msgId": msg_id,
                                     "sigUuid": sig.uuid, "data": sig.to_dict()})
            new_version = db._bump_version()
            events = [
                {"type": "signal_added", "data": {"msg_id": msg_id, "signal": sig.to_dict()},
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {msg_id})
            return HandlerResult(data=sig.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)


class DeleteSignalHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]
        sig_uuid = data["sig_uuid"]

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            sig = next((s for s in msg.signals if s.uuid == sig_uuid), None)
            if not sig:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_uuid} 不存在")
            sig_data = sig.to_dict()
            if not db.remove_signal_from_message(msg_id, sig_uuid):
                raise HandlerError("SIGNAL_NOT_FOUND", "删除失败")
            self._sm.push_undo(session, {"type": "signal_delete", "msgId": msg_id, "data": sig_data})
            new_version = db._bump_version()
            events = [
                {"type": "signal_deleted", "data": {"msg_id": msg_id, "signal_uuid": sig_uuid},
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {msg_id})
            return HandlerResult(data={"deleted": sig_uuid}, events=events,
                                 new_version=new_version, session_id=sid)


class BatchAddSignalsHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]
        signals_data = data.get("signals", [])
        if not signals_data:
            raise HandlerError("VALUE_INVALID", "Expected non-empty signals array")

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            created = []
            errors = []
            for i, sd in enumerate(signals_data):
                vtn = sd.get("value_table_name", "")
                try:
                    _validate_value_table_ref(db, vtn)
                except HandlerError as e:
                    errors.append({"index": i, "name": sd.get("name", ""),
                                   "error": e.message})
                    continue
                sig = Signal.from_dict(sd)
                ok, err, _ = db.validate_signal(msg, sig)
                if not ok:
                    errors.append({"index": i, "name": sig.name, "error": err})
                    continue
                if db.add_signal_to_message(msg_id, sig):
                    created.append(sig)
                else:
                    errors.append({"index": i, "name": sig.name, "error": "Message not found"})
            if not created:
                raise HandlerError("VALUE_INVALID", "No signals created", {"errors": errors})
            self._sm.push_undo(session, {"type": "batch_signal_add", "msgId": msg_id,
                                     "signals": [{"uuid": s.uuid, "data": s.to_dict()} for s in created]})
            new_version = db._bump_version()
            events = []
            for sig in created:
                events.append({"type": "signal_added", "data": {"msg_id": msg_id, "signal": sig.to_dict()},
                               "data_version": new_version})
            events.append({"type": "status_changed", "data": {"modified": True,
                           "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                           "data_version": new_version})
            push_data_errors(events, db, new_version, {msg_id})
            return HandlerResult(
                data={"created": [s.to_dict() for s in created], "errors": errors, "count": len(created)},
                events=events, new_version=new_version, session_id=sid)


class GetDataErrorsHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        db = session.db
        with db.with_lock():
            errors = db.full_validate()
        return HandlerResult(data=errors, session_id=sid)
