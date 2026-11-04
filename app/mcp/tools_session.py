"""文件/会话工具 — 九个 canmatrix_ 工具（Task 7）。

工具层是薄客户端：编辑/查询消息走 WS 会话层（open_session/get_session/
control/close_session，见 app/mcp/ws.py），导出走 HTTP GET /api/export；
错误统一经 app/mcp.errors.tool_error 映射为 ToolError。
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.mcp.auth_context import require_user
from app.mcp.backend import get_backend
from app.mcp.errors import BackendError, tool_error
from app.mcp.pagination import paginate

# 导出 HTTP 超时（秒）：C 代码等大导出用足额超时。
EXPORT_TIMEOUT = 120.0

# 内联导入支持的格式（不接受服务器路径）
IMPORT_FORMATS = ("dbc", "properties")
# 导出支持的格式
EXPORT_FORMATS = ("properties", "dbc", "c_header", "c_source")

# DBC 导出被数据错误阻断时附上的可执行提示
_DATA_ERROR_FIX_HINT = "先运行 canmatrix_get_data_errors 修复，或设置 force=true 强制导出"

_FILENAME_RE = re.compile(r'filename="([^"]*)"')


# ── 共享辅助 ──


async def _list_file_entries(backend) -> list[dict]:
    """WS get_sessions（经 control()）→ list_history 条目列表。"""
    try:
        conn = await backend.control()
        result = await conn.call("get_sessions", {"current_session_id": ""})
    except BackendError as e:
        raise tool_error(e) from e
    return result.data or []


def _find_file_entry(entries: list[dict], file_name: str) -> dict | None:
    """按 file_name（如 "x.properties"）找 list_history 条目。"""
    for entry in entries:
        if entry.get("file_name") == file_name:
            return entry
    return None


async def _resolve_owner(backend, file_name: str, entry: dict | None) -> str:
    """文件 owner（权限侧车 data/{file_name}.perm.json）；owner 空串 → ""。

    裁定路径：HTTP GET /api/file-permission（需认证，BackendClient 带 PAT）。
    当前后端拒绝 PAT（403，见 app/server/http_handler._get_file_permission 与
    tests/test_http_pat_endpoints.py），被拒/失败时回退 WS get_sessions 条目的
    owner（同一权限侧车数据），保证 can_write 判定可用。
    """
    try:
        resp = await backend.request("GET", f"/api/file-permission?file={quote(file_name)}")
        return str((resp.get("data") or {}).get("owner", "") or "")
    except BackendError:
        return str((entry or {}).get("owner", "") or "")


# ── 九个工具 ──


async def canmatrix_list_files(limit: int = 50, offset: int = 0) -> dict:
    """列出后端所有文件（分页信封），items 含 list_history 原字段（owner、is_locked 等）。"""
    await require_user()
    backend = get_backend()
    entries = await _list_file_entries(backend)
    return paginate(entries, limit=limit, offset=offset)


async def canmatrix_open_file(file_name: str) -> dict:
    """打开文件并创建会话，返回 session_id 与 can_write（owner==当前用户，owner 空 → False）。

    文件被占用时直接报错并给出占用者/所有者（而非死等或静默降级只读）。
    """
    user = await require_user()
    backend = get_backend()
    entries = await _list_file_entries(backend)
    entry = _find_file_entry(entries, file_name)

    # 锁预检：被占文件不静默降级只读，报错并给占用者/所有者信息
    if entry is not None and entry.get("is_locked"):
        raise tool_error(BackendError(
            "FILE_LOCKED", f"文件 {file_name} 已被占用（占用者：{entry.get('owner') or '未知'}）"))

    try:
        _, result = await backend.open_session(
            "load_file", {"file_name": file_name, "current_session_id": ""})
    except BackendError as e:
        if e.code == "FILE_LOCKED":  # 预检后的兜底（如期间被抢占）：补占用者信息
            owner = (entry or {}).get("owner") or "未知"
            raise tool_error(BackendError(
                "FILE_LOCKED", f"文件 {file_name} 已被占用（占用者：{owner}）", e.details)) from e
        raise tool_error(e) from e

    data = result.data or {}
    owner = await _resolve_owner(backend, file_name, entry)
    return {
        "session_id": data.get("session_id") or result.new_session_id or "",
        "file_name": data.get("file_name", file_name),
        "bus_type": data.get("bus_type", ""),
        "message_count": data.get("message_count", 0),
        "signal_count": data.get("signal_count", 0),
        "can_write": bool(owner) and owner == user["username"],
    }


async def canmatrix_create_file(name: str, content: dict | None = None) -> dict:
    """新建文件（可带初始数据库内容 dict），创建者成为文件所有者。

    data 额外带 file_name：router 的 owner 侧车接线按请求 data.file_name 提取
    （CreateFileHandler 不设 new_session_id，见 MessageRouter._extract_file_name），
    与 handler 计算的 file_name 规则保持一致（空名 → Untitled.properties）。
    """
    await require_user()
    base = name.strip() if isinstance(name, str) and name.strip() else "Untitled"
    backend = get_backend()
    try:
        _, result = await backend.open_session(
            "create_file",
            {"name": name, "content": content, "file_name": f"{base}.properties"})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_import_file(file_name: str, format: str = "dbc", content: str = "") -> dict:
    """从内联内容导入 dbc/properties 创建新文件（不接受服务器路径）。"""
    await require_user()
    if format not in IMPORT_FORMATS:
        raise ToolError(f"不支持的导入格式：{format}，仅支持 {'、'.join(IMPORT_FORMATS)}")
    backend = get_backend()
    try:
        _, result = await backend.open_session(
            "import_file",
            {"format": format, "content": content, "filename": file_name, "session_id": ""})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_save(session_id: str) -> dict:
    """保存会话的修改到文件。"""
    await require_user()
    backend = get_backend()
    try:
        conn = await backend.get_session(session_id)
        result = await conn.call("save", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_save_as(session_id: str, name: str) -> dict:
    """把会话数据另存为新文件（不动原文件；只读会话也可用）。"""
    await require_user()
    backend = get_backend()
    try:
        conn = await backend.get_session(session_id)
        result = await conn.call("save_as", {"session_id": session_id, "name": name})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_close_session(session_id: str) -> dict:
    """关闭会话并释放文件锁（未保存的修改可能丢失）。"""
    await require_user()
    backend = get_backend()
    try:
        await backend.close_session(session_id)
    except BackendError as e:
        raise tool_error(e) from e
    return {"closed": True}


async def canmatrix_get_summary(session_id: str) -> dict:
    """获取会话的数据库摘要（报文/信号统计与报文列表）。"""
    await require_user()
    backend = get_backend()
    try:
        conn = await backend.get_session(session_id)
        result = await conn.call("get_summary", {"session_id": session_id})
    except BackendError as e:
        raise tool_error(e) from e
    return dict(result.data or {})


async def canmatrix_export(session_id: str, format: str = "properties", force: bool = False) -> dict:
    """导出文件内容（properties/dbc/c_header/c_source）；DBC 有数据错误时需 force=true 强制导出。"""
    await require_user()
    if format not in EXPORT_FORMATS:
        raise ToolError(f"不支持的导出格式：{format}，仅支持 {'、'.join(EXPORT_FORMATS)}")
    backend = get_backend()
    file_name, content = await _http_export(backend, session_id, format, force)
    return {"format": format, "file_name": file_name, "content": content}


async def _http_export(backend, session_id: str, fmt: str, force: bool) -> tuple[str, str]:
    """HTTP GET /api/export?sid=&fmt=&force=（超时 120s）→ (Content-Disposition 文件名, 响应体文本)。

    422（数据错误阻断 DBC 导出）→ ToolError 附「先运行 canmatrix_get_data_errors 修复，
    或设置 force=true 强制导出」；其余非 2xx 按 tool_error 统一映射。
    """
    try:
        async with httpx.AsyncClient(timeout=EXPORT_TIMEOUT) as client:
            resp = await client.get(
                f"{backend.base_url}/api/export",
                params={"sid": session_id, "fmt": fmt, "force": "1" if force else "0"},
                headers={"Authorization": f"Bearer {backend.token}"},
            )
    except httpx.RequestError as exc:
        raise tool_error(BackendError("HTTP_0", f"无法连接后端：{exc}")) from exc

    if resp.status_code == 200:
        match = _FILENAME_RE.search(resp.headers.get("content-disposition", ""))
        return (match.group(1) if match else ""), resp.text

    try:
        body = resp.json()
    except ValueError:
        body = {}
    message = body.get("error") or f"后端返回 HTTP {resp.status_code}"
    if resp.status_code == 422:
        raise ToolError(f"{message}（HTTP_422）；{_DATA_ERROR_FIX_HINT}")
    raise tool_error(BackendError(f"HTTP_{resp.status_code}", message, body.get("details") or {}))


# ── 注册 ──


def register_tools(mcp) -> None:
    """把九个工具注册进 MCPServer 实例（app/mcp/server.py 调用）。

    注解约定：查询类 readOnlyHint，写类 destructiveHint；
    save/export 按语义标 idempotentHint。
    open_file 属会话生命周期（建会话/持锁、不动数据）→ 非只读且非破坏。
    """
    mcp.tool(
        description="列出后端所有文件（分页），items 含 owner、is_locked 等字段",
        annotations=ToolAnnotations(read_only_hint=True),
    )(canmatrix_list_files)
    mcp.tool(
        description="打开文件并创建会话；文件被占用时报错并给出占用者，can_write 表示当前用户是否可写",
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False),
    )(canmatrix_open_file)
    mcp.tool(
        description="新建文件（可带初始数据库内容），创建者成为文件所有者",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_create_file)
    mcp.tool(
        description="从内联内容导入 dbc 或 properties 创建新文件（不接受服务器路径）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_import_file)
    mcp.tool(
        description="保存会话的修改到文件",
        annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=True),
    )(canmatrix_save)
    mcp.tool(
        description="把会话数据另存为新文件（不动原文件，只读会话也可用）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_save_as)
    mcp.tool(
        description="关闭会话并释放文件锁（未保存的修改可能丢失）",
        annotations=ToolAnnotations(destructive_hint=True),
    )(canmatrix_close_session)
    mcp.tool(
        description="获取会话的数据库摘要（报文/信号统计与报文列表）",
        annotations=ToolAnnotations(read_only_hint=True),
    )(canmatrix_get_summary)
    mcp.tool(
        description="导出文件内容（properties/dbc/c_header/c_source）；DBC 有数据错误时需 force=true 强制导出",
        annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )(canmatrix_export)
