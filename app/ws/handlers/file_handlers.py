"""
file_handlers.py — 文件操作 WS Handler

Save / NewFile / ImportFile / DownloadFile / CreateFile / LoadFile /
SaveAs / DeleteFile / GetSessions
"""

import json

from app.models import CanDatabase
from app.services import FileLockedError, FileNameExistsError
from app.ws.router import HandlerResult, HandlerError
from ._common import pure_file_name as _pure_file_name, validate_file_name


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


class NewFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        name = data.get("name", "Untitled")
        if not name or not str(name).strip():
            name = "Untitled"
        try:
            validate_file_name(name)
        except ValueError:
            raise HandlerError("INVALID_FILE_NAME", "非法文件名")
        new_db = CanDatabase(name)
        file_name = f"{name}.properties"
        try:
            new_sid = self._sm.create(file_name, new_db)
        except FileNameExistsError:
            raise HandlerError("FILE_NAME_EXISTS", f"File '{file_name}' already exists")
        return HandlerResult(
            data={"name": new_db.name, "file_name": file_name, "session_id": new_sid},
            new_version=0, session_id=sid, new_session_id=new_sid)


class ImportFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data.get("session_id", "")
        fmt = data.get("format", "json")
        content = data.get("content", "")
        filename = data.get("filename", "")

        try:
            if fmt == "properties":
                new_db = CanDatabase.from_properties_str(content)
            elif fmt == "json":
                parsed = json.loads(content)
                new_db = CanDatabase.from_dict(parsed)
            elif fmt == "dbc":
                new_db = CanDatabase.from_dbc_str(content)
                if filename:
                    try:
                        validate_file_name(filename)
                    except ValueError:
                        raise HandlerError("INVALID_FILE_NAME", "非法文件名")
                    new_db.name = filename.rsplit('.', 1)[0]
            else:
                raise HandlerError("VALUE_INVALID", f"Unsupported format: {fmt}")
        except HandlerError:
            raise
        except Exception as e:
            raise HandlerError("IMPORT_FAILED", f"Import failed: {e}")

        file_name = f"{new_db.name}.properties"
        try:
            new_sid = self._sm.create(file_name, new_db)
        except FileNameExistsError:
            raise HandlerError("FILE_NAME_EXISTS", f"File '{file_name}' already exists")

        return HandlerResult(
            data={"message_count": len(new_db.messages),
                  "session_id": new_sid,
                  "file_name": file_name},
            new_version=0, session_id=sid,
            new_session_id=new_sid)


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
            elif fmt == "properties":
                content = db.to_properties_str()
                ext = ".properties"
            elif fmt == "c_header":
                content = db.to_c_header_str()
                ext = "_signals.h"
            elif fmt == "c_source":
                content = db.to_c_source_str()
                ext = "_signals.c"
            else:
                raise HandlerError("VALUE_INVALID", f"Unsupported format: {fmt}")
        except Exception as e:
            raise HandlerError("EXPORT_FAILED", f"Export failed: {e}")
        file_name = db.name or "export"
        if not file_name.endswith(ext):
            file_name = file_name.rsplit(".", 1)[0] + ext
        return HandlerResult(data={"content": content, "format": fmt, "filename": file_name},
                             session_id=sid)


class CreateFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        db_name = data.get("name", "Untitled")
        if not db_name or not str(db_name).strip():
            db_name = "Untitled"
        try:
            validate_file_name(db_name)
        except ValueError:
            raise HandlerError("INVALID_FILE_NAME", "非法文件名")
        content = data.get("content", None)
        if content:
            db = CanDatabase.from_dict(content)
            db.name = db_name
        else:
            db = CanDatabase(db_name)
        file_name = f"{db_name}.properties"
        sid = self._sm.create(file_name, db)
        return HandlerResult(data={
            "session_id": sid, "file_name": file_name,
            "message_count": len(db.messages), "signal_count": db.total_signals(),
        }, session_id=sid)


class LoadFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        file_name = data["file_name"]
        try:
            validate_file_name(file_name)
        except ValueError:
            raise HandlerError("INVALID_FILE_NAME", "非法文件名")
        current_sid = data.get("current_session_id", "")
        try:
            s = self._sm.restore(file_name, exclude_session=current_sid)
        except FileLockedError as e:
            raise HandlerError("FILE_LOCKED", str(e))
        if not s:
            raise HandlerError("SESSION_NOT_FOUND", "File not found or corrupted")
        return HandlerResult(data={
            "session_id": s.id, "file_name": _pure_file_name(s),
            "message_count": len(s.db.messages), "signal_count": s.db.total_signals(),
        }, session_id=current_sid, new_session_id=s.id if s.id != current_sid else None)


class SaveAsHandler:
    """另存为：克隆当前会话数据到新文件，原始会话不受影响。"""
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        new_name = data.get("name", "")
        if not new_name:
            raise HandlerError("VALUE_INVALID", "Name is required")
        try:
            validate_file_name(new_name)
        except ValueError:
            raise HandlerError("INVALID_FILE_NAME", "非法文件名")
        check = new_name.strip()
        if check.endswith(".properties"):
            check = check[:-11]
        check = check.strip()
        if not check or not check.strip("_"):
            raise HandlerError("VALUE_INVALID", "文件名不能为空")
        try:
            new_sid = self._sm.save_as(sid, new_name)
        except FileNameExistsError:
            raise HandlerError("FILE_NAME_EXISTS", f"File '{new_name}' already exists")
        new_session = self._sm.get(new_sid)
        return HandlerResult(
            data={"session_id": new_sid, "file_name": _pure_file_name(new_session)},
            session_id=sid, new_session_id=new_sid)


class DeleteFileHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        file_name = data["file_name"]
        try:
            validate_file_name(file_name)
        except ValueError:
            raise HandlerError("INVALID_FILE_NAME", "非法文件名")
        ok = self._sm.delete_history(file_name)
        if not ok:
            raise HandlerError("SESSION_NOT_FOUND", "File not found")
        return HandlerResult(data={"deleted": file_name}, session_id=data.get("current_session_id", ""))


class GetSessionsHandler:
    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        current_sid = data.get("current_session_id", "")
        sessions = self._sm.list_history(exclude_session=current_sid)
        return HandlerResult(data=sessions, session_id=current_sid)
