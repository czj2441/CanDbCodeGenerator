"""
value_table_handlers.py — 全局值描述表 WS Handler

Add / Update / Delete / Rename / Get 值描述表。
"""

from app.ws.router import HandlerResult, HandlerError


def _validate_entries_keys(entries: dict) -> None:
    """校验值表 key 必须可转为 int。不合法时抛出 HandlerError。"""
    for k in entries:
        try:
            int(k)
        except (ValueError, TypeError):
            raise HandlerError("INVALID_PARAM",
                f"值描述表的键必须是整数，收到无效值: '{k}'")


class AddValueTableHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        name = str(data.get("name", "")).strip()
        if not name:
            raise HandlerError("INVALID_PARAM", "值描述表名称不能为空")
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            raise HandlerError("INVALID_PARAM", "entries 必须是字典")
        _validate_entries_keys(entries)

        db = session.db
        with db.with_lock():
            if not db.add_value_table(name, entries):
                raise HandlerError("ALREADY_EXISTS", f"值描述表 '{name}' 已存在")
            self._sm.push_undo(session, {
                "type": "value_table_add", "name": name,
                "entries": dict(entries),
            })
            new_version = db._bump_version()

        events = [
            {"type": "value_table_added",
             "data": {"name": name, "entries": dict(entries)},
             "data_version": new_version},
            {"type": "status_changed",
             "data": {"modified": True,
                      "undo_count": len(session.undo_stack),
                      "redo_count": len(session.redo_stack)},
             "data_version": new_version},
        ]
        return HandlerResult(data={"name": name}, events=events,
                             new_version=new_version, session_id=sid)


class UpdateValueTableHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        name = str(data.get("name", "")).strip()
        if not name:
            raise HandlerError("INVALID_PARAM", "值描述表名称不能为空")
        entries = data.get("entries", {})
        if not isinstance(entries, dict):
            raise HandlerError("INVALID_PARAM", "entries 必须是字典")
        _validate_entries_keys(entries)

        db = session.db
        with db.with_lock():
            old_entries = dict(db.value_tables.get(name, {}))
            if not db.update_value_table(name, entries):
                raise HandlerError("NOT_FOUND", f"值描述表 '{name}' 不存在")
            self._sm.push_undo(session, {
                "type": "value_table_update", "name": name,
                "prev": old_entries, "next": dict(entries),
            })
            new_version = db._bump_version()

        events = [
            {"type": "value_table_updated",
             "data": {"name": name, "entries": dict(entries)},
             "data_version": new_version},
            {"type": "status_changed",
             "data": {"modified": True,
                      "undo_count": len(session.undo_stack),
                      "redo_count": len(session.redo_stack)},
             "data_version": new_version},
        ]
        return HandlerResult(data={"name": name}, events=events,
                             new_version=new_version, session_id=sid)


class DeleteValueTableHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        name = str(data.get("name", "")).strip()
        if not name:
            raise HandlerError("INVALID_PARAM", "值描述表名称不能为空")

        db = session.db
        with db.with_lock():
            # 记录旧值用于 undo
            old_entries = dict(db.value_tables.get(name, {}))
            ok, ref_count = db.remove_value_table(name)
            if not ok:
                if ref_count > 0:
                    raise HandlerError("VALUE_TABLE_IN_USE",
                                       f"值描述表 '{name}' 被 {ref_count} 个信号引用",
                                       {"error_code": "VALUE_TABLE_IN_USE",
                                        "ref_count": ref_count})
                raise HandlerError("NOT_FOUND", f"值描述表 '{name}' 不存在")
            self._sm.push_undo(session, {
                "type": "value_table_remove", "name": name,
                "entries": old_entries,
            })
            new_version = db._bump_version()

        events = [
            {"type": "value_table_deleted",
             "data": {"name": name},
             "data_version": new_version},
            {"type": "status_changed",
             "data": {"modified": True,
                      "undo_count": len(session.undo_stack),
                      "redo_count": len(session.redo_stack)},
             "data_version": new_version},
        ]
        return HandlerResult(data={"name": name}, events=events,
                             new_version=new_version, session_id=sid)


class RenameValueTableHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        old_name = str(data.get("old_name", "")).strip()
        new_name = str(data.get("new_name", "")).strip()
        if not old_name or not new_name:
            raise HandlerError("INVALID_PARAM", "表名称不能为空")

        db = session.db
        with db.with_lock():
            if not db.rename_value_table(old_name, new_name):
                if old_name not in db.value_tables:
                    raise HandlerError("NOT_FOUND",
                                       f"值描述表 '{old_name}' 不存在")
                raise HandlerError("ALREADY_EXISTS",
                                   f"值描述表 '{new_name}' 已存在")
            self._sm.push_undo(session, {
                "type": "value_table_rename",
                "old_name": old_name, "new_name": new_name,
            })
            new_version = db._bump_version()

        events = [
            {"type": "value_table_renamed",
             "data": {"old_name": old_name, "new_name": new_name},
             "data_version": new_version},
            {"type": "status_changed",
             "data": {"modified": True,
                      "undo_count": len(session.undo_stack),
                      "redo_count": len(session.redo_stack)},
             "data_version": new_version},
        ]
        return HandlerResult(data={"old_name": old_name, "new_name": new_name},
                             events=events, new_version=new_version, session_id=sid)


class GetValueTablesHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        return HandlerResult(data=session.db.get_value_tables(), session_id=sid)
