"""MCP 信号工具测试 — 八个工具的往返、批量、字段编辑、过滤分页与重叠数据错误。

覆盖 Task 9 的工具行为（真实后端，live_backend 夹具）：
- add/get/edit/delete 往返（get 附 msg_id；delete 后 get → ToolError）
- batch_add_signals 一次创建 3 个信号，list_signals(msg_id=...) count==3
- edit_signal 改 factor → get_signal.factor 更新
- list_signals filter 大小写不敏感子串 + 分页信封
- edit_signal 改 start_bit 造成重叠 → 编辑非阻断成功，随后
  candb_get_data_errors 含 type=="overlap"（工具层不返回 events）

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_tools_session.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp.auth_context import set_current_pat
from app.mcp.tools_history import candb_get_data_errors
from app.mcp.tools_messages import candb_add_message
from app.mcp.tools_session import candb_create_file
from app.mcp.tools_signals import (
    candb_add_signal,
    candb_batch_add_signals,
    candb_delete_signal,
    candb_edit_signal,
    candb_get_signal,
    candb_list_signals,
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


def test_add_get_edit_delete_signal_roundtrip(live_backend, monkeypatch):
    """add_signal → get_signal → edit_signal → delete_signal 往返；
    get 附 msg_id，delete 后 get → ToolError。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_rt")
            await candb_add_message(sid, _msg(291, "EngineData"))

            added = await candb_add_signal(sid, 291, _sig("Speed", 0, factor=1.0))
            assert added["name"] == "Speed"
            assert added["start_bit"] == 0
            assert added["factor"] == 1.0

            got = await candb_get_signal(sid, 291, "Speed")
            assert got["name"] == "Speed"
            assert got["msg_id"] == 291

            edited = await candb_edit_signal(sid, 291, "Speed", "factor", 0.5)
            assert edited["factor"] == 0.5
            assert (await candb_get_signal(sid, 291, "Speed"))["factor"] == 0.5

            deleted = await candb_delete_signal(sid, 291, "Speed")
            assert deleted["deleted"] == "Speed"

            with pytest.raises(ToolError) as ei:
                await candb_get_signal(sid, 291, "Speed")
            assert "Speed" in str(ei.value)
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_batch_add_signals_creates_all(live_backend, monkeypatch):
    """batch_add_signals 一次创建 3 个信号 → count==3、errors==[]；
    list_signals(msg_id=...) 得 3 条。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_batch_add")
            await candb_add_message(sid, _msg(100, "BatchSig"))

            result = await candb_batch_add_signals(sid, 100, [
                _sig("A", 0), _sig("B", 8), _sig("C", 16),
            ])
            assert result["count"] == 3
            assert result["errors"] == []

            listed = await candb_list_signals(sid, msg_id=100)
            assert listed["total"] == 3
            assert sorted(s["name"] for s in listed["items"]) == ["A", "B", "C"]
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_edit_signal_field_value(live_backend, monkeypatch):
    """edit_signal 改 factor → 返回值与 get_signal 均反映新值（其余字段不变）。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_edit_field")
            await candb_add_message(sid, _msg(200, "EditSig"))
            await candb_add_signal(sid, 200, _sig("Temp", 0, factor=1.0, unit="degC"))

            edited = await candb_edit_signal(sid, 200, "Temp", "factor", 0.125)
            assert edited["factor"] == 0.125

            got = await candb_get_signal(sid, 200, "Temp")
            assert got["factor"] == 0.125
            assert got["unit"] == "degC"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_list_signals_filter_and_pagination(live_backend, monkeypatch):
    """filter 大小写不敏感子串匹配信号名；分页信封 total/count/has_more。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_filter")
            await candb_add_message(sid, _msg(100, "MsgA"))
            await candb_batch_add_signals(sid, 100, [
                _sig("EngineSpeed", 0),
                _sig("EngineTemp", 8),
                _sig("BrakePressure", 16),
            ])

            filtered = await candb_list_signals(sid, filter="engine")
            assert filtered["total"] == 2
            assert sorted(s["name"] for s in filtered["items"]) == ["EngineSpeed", "EngineTemp"]

            page = await candb_list_signals(sid, limit=2)
            assert page["total"] == 3
            assert page["count"] == 2
            assert page["has_more"] is True
            assert page["next_offset"] == 2

            last = await candb_list_signals(sid, limit=2, offset=2)
            assert last["count"] == 1
            assert last["has_more"] is False
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_edit_signal_overlap_reports_data_error(live_backend, monkeypatch):
    """edit_signal 改 start_bit 造成重叠（非阻断，编辑成功）→ 随后
    candb_get_data_errors 含 type=="overlap"。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_overlap")
            await candb_add_message(sid, _msg(300, "OverlapMsg"))
            await candb_add_signal(sid, 300, _sig("SigA", 0))
            await candb_add_signal(sid, 300, _sig("SigB", 16))

            await candb_edit_signal(sid, 300, "SigB", "start_bit", 0)

            errors = await candb_get_data_errors(sid)
            assert any(e.get("type") == "overlap" for e in errors["items"])
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_value_type_enum_controls_length(live_backend, monkeypatch):
    """value_type 是枚举；float/double 会自动设置长度 32/64。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_value_type")
            await candb_add_message(sid, _msg(400, "ValueTypeMsg", dlc=64))
            await candb_add_signal(sid, 400, _sig("V", 0, length=8))

            got = await candb_get_signal(sid, 400, "V")
            assert got["value_type"] == "uint"
            assert got["length"] == 8

            edited = await candb_edit_signal(sid, 400, "V", "value_type", "float")
            assert edited["value_type"] == "float"
            assert edited["length"] == 32

            edited = await candb_edit_signal(sid, 400, "V", "value_type", "double")
            assert edited["value_type"] == "double"
            assert edited["length"] == 64

            edited = await candb_edit_signal(sid, 400, "V", "value_type", "int")
            assert edited["value_type"] == "int"
            assert edited["length"] == 64

            with pytest.raises(ToolError):
                await candb_edit_signal(sid, 400, "V", "value_type", "bool")
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_batch_add_invalid_value_type_is_per_signal_error(live_backend, monkeypatch):
    """单个非法 value_type 不应中断整个批量请求。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_batch_bad_type")
            await candb_add_message(sid, _msg(401, "BatchBadType"))

            result = await candb_batch_add_signals(sid, 401, [
                _sig("Good", 0),
                _sig("Bad", 8, value_type="bool"),
            ])
            assert result["count"] == 1
            assert len(result["errors"]) == 1
            assert result["errors"][0]["name"] == "Bad"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_batch_add_rejects_out_of_physical_range(live_backend, monkeypatch):
    """批量新增绕过 _validate_signal_fields，量程校验仍必须生效。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            sid = await _new_session("sig_batch_range")
            await candb_add_message(sid, _msg(402, "BatchRange"))
            result = await candb_batch_add_signals(sid, 402, [
                _sig("Good", 0, min_val=0, max_val=255),
                _sig("Bad", 8, min_val=0, max_val=256),
            ])
            assert result["count"] == 1
            assert result["errors"][0]["name"] == "Bad"
            assert "256" in result["errors"][0]["error"]
        finally:
            await pool.aclose_all()

    asyncio.run(run())
