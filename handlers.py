"""
handlers.py — WS Handler 业务逻辑

每个 handler 是一个 callable 类，不持有 ws 连接，不发送网络消息。
只操作 db 和 session_mgr，返回 HandlerResult。
"""

import json
import math
import os

from models import Signal, Message, CanDatabase
from ws_router import HandlerResult, HandlerError, EDITABLE_SIGNAL_FIELDS


# ═══════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════

def _parse_id(s) -> int | None:
    """解析报文 ID。仅接受 int 或十进制整数字符串。

    注意：不要使用 int(s, 0) — base=0 会附带引入 0x/0o/0b 前缀解析，
    且拒绝前导零字符串（如 "010"）。前端在发送前已通过 parseHex()
    将用户输入转为十进制整数，后端只需处理 int 和纯十进制字符串。
    """
    if isinstance(s, int):
        return s
    if isinstance(s, str):
        try:
            return int(s.strip())
        except ValueError:
            return None
    return None


def _pure_file_name(session) -> str:
    """从 session 中提取纯文件名。"""
    base = os.path.basename(session.file_path)
    if base.startswith(session.id + "_"):
        base = base[len(session.id) + 1:]
    return base


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
    if "factor" in body and body["factor"] == 0:
        raise HandlerError("VALUE_INVALID", "Factor cannot be zero",
                           {"error_code": "factor_zero", "field": "factor"})


# ═══════════════════════════════════════════
# 1. EditSignalHandler — 编辑信号字段
# ═══════════════════════════════════════════

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
            _validate_signal_fields({field: value}, msg, sig_uuid)

            test_sig = Signal.from_dict({**sig.to_dict(), field: value})
            ok, err, info = db.validate_signal(msg_id, test_sig, exclude_uuid=sig_uuid)
            if not ok:
                raise HandlerError("VALUE_INVALID", err, info)

            setattr(sig, field, value)
            db.modified = True
            self._sm.push_undo(sid, {
                "type": "signal_update", "msgId": msg_id, "sigUuid": sig_uuid,
                "prev": {field: old_val}, "next": {field: value}
            })
            new_version = db._bump_version()
            event = {"type": "signal_updated", "data": {"msg_id": msg_id, "signal": sig.to_dict()},
                     "data_version": new_version}
            return HandlerResult(data=sig.to_dict(), events=[event],
                                 new_version=new_version, session_id=sid)


