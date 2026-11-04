"""MCP 校验与历史工具测试 — 数据错误分页、undo/redo 往返、save diff。

覆盖 Task 11 的工具行为（真实后端，live_backend 夹具）：
- get_data_errors 分页信封（3 个 factor_zero 错误 → limit=2 得 count==2）
- undo → 报文消失（get_message 报 MESSAGE_NOT_FOUND）→ redo → 报文恢复
- get_save_diff：save 后为空 → 编辑后非空（added）→ 再 save 后为空

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_tools_session.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp.auth_context import set_current_pat
from app.mcp.tools_history import (
    canmatrix_get_data_errors,
    canmatrix_get_save_diff,
    canmatrix_redo,
    canmatrix_undo,
)
from app.mcp.tools_messages import canmatrix_add_message, canmatrix_get_message
from app.mcp.tools_session import canmatrix_create_file, canmatrix_save
from app.mcp.tools_signals import canmatrix_add_signal
from app.mcp.ws import init_session_pool


def _prepare(live_backend, monkeypatch):
    """指向 live_backend 后端并重建会话池（测试间不留连接）。"""
    monkeypatch.setenv("CANMATRIX_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


async def _new_session(file_name: str) -> str:
    """建一个空文件会话并返回 session_id。"""
    created = await canmatrix_create_file(file_name)
    return created["session_id"]


def _msg(msg_id: int, name: str, **extra) -> dict:
    """最小合法 message dict（必填 id/name/dlc + 追加字段）。"""
    message = {"id": msg_id, "name": name, "dlc": 8}
    message.update(extra)
    return message


def _sig(name: str, start_bit: int, length: int = 8, **extra) -> dict:
    """最小合法 signal dict（intel 字节序，位域直观无跨字节）。"""
    signal = {"name": name, "start_bit": start_bit, "length": length, "byte_order": "intel"}
    signal.update(extra)
    return signal


def test_data_errors_pagination(live_backend, monkeypatch):
    """3 个 factor=0 信号 → 3 条 factor_zero 错误；limit/offset 分页信封。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("hist_errors")
            await canmatrix_add_message(sid, _msg(100, "ErrMsg"))
            for i in range(3):
                await canmatrix_add_signal(sid, 100, _sig(f"Bad{i}", i * 8, factor=0))

            errors = await canmatrix_get_data_errors(sid)
            assert errors["total"] == 3
            assert all(e["type"] == "factor_zero" for e in errors["items"])

            page = await canmatrix_get_data_errors(sid, limit=2)
            assert page["count"] == 2
            assert page["has_more"] is True
            assert page["next_offset"] == 2

            last = await canmatrix_get_data_errors(sid, limit=2, offset=2)
            assert last["count"] == 1
            assert last["has_more"] is False
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_undo_redo_roundtrip(live_backend, monkeypatch):
    """add_message → undo → get_message 报不存在 → redo → get_message 存在。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("hist_undo")
            await canmatrix_add_message(sid, _msg(100, "UndoMe"))
            assert (await canmatrix_get_message(sid, 100))["id"] == 100

            undone = await canmatrix_undo(sid)
            assert undone["undo_count"] == 0
            assert undone["redo_count"] == 1
            with pytest.raises(ToolError):
                await canmatrix_get_message(sid, 100)

            redone = await canmatrix_redo(sid)
            assert redone["undo_count"] == 1
            assert redone["redo_count"] == 0
            assert (await canmatrix_get_message(sid, 100))["id"] == 100
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_save_diff_reflects_pending_changes(live_backend, monkeypatch):
    """save 后 get_save_diff 为空；add_message 后非空（added）；再 save 后复空。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("hist_diff")
            await canmatrix_save(sid)  # 落盘：磁盘 == 内存

            diff = await canmatrix_get_save_diff(sid)
            assert diff["count"] == 0

            await canmatrix_add_message(sid, _msg(100, "DiffMsg"))
            diff = await canmatrix_get_save_diff(sid)
            assert diff["count"] >= 1
            assert any(e["type"] == "added" for e in diff["entries"])

            await canmatrix_save(sid)
            diff = await canmatrix_get_save_diff(sid)
            assert diff["count"] == 0
        finally:
            await pool.aclose_all()

    asyncio.run(run())
