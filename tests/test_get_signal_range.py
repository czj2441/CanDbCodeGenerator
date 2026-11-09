"""get_signal_range 只读量程计算测试（真实后端）。"""

import asyncio

import pytest

from app.mcp.backend import BackendClient
from app.mcp.errors import BackendError
from app.mcp.ws import init_session_pool


def _pool(live_backend, monkeypatch):
    monkeypatch.setenv("CANDB_CODEGENERATOR_BACKEND_URL", live_backend["base_url"])
    return init_session_pool(idle_ttl=60.0, ping_interval=0.2)


def test_uint_range_with_factor_offset(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()

            result = await ctrl.call("get_signal_range", {"length": 8})
            assert result.data == {"min_val": 0.0, "max_val": 255.0}

            result = await ctrl.call("get_signal_range", {
                "length": 16, "factor": 2.0, "offset": 10.0,
            })
            assert result.data == {"min_val": 10.0, "max_val": 131080.0}
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_int_negative_factor_swaps_endpoints(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            result = await ctrl.call("get_signal_range", {
                "length": 8, "value_type": "int", "factor": -1.0,
            })
            assert result.data == {"min_val": -127.0, "max_val": 128.0}
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_float_range(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            result = await ctrl.call("get_signal_range", {
                "length": 32, "value_type": "float",
            })
            assert result.data["min_val"] == pytest.approx(-3.4028234663852886e38)
            assert result.data["max_val"] == pytest.approx(3.4028234663852886e38)
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_factor_zero_is_error(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            with pytest.raises(BackendError) as exc:
                await ctrl.call("get_signal_range", {"length": 8, "factor": 0})
            assert exc.value.details["error_code"] == "factor_zero"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_float_length_mismatch_is_error(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            with pytest.raises(BackendError) as exc:
                await ctrl.call("get_signal_range", {"length": 8, "value_type": "float"})
            assert exc.value.details["error_code"] == "signal_value_type_length_invalid"
        finally:
            await pool.aclose_all()

    asyncio.run(run())


def test_zero_length_is_error(live_backend, monkeypatch):
    async def run():
        pool = _pool(live_backend, monkeypatch)
        try:
            client = BackendClient(live_backend["base_url"], live_backend["pat_alice"])
            ctrl = await client.control()
            with pytest.raises(BackendError) as exc:
                await ctrl.call("get_signal_range", {"length": 0})
            assert exc.value.details["error_code"] == "signal_length_invalid"
        finally:
            await pool.aclose_all()

    asyncio.run(run())