"""信号物理量程校验单元测试。

量程错误是非阻断的数据错误（与 overlap 同类）：编辑时保存，完整性检查中报告。
"""

import json
import sys

import pytest

from app.models.database import CanDatabase
from app.models.message import Message
from app.models.signal import Signal, SignalValueType


def _db() -> CanDatabase:
    db = CanDatabase()
    db.add_message(Message(can_id=0x100, name="M", is_extended_frame=False))
    return db


def _sig(**kwargs) -> Signal:
    data = {
        "name": "S", "start_bit": 0, "length": 8,
        "value_type": SignalValueType.UINT,
        "factor": 1.0, "offset": 0.0,
        "min_val": 0.0, "max_val": 0.0,
    }
    data.update(kwargs)
    return Signal(**data)


def _check(**kwargs):
    db = _db()
    msg = db.messages["0x100:std"]
    return db.validate_signal(msg, _sig(**kwargs))


def _db_with_sig(**kwargs) -> CanDatabase:
    db = CanDatabase()
    sig = _sig(**kwargs)
    db.add_message(Message(
        can_id=0x100, name="M", is_extended_frame=False,
        signals={sig.name: sig},
    ))
    return db


def _error_types(db: CanDatabase) -> set[str]:
    return {e["type"] for e in db.full_validate()}


RANGE_ERRORS = {"signal_min_max_invalid", "signal_min_out_of_range", "signal_max_out_of_range"}


# ── 物理量程计算 ───────────────────────────────────────────────────

def test_uint8_physical_range():
    db = _db()
    assert db.signal_physical_range(_sig(length=8)) == (0.0, 255.0)


def test_int8_physical_range():
    db = _db()
    p_min, p_max = db.signal_physical_range(
        _sig(value_type=SignalValueType.INT, length=8)
    )
    assert (p_min, p_max) == (-128.0, 127.0)


def test_factor_and_offset_define_physical_range():
    db = _db()
    p_min, p_max = db.signal_physical_range(_sig(factor=2.0, offset=10.0))
    assert (p_min, p_max) == (10.0, 520.0)


def test_negative_factor_swaps_endpoints():
    db = _db()
    p_min, p_max = db.signal_physical_range(
        _sig(value_type=SignalValueType.INT, factor=-1.0)
    )
    assert (p_min, p_max) == (-127.0, 128.0)


def test_float32_physical_range():
    max_f = 3.4028234663852886e38
    db = _db()
    p_min, p_max = db.signal_physical_range(
        _sig(value_type=SignalValueType.FLOAT, length=32)
    )
    assert p_min == pytest.approx(-max_f)
    assert p_max == pytest.approx(max_f)


def test_double_overflow_is_clamped_to_finite_max():
    db = _db()
    p_min, p_max = db.signal_physical_range(
        _sig(value_type=SignalValueType.DOUBLE, length=64, factor=2.0)
    )
    assert p_min == -sys.float_info.max
    assert p_max == sys.float_info.max


def test_long_uint_length_does_not_overflow():
    db = _db()
    p_min, p_max = db.signal_physical_range(_sig(length=1024))
    assert p_min == 0.0
    assert p_max == sys.float_info.max


def test_zero_length_physical_range_is_safe():
    db = _db()
    p_min, p_max = db.signal_physical_range(
        _sig(value_type=SignalValueType.INT, length=0, min_val=1, max_val=2)
    )
    assert (p_min, p_max) == (0.0, 0.0)


# ── validate_signal：量程错误不阻断 ────────────────────────────────

def test_validate_signal_allows_out_of_range_min():
    ok, _, _ = _check(min_val=-1, max_val=255)
    assert ok is True


def test_validate_signal_allows_out_of_range_max():
    ok, _, _ = _check(min_val=0, max_val=256)
    assert ok is True


def test_validate_signal_allows_min_greater_than_max():
    ok, _, _ = _check(min_val=10, max_val=5)
    assert ok is True


def test_validate_signal_still_rejects_non_finite_values():
    ok, _, info = _check(min_val=float("nan"), max_val=0)
    assert ok is False
    assert info["error_code"] == "signal_min_max_invalid"
    json.dumps(info, allow_nan=False)


def test_validate_signal_still_rejects_zero_length():
    ok, _, info = _check(length=0)
    assert ok is False
    assert info["error_code"] == "signal_length_invalid"


def test_validate_signal_still_rejects_bad_float_length():
    ok, _, info = _check(value_type=SignalValueType.FLOAT, length=8)
    assert ok is False
    assert info["error_code"] == "signal_value_type_length_invalid"


# ── 完整性检查：量程错误在此报告 ──────────────────────────────────

def test_integrity_reports_min_out_of_range():
    assert "signal_min_out_of_range" in _error_types(_db_with_sig(min_val=-1, max_val=255))


def test_integrity_reports_max_out_of_range():
    assert "signal_max_out_of_range" in _error_types(_db_with_sig(min_val=0, max_val=256))


def test_integrity_reports_min_max_invalid():
    assert "signal_min_max_invalid" in _error_types(_db_with_sig(min_val=10, max_val=5))


def test_integrity_reports_non_finite_range():
    assert "signal_min_max_invalid" in _error_types(
        _db_with_sig(min_val=float("inf"), max_val=0)
    )


def test_integrity_non_finite_payload_is_json_safe():
    errors = _db_with_sig(min_val=float("inf"), max_val=0).full_validate()
    json.dumps(errors, allow_nan=False)


def test_integrity_skips_zero_zero():
    assert not (RANGE_ERRORS & _error_types(_db_with_sig(offset=1000.0)))


def test_integrity_skips_factor_zero():
    assert not (RANGE_ERRORS & _error_types(_db_with_sig(factor=0.0)))


def test_integrity_int_zero_length_does_not_crash():
    db = _db_with_sig(value_type=SignalValueType.INT, length=0, min_val=1, max_val=2)
    types = _error_types(db)
    assert "signal_length_zero" in types
    assert not (RANGE_ERRORS & types)


def test_float32_rounded_decimal_max_is_accepted():
    db = _db_with_sig(
        value_type=SignalValueType.FLOAT, length=32,
        min_val=0, max_val=3.4028235e38,
    )
    assert not (RANGE_ERRORS & _error_types(db))


def test_float32_clearly_above_range_is_reported():
    db = _db_with_sig(
        value_type=SignalValueType.FLOAT, length=32,
        min_val=0, max_val=3.5e38,
    )
    assert "signal_max_out_of_range" in _error_types(db)


# ── 修改 length / value_type / factor / offset 后重新报告 ──────────

def test_length_change_reports_range_error():
    db = _db_with_sig(length=8, min_val=0, max_val=255)
    db.messages["0x100:std"].signals["S"].length = 4
    assert "signal_max_out_of_range" in _error_types(db)


def test_factor_change_reports_range_error():
    db = _db_with_sig(factor=1.0, min_val=0, max_val=255)
    db.messages["0x100:std"].signals["S"].factor = 0.5
    assert "signal_max_out_of_range" in _error_types(db)


def test_value_type_change_reports_range_error():
    db = _db_with_sig(value_type=SignalValueType.UINT, length=8, min_val=0, max_val=255)
    db.messages["0x100:std"].signals["S"].value_type = SignalValueType.INT
    assert "signal_max_out_of_range" in _error_types(db)


def test_offset_change_reports_range_error():
    db = _db_with_sig(factor=1.0, offset=0.0, min_val=0, max_val=255)
    db.messages["0x100:std"].signals["S"].offset = 10.0
    assert "signal_min_out_of_range" in _error_types(db)