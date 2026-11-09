"""MCP 文件/会话工具测试 — 九个工具的往返、锁/只读错误文案、导出。

覆盖 Task 7 的工具行为（真实后端，live_backend 夹具）：
- create/save/close/open 往返（open_file 的 can_write 按 owner==用户 判定）
- create_file 空白填充名按 handler 规则归一化（不 strip）→ owner 侧车与文件同键
- 内联最小 DBC 导入 → export properties 含信号名
- alice 开着文件时 bob open → 成功返回只读会话，标注 is_locked/locked_by=alice
- owner 二次 open 被自己另一会话占锁 → ToolError 文案含占用者
- bob 只读会话调 save → ToolError 文案含所有者提示
- list_files 分页信封 + items 含 file_name/owner/is_locked
- export c_source 返回非空 content（HTTP /api/export，120s 超时约定）
- 数据错误阻断 dbc 导出（force=False）→ ToolError 提及 candb_get_data_errors

说明：仓库未装 pytest-asyncio，沿用 tests/test_mcp_identity.py 的
asyncio.run() 约定（同步测试函数包一层协程）。
"""

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp import tools_session
from app.mcp.auth_context import set_current_pat
from app.mcp.tools_session import (
    candb_close_session,
    candb_create_file,
    candb_export,
    candb_import_file,
    candb_list_files,
    candb_open_file,
    candb_save,
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
    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


def test_create_open_save_close_roundtrip(live_backend, monkeypatch):
    """create_file → save → close → open_file 得到同名文件；
    alice 是 owner → can_write 为 True。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await candb_create_file("rt_file")
            assert created["file_name"] == "rt_file.properties"
            assert created["message_count"] == 0
            assert created["signal_count"] == 0
            sid = created["session_id"]
            assert sid

            saved = await candb_save(sid)
            assert saved["message"] == "保存成功"

            closed = await candb_close_session(sid)
            assert closed == {"closed": True}

            opened = await candb_open_file("rt_file.properties")
            assert opened["file_name"] == "rt_file.properties"
            assert opened["message_count"] == 0
            assert opened["signal_count"] == 0
            assert opened["session_id"] and opened["session_id"] != sid
            assert opened["can_write"] is True  # alice 是文件所有者
            assert opened["is_locked"] is False  # 无锁标注
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_create_file_padded_name_keeps_ownership(live_backend, monkeypatch):
    """带前后空白的 name 按 handler 规则归一化（不 strip）：
    文件名 " pad_file .properties" 与 owner 侧车同键，创建者 can_write=True 且能 save。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await candb_create_file(" pad_file ")
            assert created["file_name"] == " pad_file .properties"  # 原样 + .properties，不 strip

            # owner 侧车键与真实文件一致 → 创建者可写、自己的 save 可过权限检查
            saved = await candb_save(created["session_id"])
            assert saved["message"] == "保存成功"

            await candb_close_session(created["session_id"])
            opened = await candb_open_file(" pad_file .properties")
            assert opened["file_name"] == " pad_file .properties"
            assert opened["can_write"] is True
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_import_dbc_then_export_properties(live_backend, monkeypatch):
    """内联最小 DBC 导入 → export properties 含信号名 SigX。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            imported = await candb_import_file("imp_dbc.dbc", format="dbc", content=MINIMAL_DBC)
            sid = imported["session_id"]
            assert sid
            assert imported["file_name"] == "imp_dbc.properties"

            exported = await candb_export(sid, format="properties")
            assert exported["format"] == "properties"
            assert "SigX" in exported["content"]
            assert exported["file_name"].endswith(".properties")
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_open_locked_file_readonly_shows_lock_owner(live_backend, monkeypatch):
    """alice 占锁时 bob open → 成功返回只读会话（与 Web 端一致），
    can_write=False，结果含 is_locked=True、locked_by="alice"。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await candb_create_file("locked_by_alice")
            assert created["session_id"]  # 会话保持打开 → 文件锁被 alice 持有

            set_current_pat(live_backend["pat_bob"])
            opened = await candb_open_file("locked_by_alice.properties")
            assert opened["session_id"]
            assert opened["can_write"] is False   # bob 非 owner → 只读会话
            assert opened["is_locked"] is True
            assert opened["locked_by"] == "alice"  # 占用者来自 get_sessions
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_owner_reopen_locked_file_reports_owner(live_backend, monkeypatch):
    """owner 二次 open 被自己另一会话占锁 → ToolError 文案含占用者。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            created = await candb_create_file("own_lock")
            assert created["session_id"]  # 第一个会话保持打开 → 占锁

            with pytest.raises(ToolError) as exc_info:
                await candb_open_file("own_lock.properties")
            msg = str(exc_info.value)
            assert "alice" in msg        # 占用者（=owner，也是调用者自己）
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
            created = await candb_create_file("ro_file")
            await candb_close_session(created["session_id"])  # 释放锁，bob 可开只读

            set_current_pat(live_backend["pat_bob"])
            opened = await candb_open_file("ro_file.properties")
            assert opened["can_write"] is False  # bob 非 owner → 只读会话
            sid = opened["session_id"]
            assert sid

            with pytest.raises(ToolError) as exc_info:
                await candb_save(sid)
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
            created = await candb_create_file("listed_file")
            assert created["session_id"]  # 保持打开 → is_locked 为 True

            set_current_pat(live_backend["pat_bob"])
            listing = await candb_list_files()
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
            imported = await candb_import_file("cexp.dbc", format="dbc", content=MINIMAL_DBC)

            exported = await candb_export(imported["session_id"], format="c_source")
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
            created = await candb_create_file("bad_data", content=bad_content)
            sid = created["session_id"]

            with pytest.raises(ToolError) as exc_info:
                await candb_export(sid, format="dbc", force=False)
            assert "candb_get_data_errors" in str(exc_info.value)

            forced = await candb_export(sid, format="dbc", force=True)
            assert forced["format"] == "dbc"
            assert forced["content"].strip()
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_import_dbc_returns_warnings(live_backend, monkeypatch):
    """导入 DBC 时返回未采用属性/结构提示，且不阻断导入。"""

    async def run():
        pool = _prepare(live_backend, monkeypatch)
        try:
            set_current_pat(live_backend["pat_alice"])
            content = '''VERSION ""

NS_ :
\tSIG_GROUP_

BS_:

BU_: ECU1

BO_ 256 Msg: 8 ECU1
 SG_ SigA : 0|8@1+ (1,0) [0|255] "" ECU1

BA_DEF_ BO_ "GenMsgSendType" ENUM "Cyclic","Event";
BA_DEF_ SG_ "GenSigStartValue" INT 0 1000;
BA_ "GenMsgSendType" BO_ 256 0;
BA_ "GenSigStartValue" SG_ 256 SigA 5;
'''
            imported = await candb_import_file("warn.dbc", format="dbc", content=content)
            names = {w["name"] for w in imported.get("import_warnings", [])}
            assert "GenMsgSendType" in names
            assert "GenSigStartValue" in names
            assert imported["warning_count"] >= 2
        finally:
            await pool.aclose_all()

    asyncio.run(run())
