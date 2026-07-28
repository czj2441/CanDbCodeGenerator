"""validate_data_integrity 增量校验缓存单元测试。"""

import pytest
from app.models.database import CanDatabase
from app.models.message import Message
from app.models.signal import Signal


def _make_msg(msg_id: int, name: str = "TestMsg", dlc: int = 8,
              signals: list[Signal] | None = None) -> Message:
    """创建测试报文。"""
    msg = Message(id=msg_id, name=name, dlc=dlc, signals=signals or [])
    return msg


def _make_sig(name: str = "TestSig", start_bit: int = 0, length: int = 8,
              factor: float = 1.0, **kwargs) -> Signal:
    """创建测试信号。"""
    return Signal(name=name, start_bit=start_bit, length=length, factor=factor, **kwargs)


class TestFullValidateBaseline:
    """full_validate() 结果正确性基线。"""

    def test_empty_database(self):
        """空数据库应返回空错误列表。"""
        db = CanDatabase()
        errors = db.full_validate()
        assert errors == []
        assert db._validation_cache == {}

    def test_clean_message_no_errors(self):
        """无错误的报文不应产生错误。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "ECU_Msg", 8, [_make_sig("Speed", 0, 8)]))
        errors = db.full_validate()
        assert errors == []

    def test_message_name_empty(self):
        """空报文名应检测到 message_name_empty。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "", 8))
        errors = db.full_validate()
        assert len(errors) == 1
        assert errors[0]["type"] == "message_name_empty"
        assert errors[0]["msg_id"] == 0x100

    def test_factor_zero(self):
        """factor=0 应检测到 factor_zero。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [_make_sig("Sig1", factor=0)]))
        errors = db.full_validate()
        assert any(e["type"] == "factor_zero" for e in errors)

    def test_signal_name_empty(self):
        """空信号名应检测到 signal_name_empty。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [_make_sig("", 0, 8)]))
        errors = db.full_validate()
        assert any(e["type"] == "signal_name_empty" for e in errors)

    def test_signal_name_duplicate(self):
        """重复信号名应检测到 signal_name_duplicate。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [
            _make_sig("DupSig", 0, 8),
            _make_sig("DupSig", 8, 8),
        ]))
        errors = db.full_validate()
        assert any(e["type"] == "signal_name_duplicate" for e in errors)

    def test_signal_out_of_bounds(self):
        """信号越界应检测到 out_of_bounds。"""
        db = CanDatabase()
        # DLC=8 → max_bits=64，信号从 bit 60 长 8 → 位 60-67，其中 64-67 越界
        db.add_message(_make_msg(0x100, "Msg", 8, [_make_sig("BigSig", 60, 8)]))
        errors = db.full_validate()
        assert any(e["type"] == "out_of_bounds" for e in errors)

    def test_signal_length_zero(self):
        """信号 length<1 应检测到 signal_length_zero。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [_make_sig("BadSig", 0, 0)]))
        errors = db.full_validate()
        assert any(e["type"] == "signal_length_zero" for e in errors)

    def test_signal_overlap(self):
        """信号重叠应检测到 overlap。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [
            _make_sig("Sig1", 0, 8),
            _make_sig("Sig2", 4, 8),  # 位 4-11 与 Sig1 的 0-7 重叠
        ]))
        errors = db.full_validate()
        assert any(e["type"] == "overlap" for e in errors)

    def test_cache_rebuilt_on_full_validate(self):
        """full_validate() 后缓存应完全重建。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [_make_sig("S", factor=0)]))
        # 先填充缓存
        db.full_validate()
        assert 0x100 in db._validation_cache
        assert len(db._validation_cache[0x100]) == 1  # factor_zero

        # 修复错误后全量扫描应重建缓存
        db.messages[0x100].signals[0].factor = 1.0
        errors = db.full_validate()
        assert errors == []
        assert db._validation_cache[0x100] == []