# ═══════════════════════════════════════════
# 2. AddSignalHandler
# ═══════════════════════════════════════════

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
            sig = Signal.from_dict(sig_data)
            ok, err, info = db.validate_signal(msg_id, sig)
            if not ok:
                raise HandlerError("VALUE_INVALID", err, info)
            if not db.add_signal_to_message(msg_id, sig):
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_id} 不存在")
            self._sm.push_undo(sid, {"type": "signal_add", "msgId": msg_id,
                                     "sigUuid": sig.uuid, "data": sig.to_dict()})
            new_version = db._bump_version()
            events = [
                {"type": "signal_added", "data": {"msg_id": msg_id, "signal": sig.to_dict()},
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            # 检查信号错误
            errors = db.validate_all_signals(msg_id)
            events.append({"type": "signal_errors_changed", "data": {"msg_id": msg_id, "errors": errors},
                           "data_version": new_version})
            return HandlerResult(data=sig.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)


# ═══════════════════════════════════════════
# 3. DeleteSignalHandler
# ═══════════════════════════════════════════

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
            self._sm.push_undo(sid, {"type": "signal_delete", "msgId": msg_id, "data": sig_data})
            new_version = db._bump_version()
            events = [
                {"type": "signal_deleted", "data": {"msg_id": msg_id, "signal_uuid": sig_uuid},
                 "data_version": new_version},
                {"type": "status_changed", "data": {"modified": True,
                 "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            errors = db.validate_all_signals(msg_id)
            events.append({"type": "signal_errors_changed", "data": {"msg_id": msg_id, "errors": errors},
                           "data_version": new_version})
            return HandlerResult(data={"deleted": sig_uuid}, events=events,
                                 new_version=new_version, session_id=sid)


# ═══════════════════════════════════════════
# 4. BatchAddSignalsHandler
# ═══════════════════════════════════════════

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
                sig = Signal.from_dict(sd)
                ok, err, _ = db.validate_signal(msg_id, sig)
                if not ok:
                    errors.append({"index": i, "name": sig.name, "error": err})
                    continue
                if db.add_signal_to_message(msg_id, sig):
                    created.append(sig)
                else:
                    errors.append({"index": i, "name": sig.name, "error": "Message not found"})
            if not created:
                raise HandlerError("VALUE_INVALID", "No signals created", {"errors": errors})
            self._sm.push_undo(sid, {"type": "batch_signal_add", "msgId": msg_id,
                                     "signals": [{"uuid": s.uuid, "data": s.to_dict()} for s in created]})
            new_version = db._bump_version()
            events = []
            for sig in created:
                events.append({"type": "signal_added", "data": {"msg_id": msg_id, "signal": sig.to_dict()},
                               "data_version": new_version})
            events.append({"type": "status_changed", "data": {"modified": True,
                           "undo_count": len(session.undo_stack), "redo_count": len(session.redo_stack)},
                           "data_version": new_version})
            errs = db.validate_all_signals(msg_id)
            events.append({"type": "signal_errors_changed", "data": {"msg_id": msg_id, "errors": errs},
                           "data_version": new_version})
            return HandlerResult(
                data={"created": [s.to_dict() for s in created], "errors": errors, "count": len(created)},
                events=events, new_version=new_version, session_id=sid)


# ═══════════════════════════════════════════
# 5. EditMessageHandler
# ═══════════════════════════════════════════

class EditMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = data["msg_id"]
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
            if old_values:
                self._sm.push_undo(sid, {"type": "message_update", "msgId": msg_id,
                                         "prev": old_values,
                                         "next": {k: v for k, v in fields.items() if k != "id"}})
            new_version = db._bump_version()
            updated_msg = db.get_message(msg_id)
            events = [
                {"type": "message_updated", "data": {"message": {
                    "id": msg_id, "id_hex": f"0x{msg_id:X}", "name": updated_msg.name,
                    "dlc": updated_msg.dlc, "cycle_time": updated_msg.cycle_time,
                    "sender": updated_msg.sender, "comment": updated_msg.comment,
                    "signal_count": len(updated_msg.signals)}},
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


# ═══════════════════════════════════════════
# 6. AddMessageHandler
# ═══════════════════════════════════════════

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


# ═══════════════════════════════════════════
# 7. DeleteMessageHandler
# ═══════════════════════════════════════════

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


# ═══════════════════════════════════════════
# 8. UndoHandler
# ═══════════════════════════════════════════

class UndoHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        result = self._sm.undo(sid)
        if not result["success"]:
            raise HandlerError("UNDO_FAILED", result.get("message", "撤销失败"))

        # 构建全量数据广播（undo 可能影响多个报文/信号）
        db = session.db
        with db.with_lock():
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


# ═══════════════════════════════════════════
# 9. RedoHandler
# ═══════════════════════════════════════════

class RedoHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        result = self._sm.redo(sid)
        if not result["success"]:
            raise HandlerError("REDO_FAILED", result.get("message", "重做失败"))

        db = session.db
        with db.with_lock():
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


# ═══════════════════════════════════════════
# 10. SaveHandler
# ═══════════════════════════════════════════

class SaveHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        try:
            ok = self._sm.save(sid)
        except Exception as e:
            raise HandlerError("SAVE_FAILED", f"保存失败: {e}")
        if not ok:
            raise HandlerError("SAVE_FAILED", "保存失败：会话不存在")
        events = [{"type": "status_changed",
                    "data": {"modified": False}, "data_version": 0}]
        return HandlerResult(data={"message": "保存成功"}, events=events, session_id=sid)


# ═══════════════════════════════════════════
# 11. NewFileHandler (含 session 切换)
# ═══════════════════════════════════════════

class NewFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        name = data.get("name", "Untitled")
        if not name or not str(name).strip():
            name = "Untitled"
        # 先保存当前会话
        if sid:
            try:
                self._sm.save(sid)
            except Exception:
                pass
        new_db = CanDatabase(name)
        file_name = f"{name}.toml"
        new_sid = self._sm.create(file_name, new_db)
        return HandlerResult(
            data={"name": new_db.name, "session_id": new_sid},
            new_version=0, session_id=sid, new_session_id=new_sid)


# ═══════════════════════════════════════════
# 12. ImportFileHandler (含 session 切换)
# ═══════════════════════════════════════════

class ImportFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        fmt = data.get("format", "json")
        content = data.get("content", "")
        filename = data.get("filename", "")

        try:
            if fmt == "toml":
                new_db = CanDatabase.from_toml_str(content)
            elif fmt == "json":
                parsed = json.loads(content)
                new_db = CanDatabase.from_dict(parsed)
            elif fmt == "dbc":
                import cantools.database, tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.dbc', delete=False, encoding='utf-8') as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name
                try:
                    can_db = cantools.database.load_file(tmp_path)
                    new_db = CanDatabase(name=filename.replace('.dbc', '') if filename else 'imported_dbc')
                    for can_msg in can_db.messages:
                        cycle_time = 0
                        try:
                            if can_msg.cycle_time is not None:
                                cycle_time = int(can_msg.cycle_time)
                        except Exception:
                            pass
                        sender = ""
                        try:
                            senders = getattr(can_msg, "senders", None)
                            if senders and isinstance(senders, list) and len(senders) > 0:
                                sender = str(senders[0])
                        except Exception:
                            pass
                        msg = Message.from_dict({
                            "id": can_msg.frame_id, "name": can_msg.name, "dlc": can_msg.length,
                            "cycle_time": cycle_time, "comment": can_msg.comment or "", "sender": sender,
                        })
                        for can_sig in can_msg.signals:
                            bo = can_sig.byte_order
                            order_str = bo.name.lower() if hasattr(bo, "name") else str(bo).lower()
                            if order_str in ("little", "little_endian", "intel"):
                                order_str = "intel"
                            elif order_str in ("big", "big_endian", "motorola"):
                                order_str = "motorola"
                            mux_mode = "none"
                            mux_value = 0
                            if can_sig.is_multiplexer:
                                mux_mode = "multiplexer"
                            elif can_sig.multiplexer_ids:
                                mux_mode = "multiplexed"
                                mux_value = can_sig.multiplexer_ids[0]
                            sig = Signal.from_dict({
                                "name": can_sig.name, "start_bit": can_sig.start, "length": can_sig.length,
                                "byte_order": order_str, "is_signed": can_sig.is_signed,
                                "factor": can_sig.scale or 1.0, "offset": can_sig.offset or 0.0,
                                "min_val": can_sig.minimum or 0.0, "max_val": can_sig.maximum or 0.0,
                                "unit": can_sig.unit or "", "comment": can_sig.comment or "",
                                "receivers": can_sig.receivers[:] if can_sig.receivers else [],
                                "multiplexer_mode": mux_mode, "multiplexer_value": mux_value,
                            })
                            msg.signals.append(sig)
                        new_db.add_message(msg)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
            else:
                raise HandlerError("VALUE_INVALID", f"Unsupported format: {fmt}")
        except HandlerError:
            raise
        except Exception as e:
            raise HandlerError("IMPORT_FAILED", f"Import failed: {e}")

        # 替换当前会话 DB
        new_sid = sid
        if sid:
            s = self._sm.get(sid)
            if s:
                s.db = new_db
                self._sm.save(sid)
            else:
                new_sid = self._sm.create(f"{new_db.name}.toml", new_db)
        else:
            new_sid = self._sm.create(f"{new_db.name}.toml", new_db)

        return HandlerResult(
            data={"message_count": len(new_db.messages), "session_id": new_sid},
            new_version=0, session_id=sid,
            new_session_id=new_sid if new_sid != sid else None)


# ═══════════════════════════════════════════
# 13. ExportFileHandler
# ═══════════════════════════════════════════

class ExportFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        fmt = data.get("format", "json")
        try:
            if fmt == "json":
                content = json.dumps(db.to_dict(), ensure_ascii=False, indent=2)
            elif fmt == "toml":
                content = db.to_toml_str()
            elif fmt == "dbc":
                content = db.to_dbc_str()
            else:
                raise HandlerError("VALUE_INVALID", f"Unsupported format: {fmt}")
        except Exception as e:
            raise HandlerError("EXPORT_FAILED", f"Export failed: {e}")
        return HandlerResult(data={"content": content, "format": fmt}, session_id=sid)


# ═══════════════════════════════════════════
# 14. DownloadFileHandler
# ═══════════════════════════════════════════

class DownloadFileHandler:
    """返回文件内容供前端下载（Content-Disposition 由前端处理）。"""
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        fmt = data.get("format", "dbc")
        try:
            if fmt == "dbc":
                content = db.to_dbc_str()
                ext = ".dbc"
            elif fmt == "toml":
                content = db.to_toml_str()
                ext = ".toml"
            elif fmt == "json":
                content = json.dumps(db.to_dict(), ensure_ascii=False, indent=2)
                ext = ".json"
            else:
                raise HandlerError("VALUE_INVALID", f"Unsupported format: {fmt}")
        except Exception as e:
            raise HandlerError("EXPORT_FAILED", f"Export failed: {e}")
        file_name = db.name or "export"
        if not file_name.endswith(ext):
            file_name = file_name.rsplit(".", 1)[0] + ext
        return HandlerResult(data={"content": content, "format": fmt, "filename": file_name},
                             session_id=sid)


# ═══════════════════════════════════════════
# 15. CreateSessionHandler
# ═══════════════════════════════════════════

class CreateSessionHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        db_name = data.get("name", "Untitled")
        if not db_name or not str(db_name).strip():
            db_name = "Untitled"
        content = data.get("content", None)
        if content:
            db = CanDatabase.from_dict(content)
            db.name = db_name
        else:
            db = CanDatabase(db_name)
        file_name = f"{db_name}.toml"
        sid = self._sm.create(file_name, db)
        return HandlerResult(data={
            "session_id": sid, "file_name": file_name,
            "message_count": len(db.messages), "signal_count": db.total_signals(),
        }, session_id=sid)


# ═══════════════════════════════════════════
# 16. LoadSessionHandler
# ═══════════════════════════════════════════

class LoadSessionHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        target_sid = data["session_id"]
        current_sid = data.get("current_session_id", "")
        from session_manager import FileLockedError
        try:
            s = self._sm.restore(target_sid, exclude_session=current_sid)
        except FileLockedError as e:
            raise HandlerError("FILE_LOCKED", str(e))
        if not s:
            raise HandlerError("SESSION_NOT_FOUND", "Session not found or corrupted")
        return HandlerResult(data={
            "session_id": s.id, "file_name": _pure_file_name(s),
            "message_count": len(s.db.messages), "signal_count": s.db.total_signals(),
        }, session_id=current_sid, new_session_id=s.id if s.id != current_sid else None)


# ═══════════════════════════════════════════
# 17. RenameSessionHandler
# ═══════════════════════════════════════════

class RenameSessionHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        new_name = data.get("name", "")
        if not new_name:
            raise HandlerError("VALUE_INVALID", "Name is required")
        # 去前缀 + .toml 后校验：防止空名称文件被创建
        check = new_name.strip()
        if check.endswith(".toml"):
            check = check[:-5]
        if check.startswith(sid + "_"):
            check = check[len(sid) + 1:]
        check = check.strip()
        if not check or not check.strip("_"):
            raise HandlerError("VALUE_INVALID", "文件名不能为空")
        ok = self._sm.rename(sid, new_name)
        if not ok:
            raise HandlerError("SESSION_NOT_FOUND", "Session not found")
        s = self._sm.get(sid)
        return HandlerResult(data={"name": s.db.name, "file_name": _pure_file_name(s)},
                             session_id=sid)


# ═══════════════════════════════════════════
# 18. DeleteSessionHandler
# ═══════════════════════════════════════════

class DeleteSessionHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        target_sid = data["session_id"]
        ok = self._sm.delete_history(target_sid)
        if not ok:
            raise HandlerError("SESSION_NOT_FOUND", "Session not found")
        return HandlerResult(data={"deleted": target_sid}, session_id=data.get("current_session_id", ""))


# ═══════════════════════════════════════════
# 19. GetSessionsHandler
# ═══════════════════════════════════════════

class GetSessionsHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        current_sid = data.get("current_session_id", "")
        sessions = self._sm.list_history(exclude_session=current_sid)
        return HandlerResult(data=sessions, session_id=current_sid)


# ═══════════════════════════════════════════
# 20. ReleaseLockHandler
# ═══════════════════════════════════════════

class ReleaseLockHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        abort = data.get("abort", False)
        if sid:
            self._sm.release_session(sid, abort=abort)
        return HandlerResult(data={"released": True}, session_id=sid)


# ═══════════════════════════════════════════
# 21. StealLockHandler
# ═══════════════════════════════════════════

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
        # 释放目标 session 的文件锁（触发 lock_stolen 广播）
        self._sm.release_session(target_sid)
        return HandlerResult(data={"released_session": target_sid},
                             session_id=data.get("current_session_id", ""))


# ═══════════════════════════════════════════
# 22. GetSummaryHandler
# ═══════════════════════════════════════════

class GetSummaryHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msgs = list(db.messages.values())
        return HandlerResult(data={
            "name": db.name, "message_count": len(msgs),
            "signal_count": db.total_signals(), "modified": db.modified,
            "messages": [{"id": m.id, "id_hex": f"0x{m.id:X}", "name": m.name,
                          "dlc": m.dlc, "signal_count": len(m.signals)}
                         for m in sorted(msgs, key=lambda m: m.id)],
        }, session_id=sid)


# ═══════════════════════════════════════════
# 23. GetSessionInfoHandler
# ═══════════════════════════════════════════

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


# ═══════════════════════════════════════════
# 24. GetMessageHandler
# ═══════════════════════════════════════════

class GetMessageHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
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


# ═══════════════════════════════════════════
# 25. GetSignalErrorsHandler
# ═══════════════════════════════════════════

class GetSignalErrorsHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        msg_id = _parse_id(data.get("msg_id", ""))
        if msg_id is None:
            raise HandlerError("VALUE_INVALID", "Invalid message ID")
        errors = db.validate_all_signals(msg_id)
        return HandlerResult(data=errors, session_id=sid)


# ═══════════════════════════════════════════
# 26. GetStatusHandler
# ═══════════════════════════════════════════

class GetStatusHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
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


# ═══════════════════════════════════════════
# 27. DuplicateMessageHandler
# ═══════════════════════════════════════════

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


# ═══════════════════════════════════════════
# 28. GetMessagesHandler (完整报文列表)
# ═══════════════════════════════════════════

class GetMessagesHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        session = self._sm.get(sid) if sid else None
        db = session.db if session else None
        if not db:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")
        messages = [
            {"id": mid, "id_hex": f"0x{mid:X}", "name": m.name,
             "dlc": m.dlc, "cycle_time": m.cycle_time, "signal_count": len(m.signals)}
            for mid, m in sorted(db.messages.items())
        ]
        return HandlerResult(data=messages, session_id=sid)
