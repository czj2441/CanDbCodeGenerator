"""信号工具 — 八个 canmatrix_ 工具（Task 9）。

信号明细经 get_message（message.to_dict()["signals"] = {name: sig_dict}）获取；
编辑/增删走 WS；分页复用 app/mcp.pagination。
"""
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
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


async def _message_signals(conn, session_id: str, msg_id: int) -> list[dict]:
    """取单报文信号明细列表，每条附 msg_id。"""
    try:
        result = await conn.call("get_message", {"session_id": session_id, "msg_id": msg_id})
    except BackendError as e:
        raise tool_error(e) from e
    signals = (result.data or {}).get("signals", {}) or {}
    return [{**sig, "msg_id": msg_id} for sig in signals.values()]


async def _all_signals(conn, session_id: str) -> list[dict]:
    """取全部报文信号明细（get_messages 得到 id 列表后逐条 get_message）。"""
    try:
        result = await conn.call("get_messages", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    summaries = result.data or {}
    items: list[dict] = []
    for mid in summaries.keys():
        try:
            items.extend(await _message_signals(conn, session_id, int(mid)))
        except ToolError:
            continue
    return items


async def canmatrix_list_signals(
    session_id: str, msg_id: int | None = None, filter: str | None = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    """分页列出信号明细（每条附 msg_id）；msg_id 给定时只看该报文，否则遍历全部报文。"""
    await require_user()
    conn = await _get_conn(session_id)
    if msg_id is not None:
        items = await _message_signals(conn, session_id, msg_id)
    else:
        items = await _all_signals(conn, session_id)
    return paginate(items, limit=limit, offset=offset, filter=filter, filter_fields=("name",))


async def canmatrix_get_signal(session_id: str, msg_id: int, sig_name: str) -> dict:
    """获取单个信号明细（附 msg_id）。"""
    await require_user()
    conn = await _get_conn(session_id)
    items = await _message_signals(conn, session_id, msg_id)
    for sig in items:
        if sig.get("name") == sig_name:
            return sig
    raise ToolError(f"信号 {sig_name} 在报文 0x{msg_id:X} 中不存在")


async def canmatrix_add_signal(session_id: str, msg_id: int, signal: dict) -> dict:
    """在报文中新增一个信号（signal 字段集与后端 add_signal 一致）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call("add_signal", {"session_id": session_id, "msg_id": msg_id, "signal": signal})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_batch_add_signals(session_id: str, msg_id: int, signals: list[dict]) -> dict:
    """在报文中批量新增多个信号。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "batch_add_signals", {"session_id": session_id, "msg_id": msg_id, "signals": signals})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_edit_signal(session_id: str, msg_id: int, sig_name: str, field: str, value) -> dict:
    """修改单个信号的一个字段（field/value）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "edit_signal",
            {"session_id": session_id, "msg_id": msg_id, "sig_name": sig_name, "field": field, "value": value})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_batch_edit_signals(
    session_id: str, msg_id: int, sig_names: list[str], fields: dict,
) -> dict:
    """批量修改报文中多个信号的字段（禁止 name/start_bit）。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "batch_edit_signals",
            {"session_id": session_id, "msg_id": msg_id, "sig_names": sig_names, "fields": fields})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_delete_signal(session_id: str, msg_id: int, sig_name: str) -> dict:
    """删除报文中的一个信号。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "delete_signal", {"session_id": session_id, "msg_id": msg_id, "sig_name": sig_name})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_batch_delete_signals(session_id: str, msg_id: int, sig_names: list[str]) -> dict:
    """批量删除报文中的多个信号。"""
    await require_user()
    conn = await _get_conn(session_id)
    try:
        result = await conn.call(
            "batch_delete_signals",
            {"session_id": session_id, "msg_id": msg_id, "sig_names": sig_names})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


def register_tools(mcp) -> None:
    """把八个信号工具注册进 MCPServer 实例。"""
    mcp.tool(
        description="分页列出信号明细（每条附 msg_id）；msg_id 给定时只看该报文，否则遍历全部报文；filter 按信号名子串过滤",
        annotations=ToolAnnotations(read_only_hint=True),
    )(canmatrix_list_signals)
    mcp.tool(
        description="获取单个信号明细（附 msg_id）",
        annotations=ToolAnnotations(read_only_hint=True),
    )(canmatrix_get_signal)
    mcp.tool(
        description="在报文中新增一个信号",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_add_signal)
    mcp.tool(
        description="在报文中批量新增多个信号",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_batch_add_signals)
    mcp.tool(
        description="修改单个信号的一个字段",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_edit_signal)
    mcp.tool(
        description="批量修改报文中多个信号的字段（禁止 name/start_bit）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_batch_edit_signals)
    mcp.tool(
        description="删除报文中的一个信号",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_delete_signal)
    mcp.tool(
        description="批量删除报文中的多个信号",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_batch_delete_signals)