class TestIncrementalValidation:
    """增量校验 vs 全量校验结果一致性。"""

    def test_incremental_after_signal_edit(self):
        """编辑信号后增量结果 == full_validate() 结果。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S1", 0, 8)]))
        db.add_message(_make_msg(0x200, "Msg2", 8, [_make_sig("S2", 0, 8)]))
        # 初始化缓存
        db.full_validate()

        # 编辑信号：设置 factor=0 制造错误
        db.messages[0x100].signals[0].factor = 0
        incremental = db.validate_data_integrity({0x100})
        full = db.full_validate()
        assert _error_types(incremental) == _error_types(full)

    def test_incremental_after_signal_add(self):
        """添加信号后增量结果 == full_validate() 结果。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S1", 0, 8)]))
        db.add_message(_make_msg(0x200, "Msg2", 8))
        db.full_validate()

        # 添加重叠信号
        new_sig = _make_sig("Overlap", 4, 8)
        db.messages[0x100].signals.append(new_sig)
        incremental = db.validate_data_integrity({0x100})
        full = db.full_validate()
        assert _error_types(incremental) == _error_types(full)

    def test_incremental_after_message_edit(self):
        """编辑报文属性后增量结果 == full_validate() 结果。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S1", 0, 8)]))
        db.full_validate()

        # 清空报文名
        db.messages[0x100].name = ""
        incremental = db.validate_data_integrity({0x100})
        full = db.full_validate()
        assert _error_types(incremental) == _error_types(full)
        assert any(e["type"] == "message_name_empty" for e in incremental)

    def test_incremental_multiple_messages(self):
        """多报文增量校验结果 == full_validate()。"""
        db = CanDatabase()
        for i in range(10):
            db.add_message(_make_msg(0x100 + i, f"Msg{i}", 8, [_make_sig(f"S{i}", 0, 8)]))
        db.full_validate()

        # 修改多个报文
        db.messages[0x100].signals[0].factor = 0
        db.messages[0x105].name = ""
        incremental = db.validate_data_integrity({0x100, 0x105})
        full = db.full_validate()
        assert _error_types(incremental) == _error_types(full)


class TestFallbackOnDeletedMsgId:
    """传入不存在的 msg_id 应自动回退 full_validate()。"""

    def test_fallback_single_deleted_id(self):
        """传入已删除的 msg_id → 自动回退。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8))
        db.add_message(_make_msg(0x200, "Msg2", 8))
        db.full_validate()

        # 删除 0x100
        db.remove_message(0x100)

        # 传入已删除的 ID → issubset 失败 → 回退全量
        errors = db.validate_data_integrity({0x100, 0x200})
        # 应该等于 full_validate 结果
        full = db.full_validate()
        assert _error_types(errors) == _error_types(full)
        # 0x100 不应出现在结果中
        assert not any(e.get("msg_id") == 0x100 for e in errors)

    def test_fallback_only_deleted_id(self):
        """仅传入已删除的 ID → 回退后返回其他报文结果。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S", factor=0)]))
        db.add_message(_make_msg(0x200, "Msg2", 8))
        db.full_validate()

        db.remove_message(0x100)
        errors = db.validate_data_integrity({0x100})
        # 回退全量扫描，结果应只含 0x200（无错误）
        assert errors == []

    def test_no_fallback_for_existing_id(self):
        """传入存在的 msg_id 不应回退。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S", factor=0)]))
        db.add_message(_make_msg(0x200, "Msg2", 8, [_make_sig("S2", 0, 8)]))
        db.full_validate()

        # 修改 0x200
        db.messages[0x200].signals[0].factor = 0  # 制造错误
        # 仅传 0x200（存在）→ 增量模式
        errors = db.validate_data_integrity({0x200})
        assert any(e["type"] == "factor_zero" and e["msg_id"] == 0x200 for e in errors)


class TestCacheConsistency:
    """缓存一致性测试。"""

    def test_incremental_then_full_validate_same_result(self):
        """增量后立即全量扫描，结果应一致。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S", 0, 8)]))
        db.full_validate()

        db.messages[0x100].signals[0].factor = 0
        incremental = db.validate_data_integrity({0x100})
        full = db.full_validate()
        assert _error_types(incremental) == _error_types(full)

    def test_cache_empty_first_call(self):
        """首次调用（缓存为空）增量模式应正确工作。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S", factor=0)]))
        # 不调 full_validate，直接增量
        errors = db.validate_data_integrity({0x100})
        assert any(e["type"] == "factor_zero" for e in errors)

    def test_unaffected_messages_use_cache(self):
        """未受影响的报文应使用缓存，不重新计算。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg1", 8, [_make_sig("S1", 0, 8)]))
        db.add_message(_make_msg(0x200, "Msg2", 8, [_make_sig("S2", factor=0)]))
        # 初始化缓存
        db.full_validate()
        cached_200 = db._validation_cache[0x200]
        assert any(e["type"] == "factor_zero" for e in cached_200)

        # 仅增量 0x100
        errors = db.validate_data_integrity({0x100})
        # 0x200 的错误应来自缓存（仍然存在）
        assert any(e["type"] == "factor_zero" and e["msg_id"] == 0x200 for e in errors)

    def test_validate_for_dbc_export_uses_full_validate(self):
        """validate_for_dbc_export() 应使用 full_validate()。"""
        db = CanDatabase()
        db.add_message(_make_msg(0x100, "Msg", 8, [_make_sig("S", factor=0)]))
        db.full_validate()
        # 修复
        db.messages[0x100].signals[0].factor = 1.0
        # 缓存仍有旧的 factor_zero 错误
        # 但 full_validate 应返回空
        export_errors = db.validate_for_dbc_export()
        assert export_errors == []


def _error_types(errors: list[dict]) -> set[tuple]:
    """提取错误类型+msg_id 的集合，用于比较。"""
    return {(e["type"], e.get("msg_id")) for e in errors}
