"""信号物理量程校验单元测试。"""

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


def test_uint8_full_range_passes():
    ok, _, _ = _check(min_val=0, max_val=255)
    assert ok is True


def test_uint8_min_below_range_is_rejected():
    ok, _, info = _check(min_val=-1, max_val=255)
    assert ok is False
    assert info["error_code"] == "signal_min_out_of_range"


def test_uint8_max_above_range_is_rejected():
    ok, _, info = _check(min_val=0, max_val=256)
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"


def test_int8_full_range_passes():
    ok, _, _ = _check(value_type=SignalValueType.INT, min_val=-128, max_val=127)
    assert ok is True


@pytest.mark.parametrize("mn,mx,code", [
    (-129, 127, "signal_min_out_of_range"),
    (-128, 128, "signal_max_out_of_range"),
])
def test_int8_out_of_range_is_rejected(mn, mx, code):
    ok, _, info = _check(value_type=SignalValueType.INT, min_val=mn, max_val=mx)
    assert ok is False
    assert info["error_code"] == code


def test_min_greater_than_max_is_rejected():
    ok, _, info = _check(min_val=10, max_val=5)
    assert ok is False
    assert info["error_code"] == "signal_min_max_invalid"


def test_zero_zero_is_treated_as_unset():
    ok, _, _ = _check(offset=1000.0)
    assert ok is True


def test_factor_zero_skips_range_check():
    ok, _, _ = _check(factor=0.0)
    assert ok is True


def test_factor_and_offset_define_physical_range():
    ok, _, _ = _check(factor=2.0, offset=10.0, min_val=10, max_val=520)
    assert ok is True

    ok, _, info = _check(factor=2.0, offset=10.0, min_val=9, max_val=520)
    assert ok is False
    assert info["error_code"] == "signal_min_out_of_range"

    ok, _, info = _check(factor=2.0, offset=10.0, min_val=10, max_val=521)
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"


def test_negative_factor_swaps_endpoints():
    ok, _, _ = _check(value_type=SignalValueType.INT, factor=-1.0, min_val=-127, max_val=128)
    assert ok is True

    ok, _, info = _check(value_type=SignalValueType.INT, factor=-1.0, min_val=-128, max_val=128)
    assert ok is False
    assert info["error_code"] == "signal_min_out_of_range"


def test_float32_range():
    max_f = 3.4028234663852886e38
    ok, _, _ = _check(value_type=SignalValueType.FLOAT, length=32, min_val=-max_f, max_val=max_f)
    assert ok is True

    ok, _, info = _check(value_type=SignalValueType.FLOAT, length=32, min_val=0, max_val=3.5e38)
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"


def test_double_overflow_is_clamped_to_finite_max():
    max_d = sys.float_info.max
    ok, _, _ = _check(
        value_type=SignalValueType.DOUBLE, length=64, factor=2.0,
        min_val=0, max_val=max_d,
    )
    assert ok is True

    ok, _, info = _check(
        value_type=SignalValueType.DOUBLE, length=64, factor=0.5,
        min_val=0, max_val=max_d,
    )
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"


def test_long_uint_length_does_not_overflow():
    ok, _, _ = _check(length=1024, min_val=0, max_val=sys.float_info.max)
    assert ok is True


def test_non_finite_range_values_are_rejected():
    ok, _, info = _check(min_val=float("nan"), max_val=0)
    assert ok is False
    assert info["error_code"] == "signal_min_max_invalid"


def test_length_change_revalidates_existing_max():
    db = _db()
    sig = _sig(length=8, min_val=0, max_val=255)
    sig.length = 4
    ok, _, info = db.validate_signal(db.messages["0x100:std"], sig)
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"


def test_factor_change_revalidates_existing_max():
    db = _db()
    sig = _sig(factor=1.0, min_val=0, max_val=255)
    sig.factor = 0.5
    ok, _, info = db.validate_signal(db.messages["0x100:std"], sig)
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"


def test_value_type_change_revalidates_existing_max():
    db = _db()
    sig = _sig(value_type=SignalValueType.UINT, length=8, min_val=0, max_val=255)
    sig.value_type = SignalValueType.INT
    ok, _, info = db.validate_signal(db.messages["0x100:std"], sig)
    assert ok is False
    assert info["error_code"] == "signal_max_out_of_range"

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


def test_integrity_skips_zero_zero():
    assert not (RANGE_ERRORS & _error_types(_db_with_sig(offset=1000.0)))


def test_integrity_skips_factor_zero():
    assert not (RANGE_ERRORS & _error_types(_db_with_sig(factor=0.0)))
