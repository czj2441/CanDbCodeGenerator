"""值表工具 — 五个 candb_ 工具（Task 10）。"""
from __future__ import annotations

from mcp.types import ToolAnnotations

from app.mcp.auth_context import require_user
from app.mcp.backend import get_backend
from app.mcp.errors import BackendError, tool_error


async def _get_conn(session_id: str):
    backend = get_backend()
    try:
        return await backend.get_session(session_id)
    except BackendError as e:
        raise tool_error(e) from e


async def candb_list_value_tables(session_id: str) -> dict:
    """列出会话的全部值描述表（{name: entries}）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("get_value_tables", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_add_value_table(session_id: str, name: str, entries: dict) -> dict:
    """新增值描述表（entries: {value: label}）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "add_value_table", {"session_id": session_id, "name": name, "entries": entries})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_update_value_table(session_id: str, name: str, entries: dict) -> dict:
    """更新值描述表的条目。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "update_value_table", {"session_id": session_id, "name": name, "entries": entries})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_rename_value_table(session_id: str, old_name: str, new_name: str) -> dict:
    """重命名值描述表。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "rename_value_table", {"session_id": session_id, "old_name": old_name, "new_name": new_name})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_delete_value_table(session_id: str, name: str) -> dict:
    """删除值描述表。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "delete_value_table", {"session_id": session_id, "name": name})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


def register_tools(mcp) -> None:
    """把五个值表工具注册进 MCPServer 实例。"""
    mcp.tool(
        description="列出会话的全部值描述表（{name: entries}）",
        annotations=ToolAnnotations(read_only_hint=True),
    )(candb_list_value_tables)
    mcp.tool(
        description="新增值描述表（entries: {value: label}）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_add_value_table)
    mcp.tool(
        description="更新值描述表条目",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_update_value_table)
    mcp.tool(
        description="重命名值描述表",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_rename_value_table)
    mcp.tool(
        description="删除值描述表",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_delete_value_table)
