"""报文工具 — 七个 candb_ 工具（Task 8）。

查询/编辑报文走 WS 会话层；分页复用 app/mcp.pagination，错误统一经
app/mcp.errors.tool_error 映射。
"""
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.mcp.auth_context import require_user
from app.mcp.backend import get_backend
from app.mcp.errors import BackendError, tool_error
from app.mcp.pagination import paginate


def _validate_message(message: dict) -> None:
    """校验 add_message 的必填字段（后端缺 name/dlc 会静默用默认值，工具层兜底报错）。"""
    if not isinstance(message, dict):
        raise ToolError("message 必须是对象")
    if not message.get("key") and (
        "id" not in message or message["id"] in (None, "")
    ):
        raise ToolError("新增报文缺少必填字段 key 或 id")
    name = message.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolError("新增报文缺少必填字段 name（非空字符串）")
    dlc = message.get("dlc")
    if isinstance(dlc, bool) or not isinstance(dlc, (int, float)):
        raise ToolError("新增报文缺少必填字段 dlc（整数）")


async def _get_conn(session_id: str):
    """按 session_id 取会话连接；未命中抛 SESSION_NOT_FOUND 的 ToolError。"""
    backend = get_backend()
    try:
        return await backend.get_session(session_id)
    except BackendError as e:
        raise tool_error(e) from e


async def candb_list_messages(
    session_id: str, filter: str | None = None, limit: int = 50, offset: int = 0
) -> dict:
    """分页列出报文的摘要（key/id/id_hex/is_extended_frame/name/dlc/cycle_time/is_fd/sender/comment/signal_count/total_signal_bits）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("get_messages", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    summaries = result.data or {}
    items = list(summaries.values()) if isinstance(summaries, dict) else list(summaries)
    return paginate(items, limit=limit, offset=offset, filter=filter, filter_fields=("name", "id_hex"))


async def candb_get_message(session_id: str, msg_id: int | str) -> dict:
    """获取单个报文的完整详情（含 signals 字段）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("get_message", {"session_id": session_id, "msg_id": msg_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_add_message(session_id: str, message: dict) -> dict:
    """新增报文。message 必填 key 或 id、name(str 非空)、dlc(int，须为合法 DLC)，其余字段透传。"""
    await require_user()
    _validate_message(message)
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("add_message", {"session_id": session_id, "message": message})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_edit_message(session_id: str, msg_id: int | str, fields: dict) -> dict:
    """修改单个报文的字段（fields: {field: value}；改 id 会移动报文）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("edit_message", {"session_id": session_id, "msg_id": msg_id, "fields": fields})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_batch_edit_messages(session_id: str, msg_ids: list[int | str], fields: dict) -> dict:
    """批量修改多个报文的字段（禁止 id/name）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "batch_edit_messages", {"session_id": session_id, "msg_ids": msg_ids, "fields": fields})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_delete_message(session_id: str, msg_id: int | str) -> dict:
    """删除单个报文。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("delete_message", {"session_id": session_id, "msg_id": msg_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def candb_batch_delete_messages(session_id: str, msg_ids: list[int | str]) -> dict:
    """批量删除多个报文。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "batch_delete_messages", {"session_id": session_id, "msg_ids": msg_ids})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


def register_tools(mcp) -> None:
    """把七个报文工具注册进 MCPServer 实例。"""
    mcp.tool(
        description="分页列出报文摘要（key/id/id_hex/is_extended_frame/name/dlc/cycle_time/is_fd/sender/comment/signal_count/total_signal_bits），filter 按 name 或 id_hex 子串过滤",
        annotations=ToolAnnotations(read_only_hint=True),
    )(candb_list_messages)
    mcp.tool(
        description="获取单个报文完整详情（含 signals 字段）",
        annotations=ToolAnnotations(read_only_hint=True),
    )(candb_get_message)
    mcp.tool(
        description="新增报文；message 必填 key 或 id(int)、name(非空 str)、dlc(int)，其余字段透传",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_add_message)
    mcp.tool(
        description="修改单个报文字段（fields: {field: value}，改 id 会移动报文）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_edit_message)
    mcp.tool(
        description="批量修改多个报文字段（禁止 id/name）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_batch_edit_messages)
    mcp.tool(
        description="删除单个报文",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_delete_message)
    mcp.tool(
        description="批量删除多个报文",
        annotations=ToolAnnotations(destructive_hint=True),
    )(candb_batch_delete_messages)
