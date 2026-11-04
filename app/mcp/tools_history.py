"""校验与历史工具 — 四个 canmatrix_ 工具（Task 11）。"""
from __future__ import annotations

from mcp.types import ToolAnnotations

from app.mcp.auth_context import require_user
from app.mcp.backend import get_backend
from app.mcp.errors import BackendError, tool_error
from app.mcp.pagination import paginate


async def _get_conn(session_id: str):
    backend = get_backend()
    try:
        return await backend.get_session(session_id)
    except BackendError as e:
        raise tool_error(e) from e


async def canmatrix_get_data_errors(session_id: str, limit: int = 50, offset: int = 0) -> dict:
    """分页返回会话的数据完整性错误列表（越界/重叠/空名/重名等）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("get_data_errors", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    errors = result.data or []
    return paginate(errors, limit=limit, offset=offset)


async def canmatrix_undo(session_id: str) -> dict:
    """撤销当前会话的最近一次操作。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("undo", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_redo(session_id: str) -> dict:
    """重做当前会话最近一次撤销的操作。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("redo", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_get_save_diff(session_id: str) -> dict:
    """返回内存数据与磁盘文件之间的字段级差异（entries/count）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("get_save_diff", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


def register_tools(mcp) -> None:
    """把四个校验/历史工具注册进 MCPServer 实例。"""
    mcp.tool(
        description="分页返回会话的数据完整性错误列表（越界/重叠/空名/重名等），修复后 DBC 导出才不被阻断",
        annotations=ToolAnnotations(read_only_hint=True),
    )(canmatrix_get_data_errors)
    mcp.tool(
        description="撤销当前会话的最近一次操作",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_undo)
    mcp.tool(
        description="重做当前会话最近一次撤销的操作",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_redo)
    mcp.tool(
        description="返回内存数据与磁盘文件之间的字段级差异（entries/count）",
        annotations=ToolAnnotations(read_only_hint=True),
    )(canmatrix_get_save_diff)
