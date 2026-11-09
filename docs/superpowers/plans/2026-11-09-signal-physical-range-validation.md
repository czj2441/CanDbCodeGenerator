# Signal Physical Range Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate signal `min_val` / `max_val` against the physical range implied by `value_type`, `length`, `factor`, and `offset`; add a button that fills the computed range.

**Architecture:** One range helper on `CanDatabase` feeds both blocking validation (`validate_signal`) and non-blocking integrity checks (`_validate_single_message_integrity`). A new WS action `fit_signal_range` reuses the helper and performs an atomic, undoable update of `min_val` / `max_val`.

**Tech Stack:** Python 3.12, pytest, Vue 3 + Pinia, WebSocket handler architecture.

**Spec:** `docs/superpowers/specs/2026-11-09-signal-physical-range-validation-design.md`

## Global Constraints

- Error codes exactly: `signal_min_max_invalid`, `signal_min_out_of_range`, `signal_max_out_of_range`.
- `min_val == 0 and max_val == 0` means “unset”: skip all range checks.
- `factor == 0` skips range checks; `factor_zero` integrity error remains the only report.
- `offset` has no separate bound; it only shifts the computed physical range.
- Float comparison uses plain Python `float`, no tolerance.
- DBC import must keep succeeding; invalid attributes surface through data errors only.
- Frontend copy is Chinese, keyed in `frontend/src/i18n.js`.

## Review Focus

- Changing `length`, `value_type`, `factor`, or `offset` must re-check existing `min_val` / `max_val` through the merged signal (Task 1 tests).
- Default `0/0` min/max must never produce range errors (Task 1 and Task 2 tests).
- Negative `factor` must swap physical endpoints (Task 1 test).
- Very large integer lengths and float/double overflow must clamp to finite `sys.float_info.max`, never raise `OverflowError` or store infinity (Task 1 test).
- Batch add bypasses `_validate_signal_fields`; range validation must still reject bad signals there (Task 3 test).

---

### Task 1: Physical range helper and blocking validation

**Files:**
- Modify: `app/models/database.py` (imports; add helper after `_get_signal_bits`; extend `validate_signal`)
- Test: `tests/test_signal_range_validation.py` (new)

**Interfaces:**
- Produces: `CanDatabase.signal_physical_range(sig: Signal) -> tuple[float, float]`
- Produces: `CanDatabase.validate_signal(msg: Message, sig: Signal, exclude_name: str | None = None) -> tuple[bool, str, dict]` with the new error codes.
- Consumes: `Signal` fields `value_type`, `length`, `factor`, `offset`, `min_val`, `max_val`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_signal_range_validation.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_signal_range_validation.py -v`
Expected: FAIL — range checks absent (`ok is True` where rejection expected).

- [ ] **Step 3: Implement the helper and validation**

In `app/models/database.py`, add `import math` and `import sys`. Add the module-level `_FLT_MAX` constant and `_as_float` helper (outside the class), then add `signal_physical_range` as a `@staticmethod` **inside `CanDatabase`**, after `_get_signal_bits`:

```python
_FLT_MAX = 3.4028234663852886e38

def _as_float(value: int | float) -> float:
    """整数可能超过 float 上限；溢出按 ±inf 处理，随后统一钳制。"""
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


@staticmethod
def signal_physical_range(sig: Signal) -> tuple[float, float]:
    """按 value_type/length/factor/offset 计算物理可表示范围。"""
    if sig.factor == 0:
        return sig.offset, sig.offset

    if sig.value_type == SignalValueType.UINT:
        raw_min, raw_max = 0, (1 << sig.length) - 1
    elif sig.value_type == SignalValueType.INT:
        raw_min = -(1 << (sig.length - 1))
        raw_max = (1 << (sig.length - 1)) - 1
    elif sig.value_type == SignalValueType.FLOAT:
        raw_min, raw_max = -_FLT_MAX, _FLT_MAX
    else:
        raw_min, raw_max = -sys.float_info.max, sys.float_info.max

    a = _as_float(raw_min) * sig.factor + sig.offset
    b = _as_float(raw_max) * sig.factor + sig.offset
    lo, hi = min(a, b), max(a, b)
    return max(lo, -sys.float_info.max), min(hi, sys.float_info.max)
```

Extend `validate_signal` after the existing float/double length checks, before the deferred A3/A4 comment:

```python
if sig.min_val == 0 and sig.max_val == 0:
    return True, "", {"type": "ok"}
