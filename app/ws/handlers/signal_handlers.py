"""
signal_handlers.py — 信号相关 WS Handler

EditSignal / AddSignal / DeleteSignal / BatchAddSignals / BatchEditSignals / BatchDeleteSignals
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


def _validate_signal_fields(body: dict, msg, sig_name: str = None):
    """统一信号字段校验，供 add/edit/batch 复用。sig_name 非空时为编辑模式。"""
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip():
            raise HandlerError("VALUE_INVALID", "Signal name cannot be empty",
                               {"error_code": "signal_name_empty", "field": "name"})
        stripped = name.strip()
        # 重命名时检查新名是否与已有信号冲突
        if stripped != sig_name and stripped in msg.signals:
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
        sig_name = data["sig_name"]
        field = data["field"]
        value = data["value"]

        if field not in EDITABLE_SIGNAL_FIELDS:
            raise HandlerError("FIELD_NOT_EDITABLE", f"字段 {field} 不可编辑")

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            sig = msg.signals.get(sig_name)
            if not sig:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_name} 不存在")

            old_val = getattr(sig, field)

            try:
                _validate_signal_fields({field: value}, msg, sig_name)
            except HandlerError as e:
                if e.details is not None:
                    e.details[field] = old_val
                raise

            # value_table_name 引用校验
            if field == 'value_table_name':
                _validate_value_table_ref(db, value)

            test_sig = Signal.from_dict({**sig.to_dict(), field: value})
            ok, err, info = db.validate_signal(msg, test_sig, exclude_name=sig_name)
            if not ok:
                if info is None:
                    info = {}
                info[field] = old_val
                raise HandlerError("VALUE_INVALID", err, info)

            # 使用 update_signal_in_message 处理（含重命名逻辑）
            ok, old_name = db.update_signal_in_message(msg_id, sig_name, **{field: value})
            if not ok:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_name} 不存在")
            # 重新获取更新后的 sig（重命名后 key 变了）
            final_name = value if field == 'name' and old_name else sig_name
            sig = msg.signals[final_name]
            self._sm.push_undo(session, {
                "type": "signal_update", "msgId": msg_id, "sigName": sig_name,
                "oldName": old_name,
                "prev": {field: old_val}, "next": {field: value}
            })
            new_version = db._bump_version()
            total_bits = sum(s.length for s in msg.signals.values())
            events = [
                {"type": "signal_updated", "data": {"msg_id": msg_id, "signal": sig.to_dict(), "old_name": old_name,
                                                     "total_signal_bits": total_bits},
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
                                     "sigName": sig.name, "data": sig.to_dict()})
            new_version = db._bump_version()
            total_bits = sum(s.length for s in msg.signals.values())
            events = [
                {"type": "signal_added", "data": {"msg_id": msg_id, "signal": sig.to_dict(),
                                                    "total_signal_bits": total_bits},
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
        sig_name = data["sig_name"]

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            sig = msg.signals.get(sig_name)
            if not sig:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_name} 不存在")
            sig_data = sig.to_dict()
            if not db.remove_signal_from_message(msg_id, sig_name):
                raise HandlerError("SIGNAL_NOT_FOUND", "删除失败")
            self._sm.push_undo(session, {"type": "signal_delete", "msgId": msg_id, "data": sig_data})
            new_version = db._bump_version()
            total_bits = sum(s.length for s in msg.signals.values())
            events = [
                {"type": "signal_deleted", "data": {"msg_id": msg_id, "signal_name": sig_name,
                                                      "total_signal_bits": total_bits},
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {msg_id})
            return HandlerResult(data={"deleted": sig_name}, events=events,
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
                                     "signals": [{"name": s.name, "data": s.to_dict()} for s in created]})
            new_version = db._bump_version()
            total_bits = sum(s.length for s in msg.signals.values())
            events = []
            for sig in created:
                events.append({"type": "signal_added", "data": {"msg_id": msg_id, "signal": sig.to_dict(),
                                                                  "total_signal_bits": total_bits},
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


# 批量编辑时禁止的字段（唯一标识字段，批量修改会导致冲突）
_BATCH_EDIT_FORBIDDEN_FIELDS = {'name', 'start_bit'}


class BatchEditSignalsHandler:
    """批量编辑多个信号的指定字段。

    请求格式: { session_id, msg_id, sig_names: [str], fields: { field: value } }
    """
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        msg_id = data["msg_id"]
        sig_names = data.get("sig_names", [])
        fields = data.get("fields", {})

        if not sig_names:
            raise HandlerError("VALUE_INVALID", "sig_names 不能为空")
        if not fields:
            raise HandlerError("VALUE_INVALID", "fields 不能为空")

        # 验证字段白名单 + 禁止批量修改唯一标识字段
        for field in fields:
            if field not in EDITABLE_SIGNAL_FIELDS:
                raise HandlerError("FIELD_NOT_EDITABLE", f"字段 {field} 不可编辑")
            if field in _BATCH_EDIT_FORBIDDEN_FIELDS:
                raise HandlerError("FIELD_NOT_EDITABLE",
                                   f"字段 {field} 不允许批量编辑",
                                   {"field": field})

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")

            prev = {}   # sig_name -> {field: old_value}
            updated_sigs = []
            errors = []

            for sig_name in sig_names:
                sig = msg.signals.get(sig_name)
                if not sig:
                    errors.append({"sig_name": sig_name, "error": "信号不存在"})
                    continue

                # 记录旧值
                old_vals = {}
                for field in fields:
                    old_vals[field] = getattr(sig, field)

                # 逐字段验证
                try:
                    _validate_signal_fields(fields, msg, sig_name)
                except HandlerError as e:
                    errors.append({"sig_name": sig_name, "error": e.message})
                    continue

                # value_table_name 引用校验
                if 'value_table_name' in fields:
                    try:
                        _validate_value_table_ref(db, fields['value_table_name'])
                    except HandlerError as e:
                        errors.append({"sig_name": sig_name, "error": e.message})
                        continue

                # 验证信号约束（如 bit 范围重叠等）
                test_dict = {**sig.to_dict(), **fields}
                test_sig = Signal.from_dict(test_dict)
                ok, err, info = db.validate_signal(msg, test_sig, exclude_name=sig_name)
                if not ok:
                    errors.append({"sig_name": sig_name, "error": err})
                    continue

                # 应用变更
                for field, value in fields.items():
                    setattr(sig, field, value)

                prev[sig_name] = old_vals
                updated_sigs.append(sig)

            if not updated_sigs:
                raise HandlerError("VALUE_INVALID", "没有信号被更新",
                                   {"errors": errors})

            # 单个 undo 快照
            self._sm.push_undo(session, {
                "type": "batch_signal_update",
                "msgId": msg_id,
                "prev": prev,
                "next": dict(fields),
            })

            new_version = db._bump_version()

            # 逐信号发 signal_updated 事件（复用前端现有处理逻辑）
            total_bits = sum(s.length for s in msg.signals.values())
            events = []
            for sig in updated_sigs:
                events.append({
                    "type": "signal_updated",
                    "data": {"msg_id": msg_id, "signal": sig.to_dict(), "old_name": None,
                             "total_signal_bits": total_bits},
                    "data_version": new_version,
                })
            events.append({
                "type": "status_changed",
                "data": {"modified": True,
                         "undo_count": len(session.undo_stack),
                         "redo_count": len(session.redo_stack)},
                "data_version": new_version,
            })
            push_data_errors(events, db, new_version, {msg_id})

            return HandlerResult(
                data={"updated": len(updated_sigs), "errors": errors},
                events=events,
                new_version=new_version,
                session_id=sid,
            )


class BatchDeleteSignalsHandler:
    """批量删除多个信号。

    请求格式: { session_id, msg_id, sig_names: [str] }
    """
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        msg_id = data["msg_id"]
        sig_names = data.get("sig_names", [])

        if not sig_names:
            raise HandlerError("VALUE_INVALID", "sig_names 不能为空")

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_id)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")

            deleted = []
            errors = []

            for sig_name in sig_names:
                sig = msg.signals.get(sig_name)
                if not sig:
                    errors.append({"sig_name": sig_name, "error": "信号不存在"})
                    continue
                sig_data = sig.to_dict()
                if not db.remove_signal_from_message(msg_id, sig_name):
                    errors.append({"sig_name": sig_name, "error": "删除失败"})
                    continue
                deleted.append({"name": sig_name, "data": sig_data})

            if not deleted:
                raise HandlerError("VALUE_INVALID", "没有信号被删除",
                                   {"errors": errors})

            # 单个 undo 快照
            self._sm.push_undo(session, {
                "type": "batch_signal_delete",
                "msgId": msg_id,
                "signals": deleted,
            })

            new_version = db._bump_version()

            # 逐信号发 signal_deleted 事件
            total_bits = sum(s.length for s in msg.signals.values())
            events = []
            for item in deleted:
                events.append({
                    "type": "signal_deleted",
                    "data": {"msg_id": msg_id, "signal_name": item["name"],
                             "total_signal_bits": total_bits},
                    "data_version": new_version,
                })
            events.append({
                "type": "status_changed",
                "data": {"modified": True,
                         "undo_count": len(session.undo_stack),
                         "redo_count": len(session.redo_stack)},
                "data_version": new_version,
            })
            push_data_errors(events, db, new_version, {msg_id})

            return HandlerResult(
                data={"deleted": len(deleted), "errors": errors},
                events=events,
                new_version=new_version,
                session_id=sid,
            )
