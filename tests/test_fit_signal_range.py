"""fit_signal_range WS 动作集成测试（真实后端）。"""

import asyncio

import pytest

from app.mcp.backend import BackendClient
from app.mcp.errors import BackendError
from app.mcp.ws import init_session_pool


def _pool(live_backend, monkeypatch):
    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


async def _setup(ctrl, **sig_fields) -> str:
    created = await ctrl.call("new_file", {"name": "fit_range", "session_id": ""})
    sid = created.new_session_id
    await ctrl.call("add_message", {
        "session_id": sid,
        "message": {"id": 0x100, "name": "M", "dlc": 8},
    })
    signal = {
        "name": "S", "start_bit": 0, "length": 8, "byte_order": "intel",
        "min_val": 1.0, "max_val": 2.0,
    }
    signal.update(sig_fields)
    await ctrl.call("add_signal", {
        "session_id": sid, "msg_id": 0x100, "signal": signal,
    })
    return sid


def test_fit_signal_range_writes_physical_bounds(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            sid = await _setup(ctrl, factor=0.5, offset=-10.0)

            result = await ctrl.call("fit_signal_range", {
                "session_id": sid, "msg_id": 0x100, "sig_name": "S",
            })
            assert result.data["min_val"] == pytest.approx(-10.0)
            assert result.data["max_val"] == pytest.approx(117.5)

            got = await ctrl.call("get_message", {"session_id": sid, "msg_id": 0x100})
            assert got.data["signals"]["S"]["min_val"] == pytest.approx(-10.0)
            assert got.data["signals"]["S"]["max_val"] == pytest.approx(117.5)
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_fit_signal_range_negative_factor_and_undo(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            sid = await _setup(ctrl, value_type="int", factor=-2.0, offset=0.0)

            result = await ctrl.call("fit_signal_range", {
                "session_id": sid, "msg_id": 0x100, "sig_name": "S",
            })
            assert result.data["min_val"] == pytest.approx(-254.0)
            assert result.data["max_val"] == pytest.approx(256.0)

            await ctrl.call("undo", {"session_id": sid})
            got = await ctrl.call("get_message", {"session_id": sid, "msg_id": 0x100})
            assert got.data["signals"]["S"]["min_val"] == pytest.approx(1.0)
            assert got.data["signals"]["S"]["max_val"] == pytest.approx(2.0)
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_fit_signal_range_rejects_factor_zero(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            sid = await _setup(ctrl, factor=0.0)

            with pytest.raises(BackendError) as exc:
                await ctrl.call("fit_signal_range", {
                    "session_id": sid, "msg_id": 0x100, "sig_name": "S",
                })
            assert exc.value.details["error_code"] == "factor_zero"

            got = await ctrl.call("get_message", {"session_id": sid, "msg_id": 0x100})
            assert got.data["signals"]["S"]["min_val"] == pytest.approx(1.0)
            assert got.data["signals"]["S"]["max_val"] == pytest.approx(2.0)
        finally:
            await pool.aclose_all()

    asyncio.run(run())