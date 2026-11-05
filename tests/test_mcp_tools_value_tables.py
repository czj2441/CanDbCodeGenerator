"""MCP 值表工具测试 — 五个工具的往返与非法 entries 校验。

覆盖 Task 10 的工具行为（真实后端，live_backend 夹具）：
- add/list/update/rename/delete 往返（entries 为 {value: label} 映射）
- add_value_table 非法 entries（键不可转 int）→ ToolError（后端 INVALID_PARAM 文案，
  由 AddValueTableHandler._validate_entries_keys 抛出）

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_tools_session.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp.auth_context import set_current_pat
from app.mcp.tools_session import candb_create_file
from app.mcp.tools_value_tables import (
    candb_add_value_table,
    candb_delete_value_table,
    candb_list_value_tables,
    candb_rename_value_table,
    candb_update_value_table,
)
from app.mcp.ws import init_session_pool


def _prepare(live_backend, monkeypatch):
    """指向 live_backend 后端并重建会话池（测试间不留连接）。"""
    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


async def _new_session(file_name: str) -> str:
    """建一个空文件会话并返回 session_id。"""
    created = await candb_create_file(file_name)
    return created["session_id"]


def test_add_list_update_rename_delete_roundtrip(live_backend, monkeypatch):
    """add → list → update → rename → delete 往返；list_value_tables 返回 {name: entries}。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("vt_rt")

            added = await candb_add_value_table(sid, "GearStatus", {"0": "Neutral", "1": "Drive"})
            assert added["name"] == "GearStatus"
            assert (await candb_list_value_tables(sid))["GearStatus"] == {"0": "Neutral", "1": "Drive"}

            updated = await candb_update_value_table(sid, "GearStatus", {"0": "N", "1": "D", "2": "R"})
            assert updated["name"] == "GearStatus"
            assert (await candb_list_value_tables(sid))["GearStatus"] == {"0": "N", "1": "D", "2": "R"}

            renamed = await candb_rename_value_table(sid, "GearStatus", "GearPos")
            assert renamed == {"old_name": "GearStatus", "new_name": "GearPos"}
            tables = await candb_list_value_tables(sid)
            assert "GearPos" in tables
            assert "GearStatus" not in tables

            deleted = await candb_delete_value_table(sid, "GearPos")
            assert deleted["name"] == "GearPos"
            assert (await candb_list_value_tables(sid)) == {}
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_add_value_table_invalid_entries(live_backend, monkeypatch):
    """entries 键不可转 int → ToolError（后端 INVALID_PARAM：键必须是整数）。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("vt_invalid")

            with pytest.raises(ToolError) as ei:
                await candb_add_value_table(sid, "BadTable", {"abc": "label"})
            assert "INVALID_PARAM" in str(ei.value)
            assert "abc" in str(ei.value)
        finally:
            await pool.aclose_all()

    asyncio.run(run())