if sig.factor != 0:
    if not all(math.isfinite(v) for v in (sig.factor, sig.offset, sig.min_val, sig.max_val)):
        return False, "Signal min/max values must be finite", {
            "error_code": "signal_min_max_invalid", "type": "invalid_param",
            "field": "min_val", "min_val": sig.min_val, "max_val": sig.max_val,
        }
    if sig.min_val > sig.max_val:
        return False, "Signal min value must not exceed max value", {
            "error_code": "signal_min_max_invalid", "type": "invalid_param",
            "field": "max_val", "min_val": sig.min_val, "max_val": sig.max_val,
        }
    p_min, p_max = self.signal_physical_range(sig)
    if sig.min_val < p_min:
        return False, f"Signal min value {sig.min_val} is below {p_min}", {
            "error_code": "signal_min_out_of_range", "type": "invalid_param",
            "field": "min_val", "value": sig.min_val,
            "min_allowed": p_min, "max_allowed": p_max,
            "value_type": str(sig.value_type), "length": sig.length,
        }
    if sig.max_val > p_max:
        return False, f"Signal max value {sig.max_val} is above {p_max}", {
            "error_code": "signal_max_out_of_range", "type": "invalid_param",
            "field": "max_val", "value": sig.max_val,
            "min_allowed": p_min, "max_allowed": p_max,
            "value_type": str(sig.value_type), "length": sig.length,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_signal_range_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/database.py tests/test_signal_range_validation.py
git commit -m "feat(signal): validate physical range for min/max"
```

---

### Task 2: Integrity errors and error-panel display

**Files:**
- Modify: `app/models/database.py::_validate_single_message_integrity`
- Modify: `frontend/src/i18n.js`
- Modify: `frontend/src/components/DataErrorList.vue`
- Test: `tests/test_signal_range_validation.py` (append)

**Interfaces:**
- Consumes: `CanDatabase.signal_physical_range` from Task 1.
- Produces: integrity error dicts with `type` in the three codes, plus `signal_name`, `msg_key`, `msg_id`, `msg_id_hex`.

- [ ] **Step 1: Append failing integrity tests**

Append to `tests/test_signal_range_validation.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_signal_range_validation.py -k integrity -v`
Expected: FAIL — no range error types emitted.

- [ ] **Step 3: Implement integrity checks**

In `_validate_single_message_integrity`, inside the per-signal loop after the `factor_zero` block and before the float/double length check, add:

```python
if sig.factor != 0 and not (sig.min_val == 0 and sig.max_val == 0):
    if not all(math.isfinite(v) for v in (sig.factor, sig.offset, sig.min_val, sig.max_val)):
        errors.append({
            "type": "signal_min_max_invalid", **msg_ref,
            "signal_name": sig.name,
            "min_val": sig.min_val, "max_val": sig.max_val,
            "message": f"Signal '{sig.name}' min/max values must be finite",
        })
    elif sig.min_val > sig.max_val:
        errors.append({
            "type": "signal_min_max_invalid", **msg_ref,
            "signal_name": sig.name,
            "min_val": sig.min_val, "max_val": sig.max_val,
            "message": f"Signal '{sig.name}' min value exceeds max value",
        })
    else:
        p_min, p_max = self.signal_physical_range(sig)
        if sig.min_val < p_min:
            errors.append({
                "type": "signal_min_out_of_range", **msg_ref,
                "signal_name": sig.name,
                "value": sig.min_val,
                "min_allowed": p_min, "max_allowed": p_max,
                "message": (
                    f"Signal '{sig.name}' min value {sig.min_val} is below {p_min}"
                ),
            })
        if sig.max_val > p_max:
            errors.append({
                "type": "signal_max_out_of_range", **msg_ref,
                "signal_name": sig.name,
                "value": sig.max_val,
                "min_allowed": p_min, "max_allowed": p_max,
                "message": (
                    f"Signal '{sig.name}' max value {sig.max_val} is above {p_max}"
                ),
            })
```

Add the frontend copy in `frontend/src/i18n.js` next to the existing data error keys:

```javascript
'toast.validation.signal_min_max_invalid': '最小值/最大值不合法或最小值大于最大值',
'toast.validation.signal_min_out_of_range': '最小值 {value} 超出可表示物理范围 [{min_allowed}, {max_allowed}]',
'toast.validation.signal_max_out_of_range': '最大值 {value} 超出可表示物理范围 [{min_allowed}, {max_allowed}]',
'dataErrors.type.signal_min_max_invalid': '信号 \'{name}\' 的最小值/最大值不合法（最小值 {min_val}，最大值 {max_val}）',
'dataErrors.type.signal_min_out_of_range': '信号 \'{name}\' 的最小值 {value} 超出可表示范围 [{min_allowed}, {max_allowed}]',
'dataErrors.type.signal_max_out_of_range': '信号 \'{name}\' 的最大值 {value} 超出可表示范围 [{min_allowed}, {max_allowed}]',
```

In `frontend/src/components/DataErrorList.vue`, add the three types to `ERROR_ICONS`:

```javascript
  signal_min_max_invalid: '⚠',
  signal_min_out_of_range: '⚠',
  signal_max_out_of_range: '⚠',
```

Extend the `t()` payload:

```javascript
function errorDescription(err) {
  const key = `dataErrors.type.${err.type}`
  return t(key, {
    name: err.signal_name || '',
    other: err.conflicts_name || '',
    bits: (err.out_of_bounds_bits || err.overlapping_bits || []).join(','),
    max: err.max_bit ?? '',
    min_val: err.min_val ?? '',
    value: err.value ?? '',
    min_allowed: err.min_allowed ?? '',
    max_allowed: err.max_allowed ?? '',
  })
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_signal_range_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/database.py frontend/src/i18n.js frontend/src/components/DataErrorList.vue tests/test_signal_range_validation.py
git commit -m "feat(signal): report physical range errors in data integrity"
```

---

### Task 3: `fit_signal_range` WS action

**Files:**
- Modify: `app/ws/handlers/signal_handlers.py` (new handler after `EditSignalHandler`)
- Modify: `app/ws/handlers/__init__.py`
- Modify: `app/ws/router.py` (`WRITE_OPERATIONS`)
- Modify: `app/server/lifecycle.py` (import + register)
- Test: `tests/test_fit_signal_range.py` (new)

**Interfaces:**
- Consumes: `CanDatabase.signal_physical_range`, `_validate_signal_fields`, `push_data_errors`.
- Produces: WS message type `fit_signal_range` with payload `{session_id, msg_key|msg_id, sig_name}`; response `HandlerResult.data` is the updated signal dict; emits `signal_updated` + `status_changed` + `data_errors_changed`.

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_fit_signal_range.py`:

```python
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
```

Also append a batch-add regression test to `tests/test_mcp_tools_signals.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_fit_signal_range.py tests/test_mcp_tools_signals.py::test_batch_add_rejects_out_of_physical_range -v`
Expected: FAIL — unknown message type `fit_signal_range` / batch add accepts 256.

- [ ] **Step 3: Implement the handler and registration**

Add to `app/ws/handlers/signal_handlers.py` after `EditSignalHandler`:

```python
class FitSignalRangeHandler:
    """按 value_type/length/factor/offset 计算并写入 min_val/max_val。"""

    def __init__(self, session_mgr):
        self._sm = session_mgr

    def __call__(self, data: dict) -> HandlerResult:
        sid = data["session_id"]
        session = self._sm.get(sid)
        if not session:
            raise HandlerError("SESSION_NOT_FOUND", "会话不存在")

        msg_key = parse_msg_key(data.get("msg_key", data.get("msg_id")))
        sig_name = data["sig_name"]

        db = session.db
        with db.with_lock():
            msg = db.messages.get(msg_key)
            if not msg:
                raise HandlerError("MESSAGE_NOT_FOUND", f"报文 {msg_key} 不存在")
            sig = msg.signals.get(sig_name)
            if not sig:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_name} 不存在")
            if sig.factor == 0:
                raise HandlerError(
                    "VALUE_INVALID",
                    "Cannot compute range when factor is 0",
                    {"error_code": "factor_zero", "field": "factor"},
                )
            if not all(math.isfinite(v) for v in (sig.factor, sig.offset)):
                raise HandlerError(
                    "VALUE_INVALID",
                    "factor/offset must be finite",
                    {"error_code": "invalid_number", "field": "factor"},
                )

            p_min, p_max = db.signal_physical_range(sig)
            updates = {"min_val": p_min, "max_val": p_max}
            old_values = {k: getattr(sig, k) for k in updates}

            try:
                _validate_signal_fields(updates, msg, sig_name)
            except HandlerError as e:
                if e.details is not None:
                    e.details.update(old_values)
                raise

            test_sig = Signal.from_dict({**sig.to_dict(), **updates})
            ok, err, info = db.validate_signal(msg, test_sig, exclude_name=sig_name)
            if not ok:
                info = info or {}
                info.update(old_values)
                raise HandlerError("VALUE_INVALID", err, info)

            ok, _ = db.update_signal_in_message(msg_key, sig_name, **updates)
            if not ok:
                raise HandlerError("SIGNAL_NOT_FOUND", f"信号 {sig_name} 不存在")
            sig = msg.signals[sig_name]

            self._sm.push_undo(session, {
                "type": "signal_update", "msgKey": msg_key, "sigName": sig_name,
                "oldName": None, "prev": old_values, "next": updates,
            })
            new_version = db._bump_version()
            total_bits = sum(s.length for s in msg.signals.values())
            events = [
                {"type": "signal_updated",
                 "data": {"msg_key": msg_key, "signal": sig.to_dict(),
                          "old_name": None, "total_signal_bits": total_bits},
                 "data_version": new_version},
                {"type": "status_changed",
                 "data": {"modified": True,
                          "undo_count": len(session.undo_stack),
                          "redo_count": len(session.redo_stack)},
                 "data_version": new_version},
            ]
            push_data_errors(events, db, new_version, {msg_key})
            return HandlerResult(data=sig.to_dict(), events=events,
                                 new_version=new_version, session_id=sid)
```

Export it from `app/ws/handlers/__init__.py` (import list and `__all__`), add `'fit_signal_range'` to `WRITE_OPERATIONS` in `app/ws/router.py`, and in `app/server/lifecycle.py` add `FitSignalRangeHandler` to the import tuple and register:

```python
ws_router.register("fit_signal_range", FitSignalRangeHandler(session_mgr))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_fit_signal_range.py tests/test_mcp_tools_signals.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ws/handlers/signal_handlers.py app/ws/handlers/__init__.py app/ws/router.py app/server/lifecycle.py tests/test_fit_signal_range.py tests/test_mcp_tools_signals.py
git commit -m "feat(signal): add atomic auto-fit range action"
```

---

### Task 4: Frontend auto-fit button

**Files:**
- Modify: `frontend/src/stores/signals.js`
- Modify: `frontend/src/components/SignalPanel.vue`
- Modify: `frontend/src/i18n.js`

**Interfaces:**
- Consumes: WS action `fit_signal_range` from Task 3.
- Produces: `useSignalsStore().fitSignalRange(sigName: string, msgKey: string) -> Promise<void>`.

- [ ] **Step 1: Add the store action**

In `frontend/src/stores/signals.js`, after `updateSignal`:

```javascript
    /**
     * 按值类型/长度/系数/偏移自动计算并写入 min_val/max_val
     */
    async fitSignalRange(sigName, msgKey) {
      const editor = useCoreStore()
      const targetId = msgKey ?? editor.selectedMsgKey
      if (targetId == null) return
      try {
        await editor._wsRequest('fit_signal_range', {
          msg_key: targetId,
          sig_name: sigName,
        })
        editor.addLogEntry('update', `自动计算信号 ${sigName} 的最大/最小值`)
      } catch (e) {
        if (!e.message?.includes?.('Connection lost')) {
          useUiStore().showToast(translateError(e), true)
        }
        throw e
      }
    },
```

- [ ] **Step 2: Add the button and handler**

In `frontend/src/components/SignalPanel.vue`, directly after the min/max `field-row`, add:

```html
        <button
          class="btn fit-range-btn"
          :disabled="selectedSig.factor === 0"
          :title="t('panel.autoFitRangeHint')"
          @click="fitSignalRange"
        >
          {{ t('panel.autoFitRange') }}
        </button>
```

Add the function next to `updateSignal`:

```javascript
function fitSignalRange() {
  edit.commit((t) => {
    if (!t.signalName) return
    signals.fitSignalRange(t.signalName, t.msgKey).catch(() => {})
  })
}
```

Add a small scoped style rule:

```css
.fit-range-btn {
  margin-top: 4px;
}
```

- [ ] **Step 3: Add i18n copy**

In `frontend/src/i18n.js` next to `panel.signalMin` / `panel.signalMax`:

```javascript
'panel.autoFitRange': '自动计算量程',
'panel.autoFitRangeHint': '按值类型、长度、系数、偏移计算并填入最大/最小值',
```

- [ ] **Step 4: Verify the frontend builds**

Run: `cd frontend && npm run build`
Expected: build exits 0 with no Vue template or import errors.

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`
Expected: PASS (all existing tests plus the new ones).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/stores/signals.js frontend/src/components/SignalPanel.vue frontend/src/i18n.js
git commit -m "feat(ui): add auto-fit signal range button"
```