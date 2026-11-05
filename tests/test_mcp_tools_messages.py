"""MCP 报文工具测试 — 七个工具的往返、分页/过滤、批量操作与必填校验。

覆盖 Task 8 的工具行为（真实后端，live_backend 夹具）：
- add/get/edit/delete 往返（get 含信号明细；delete 后 get → MESSAGE_NOT_FOUND）
- list_messages 分页信封（造 5 条 → limit=2 得 count==2、has_more==True、total==5）
- list_messages filter 大小写不敏感子串匹配 name 与 id_hex
- batch_edit_messages / batch_delete_messages 批量更新与批量删除
- add_message 缺必填键（dlc/name/id）→ ToolError（后端 VALUE_INVALID 文案）

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_tools_session.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp.auth_context import set_current_pat
from app.mcp.tools_messages import (
    candb_add_message,
    candb_batch_delete_messages,
    candb_batch_edit_messages,
    candb_delete_message,
    candb_edit_message,
    candb_get_message,
    candb_list_messages,
)
from app.mcp.tools_session import candb_create_file
from app.mcp.ws import init_session_pool


def _prepare(live_backend, monkeypatch):
    """指向 live_backend 后端并重建会话池（测试间不留连接）。"""
    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


async def _new_session(file_name: str) -> str:
    """建一个空文件会话并返回 session_id。"""
    created = await candb_create_file(file_name)
    return created["session_id"]


def _msg(msg_id: int, name: str, **extra) -> dict:
    """最小合法 message dict（必填 id/name/dlc + 追加字段）。"""
    message = {"id": msg_id, "name": name, "dlc": 8}
    message.update(extra)
    return message


def test_add_get_edit_delete_message_roundtrip(live_backend, monkeypatch):
    """add_message → get_message → edit_message → delete_message 往返；
    get 含信号明细，delete 后 get → MESSAGE_NOT_FOUND。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("msg_rt")

            added = await candb_add_message(
                sid, _msg(291, "EngineData", cycle_time=100, sender="ECU1", comment="发动机"))
            assert added["id"] == 291
            assert added["name"] == "EngineData"
            assert added["dlc"] == 8
            assert added["cycle_time"] == 100

            detail = await candb_get_message(sid, 291)
            assert detail["id"] == 291
            assert detail["name"] == "EngineData"
            assert detail["signals"] == {}  # 信号明细（空报文无信号）

            edited = await candb_edit_message(sid, 291, {"cycle_time": 50, "comment": "updated"})
            assert edited["cycle_time"] == 50
            assert edited["comment"] == "updated"
            detail = await candb_get_message(sid, 291)
            assert detail["cycle_time"] == 50

            deleted = await candb_delete_message(sid, 291)
            assert deleted["deleted"] == "0x123"  # 291 → 0x123
            with pytest.raises(ToolError) as ei:
                await candb_get_message(sid, 291)
            assert "MESSAGE_NOT_FOUND" in str(ei.value)
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_list_messages_respects_limit_and_offset(live_backend, monkeypatch):
    """造 5 条 → limit=2 得 count==2、has_more==True、total==5；末页收尾。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("msg_page")
            for i in range(5):
                await candb_add_message(sid, _msg(100 + i, f"Msg{i:03d}"))

            page1 = await candb_list_messages(sid, limit=2)
            assert page1["total"] == 5
            assert page1["count"] == 2
            assert page1["offset"] == 0
            assert page1["has_more"] is True
            assert page1["next_offset"] == 2
            assert [m["id"] for m in page1["items"]] == [100, 101]

            last = await candb_list_messages(sid, limit=2, offset=4)
            assert last["count"] == 1
            assert last["has_more"] is False
            assert last["next_offset"] is None
            assert [m["id"] for m in last["items"]] == [104]
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_list_messages_filter_matches_name_and_id_hex(live_backend, monkeypatch):
    """filter 大小写不敏感子串匹配 name 与 id_hex（items 为报文摘要）。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("msg_filter")
            await candb_add_message(sid, _msg(272, "EngineData"))   # 0x110
            await candb_add_message(sid, _msg(544, "ABS_Status"))   # 0x220
            await candb_add_message(sid, _msg(816, "engine_rpm"))   # 0x330

            by_name = await candb_list_messages(sid, filter="engine")
            assert by_name["total"] == 2  # EngineData / engine_rpm（大小写不敏感）
            assert sorted(m["name"] for m in by_name["items"]) == ["EngineData", "engine_rpm"]

            by_id = await candb_list_messages(sid, filter="0x2")
            assert by_id["total"] == 1
            assert by_id["items"][0]["name"] == "ABS_Status"
            assert by_id["items"][0]["id_hex"] == "0x220"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_batch_edit_and_batch_delete(live_backend, monkeypatch):
    """batch_edit_messages 批量更新 cycle_time（不动 id/name）；
    batch_delete_messages 批量删除后列表只剩未删报文。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("msg_batch")
            for i in range(3):
                await candb_add_message(sid, _msg(100 + i, f"Batch{i}"))

            edited = await candb_batch_edit_messages(sid, [100, 102], {"cycle_time": 20})
            assert edited["updated"] == 2
            assert edited["errors"] == []
            assert (await candb_get_message(sid, 100))["cycle_time"] == 20
            assert (await candb_get_message(sid, 101))["cycle_time"] == 0

            deleted = await candb_batch_delete_messages(sid, [100, 102])
            assert deleted["deleted"] == 2
            assert deleted["errors"] == []
            remaining = await candb_list_messages(sid)
            assert remaining["total"] == 1
            assert remaining["items"][0]["id"] == 101
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_add_message_missing_required_fields(live_backend, monkeypatch):
    """message 缺必填键（dlc/name/id）→ ToolError，文案为后端 VALUE_INVALID 文案；
    校验失败不落库。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("msg_required")

            with pytest.raises(ToolError) as ei:  # 缺 dlc
                await candb_add_message(sid, {"id": 300, "name": "NoDlc"})
            assert "dlc" in str(ei.value)

            with pytest.raises(ToolError) as ei:  # 缺 name
                await candb_add_message(sid, {"id": 300, "dlc": 8})
            assert "name" in str(ei.value)

            with pytest.raises(ToolError) as ei:  # 缺 id
                await candb_add_message(sid, {"name": "NoId", "dlc": 8})
            assert "id" in str(ei.value)

            listed = await candb_list_messages(sid)  # 校验失败不应留下报文
            assert listed["total"] == 0
        finally:
            await pool.aclose_all()

    asyncio.run(run())
