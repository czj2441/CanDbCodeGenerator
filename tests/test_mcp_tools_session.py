"""MCP 文件/会话工具测试 — 九个工具的往返、锁/只读错误文案、导出。

覆盖 Task 7 的工具行为（真实后端，live_backend 夹具）：
- create/save/close/open 往返（open_file 的 can_write 按 owner==用户 判定）
- 内联最小 DBC 导入 → export properties 含信号名
- alice 开着文件时 bob open → ToolError 文案含占用者 "alice"
- bob 只读会话调 save → ToolError 文案含所有者提示
- list_files 分页信封 + items 含 file_name/owner/is_locked
- export c_source 返回非空 content（HTTP /api/export，120s 超时约定）
- 数据错误阻断 dbc 导出（force=False）→ ToolError 提及 canmatrix_get_data_errors

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_identity.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp import tools_session
from app.mcp.auth_context import set_current_pat
from app.mcp.tools_session import (
    canmatrix_close_session,
    canmatrix_create_file,
    canmatrix_export,
    canmatrix_import_file,
    canmatrix_list_files,
    canmatrix_open_file,
    canmatrix_save,
)
from app.mcp.ws import init_session_pool

# 内联最小 DBC（cantools 语法：SG_ 名字后要有冒号）
MINIMAL_DBC = """VERSION ""

NS_ :

BS_:

BU_: ECU1

BO_ 100 Msg1: 8 ECU1
 SG_ SigX : 0|8@1+ (1,0) [0|255] "" ECU1
"""


def _prepare(live_backend, monkeypatch):
    """指向 live_backend 后端并重建会话池（测试间不留连接）。"""
    monkeypatch.setenv("CANMATRIX_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


def test_create_open_save_close_roundtrip(live_backend, monkeypatch):
    """create_file → save → close → open_file 得到同名文件；
    alice 是 owner → can_write 为 True。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await canmatrix_create_file("rt_file")
            assert created["file_name"] == "rt_file.properties"
            assert created["message_count"] == 0
            assert created["signal_count"] == 0
            sid = created["session_id"]
            assert sid

            saved = await canmatrix_save(sid)
            assert saved["message"] == "保存成功"

            closed = await canmatrix_close_session(sid)
            assert closed == {"closed": True}

            opened = await canmatrix_open_file("rt_file.properties")
            assert opened["file_name"] == "rt_file.properties"
            assert opened["message_count"] == 0
            assert opened["signal_count"] == 0
            assert opened["session_id"] and opened["session_id"] != sid
            assert opened["can_write"] is True  # alice 是文件所有者
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_import_dbc_then_export_properties(live_backend, monkeypatch):
    """内联最小 DBC 导入 → export properties 含信号名 SigX。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            imported = await canmatrix_import_file("imp_dbc.dbc", format="dbc", content=MINIMAL_DBC)
            sid = imported["session_id"]
            assert sid
            assert imported["file_name"] == "imp_dbc.properties"

            exported = await canmatrix_export(sid, format="properties")
            assert exported["format"] == "properties"
            assert "SigX" in exported["content"]
            assert exported["file_name"].endswith(".properties")
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_open_locked_file_reports_owner(live_backend, monkeypatch):
    """alice 开着文件（持锁）时 bob open → ToolError 文案含 "alice"。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await canmatrix_create_file("locked_by_alice")
            assert created["session_id"]  # 会话保持打开 → 文件锁被 alice 持有

            set_current_pat(live_backend["pat_bob"])
            with pytest.raises(ToolError) as exc_info:
                await canmatrix_open_file("locked_by_alice.properties")
            msg = str(exc_info.value)
            assert "alice" in msg
            assert "FILE_LOCKED" in msg
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_write_on_readonly_session_reports_owner(live_backend, monkeypatch):
    """bob 只读会话调 save → ToolError 文案含所有者提示。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await canmatrix_create_file("ro_file")
            await canmatrix_close_session(created["session_id"])  # 释放锁，bob 可开只读

            set_current_pat(live_backend["pat_bob"])
            opened = await canmatrix_open_file("ro_file.properties")
            assert opened["can_write"] is False  # bob 非 owner → 只读会话
            sid = opened["session_id"]
            assert sid

            with pytest.raises(ToolError) as exc_info:
                await canmatrix_save(sid)
            assert "文件所有者可写，联系其授权或由其编辑" in str(exc_info.value)
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_list_files_shows_owner_and_lock(live_backend, monkeypatch):
    """list_files 分页信封；items 含 file_name/owner/is_locked（alice 持锁中）。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await canmatrix_create_file("listed_file")
            assert created["session_id"]  # 保持打开 → is_locked 为 True

            set_current_pat(live_backend["pat_bob"])
            listing = await canmatrix_list_files()
            assert set(listing) == {"total", "count", "offset", "items", "has_more", "next_offset"}
            item = next(i for i in listing["items"] if i["file_name"] == "listed_file.properties")
            assert item["owner"] == "alice"
            assert item["is_locked"] is True
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_export_returns_content_with_extended_timeout(live_backend, monkeypatch):
    """export c_source 返回非空 content 且 format == "c_source"（120s 超时约定）。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            imported = await canmatrix_import_file("cexp.dbc", format="dbc", content=MINIMAL_DBC)

            exported = await canmatrix_export(imported["session_id"], format="c_source")
            assert exported["format"] == "c_source"
            assert exported["content"].strip()          # 非空 C 代码
            assert exported["file_name"].endswith(".c")  # Content-Disposition 解析
        finally:
            await pool.aclose_all()

    asyncio.run(run())
    # 大导出（C 代码）走 120s 超时（配置契约）
    assert tools_session.EXPORT_TIMEOUT == 120.0


def test_export_blocked_by_data_errors_mentions_fix(live_backend, monkeypatch):
    """构造数据错误（factor=0）后 export dbc（force=False）→ ToolError 提及 get_data_errors；
    force=true 可强制导出。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            bad_content = {
                "name": "bad_data",
                "messages": {
                    "0x64": {
                        "id": 100, "name": "MsgBad", "dlc": 8,
                        "signals": {"S1": {"name": "S1", "start_bit": 0, "length": 8, "factor": 0}},
                    },
                },
            }
            created = await canmatrix_create_file("bad_data", content=bad_content)
            sid = created["session_id"]

            with pytest.raises(ToolError) as exc_info:
                await canmatrix_export(sid, format="dbc", force=False)
            assert "canmatrix_get_data_errors" in str(exc_info.value)

            forced = await canmatrix_export(sid, format="dbc", force=True)
            assert forced["format"] == "dbc"
            assert forced["content"].strip()
        finally:
            await pool.aclose_all()

    asyncio.run(run())
