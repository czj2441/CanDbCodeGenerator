"""DBC 属性策略、扩展帧身份与浮点信号测试。"""

import pytest

from app.models import CanDatabase, Message, Signal
from app.models.signal import SignalValueType
from app.models.can_id import (
    CanIdError,
    format_id,
    parse_key,
    parse_ref,
    to_key,
    validate_id,
)

SAMPLE_DBC = '''VERSION ""

NS_ :
\tCM_
\tBA_DEF_
\tBA_
\tVAL_
\tSIG_GROUP_
\tSIG_VALTYPE_

BS_:

BU_: ECU1 ECU2

BO_ 256 StdMsg: 8 ECU1
 SG_ SigA : 0|8@1+ (1,0) [0|255] "" ECU2
 SG_ Flt : 8|32@1- (1,0) [0|0] "" ECU2
BO_ 2147483904 ExtMsg: 8 ECU2
 SG_ SigB : 0|8@1+ (1,0) [0|255] "" ECU1

BO_TX_BU_ 256 : ECU1,ECU2;
SIG_GROUP_ 256 Group1 1 : SigA;

BA_DEF_ "BusType" STRING ;
BA_DEF_ "Baudrate" INT 0 1000000;
BA_DEF_ BO_ "GenMsgSendType" ENUM "Cyclic","Event";
BA_DEF_ BO_ "GenMsgCycleTime" INT 0 10000;
BA_DEF_ BO_ "VFrameFormat" ENUM "StandardCAN","ExtendedCAN","reserved","StandardCAN_FD","ExtendedCAN_FD";
BA_DEF_ SG_ "GenSigStartValue" INT 0 100000;
BA_DEF_ SG_ "SystemSignalLongSymbol" STRING ;
BA_DEF_DEF_ "BusType" "CAN";
BA_DEF_DEF_ "GenMsgSendType" "Cyclic";
BA_DEF_DEF_ "GenMsgCycleTime" 0;
BA_DEF_DEF_ "VFrameFormat" "StandardCAN";
BA_ "BusType" "CAN FD";
BA_ "Baudrate" 500000;
BA_ "GenMsgSendType" BO_ 256 0;
BA_ "GenMsgCycleTime" BO_ 256 100;
BA_ "VFrameFormat" BO_ 256 0;
BA_ "GenSigStartValue" SG_ 256 SigA 12;

SIG_VALTYPE_ 256 Flt : 1;
'''


def _warning_names(db: CanDatabase) -> set[str]:
    return {w["name"] for w in db.import_warnings}


class TestCanId:
    def test_key_roundtrip(self):
        assert to_key(0x100, False) == "0x100:std"
        assert to_key(0x100, True) == "0x100:ext"
        assert parse_key("0x100:std") == (0x100, False)
        assert parse_key("0x100:ext") == (0x100, True)

    def test_parse_ref_legacy(self):
        assert parse_ref(0x100) == (0x100, False)
        assert parse_ref("0x100") == (0x100, False)
        assert parse_ref("0x100:ext") == (0x100, True)
        assert parse_ref(0x12345) == (0x12345, True)

    def test_range_validation(self):
        validate_id(0x7FF, False)
        validate_id(0x1FFFFFFF, True)
        for can_id, extended in ((0x800, False), (0x20000000, True)):
            try:
                validate_id(can_id, extended)
            except CanIdError:
                pass
            else:
                raise AssertionError("expected CanIdError")

    def test_format_id(self):
        assert format_id(0x100) == "0x100"


class TestMessageIdentity:
    def test_standard_and_extended_same_numeric_id_coexist(self):
        db = CanDatabase()
        db.add_message(Message(can_id=0x100, name="Std"))
        db.add_message(Message(can_id=0x100, name="Ext", is_extended_frame=True))
        assert set(db.messages) == {"0x100:std", "0x100:ext"}
        assert db.messages["0x100:ext"].name == "Ext"

    def test_message_roundtrip_dict(self):
        msg = Message(can_id=0x100, name="M", is_extended_frame=True)
        restored = Message.from_dict(msg.to_dict())
        assert restored.key == "0x100:ext"
        assert restored.can_id == 0x100

    def test_legacy_int_id(self):
        restored = Message.from_dict({"id": 0x100, "name": "Legacy"})
        assert restored.key == "0x100:std"

    def test_move_message_between_frame_types(self):
        db = CanDatabase()
        db.add_message(Message(can_id=0x100, name="M"))
        moved = db.move_message("0x100:std", 0x100, True)
        assert moved == "0x100:ext"
        assert set(db.messages) == {"0x100:ext"}
        assert db.messages["0x100:ext"].is_extended_frame is True

    def test_move_message_conflict(self):
        db = CanDatabase()
        db.add_message(Message(can_id=0x100, name="Std"))
        db.add_message(Message(can_id=0x100, name="Ext", is_extended_frame=True))
        assert db.move_message("0x100:std", 0x100, True) is None
        assert set(db.messages) == {"0x100:std", "0x100:ext"}

    def test_validate_message_fields_rejects_std_overflow(self):
        db = CanDatabase()
        db.add_message(Message(can_id=0x100, name="M"))
        ok, _, info = db.validate_message_fields("0x100:std", {"id": 0x800})
        assert ok is False
        assert info["error_code"] == "message_id_out_of_range"


class TestDbcAttributes:
    def test_import_adopted_and_warnings(self):
        db = CanDatabase.from_dbc_str(SAMPLE_DBC)
        assert set(db.messages) == {"0x100:std", "0x100:ext"}
        assert db.bus_type == "CAN FD"
        assert db.messages["0x100:std"].cycle_time == 100
        assert db.messages["0x100:ext"].is_extended_frame is True
        assert db.messages["0x100:std"].signals["Flt"].is_float is True
        assert db.messages["0x100:std"].signals["Flt"].is_signed is False

        names = _warning_names(db)
        assert "GenMsgSendType" in names
        assert "Baudrate" in names
        assert "GenSigStartValue" in names
        assert "BO_TX_BU_" in names
        assert "SIG_GROUP_" in names
        # 标准帧与扩展帧共用数值 ID 不是重复报文
        assert "message_duplicate" not in {w["code"] for w in db.import_warnings}
        # 长名符号按决策静默接受
        assert "SystemSignalLongSymbol" not in names

    def test_export_roundtrip_and_whitelist(self):
        db = CanDatabase.from_dbc_str(SAMPLE_DBC)
        content = db.to_dbc_str()

        assert "CANFD_BRS" not in content
        assert "GenMsgSendType" not in content
        assert "GenSigStartValue" not in content
        assert 'BA_ "Baudrate"' not in content

        restored = CanDatabase.from_dbc_str(content)
        assert set(restored.messages) == {"0x100:std", "0x100:ext"}
        assert restored.bus_type == "CAN FD"
        assert restored.messages["0x100:std"].signals["Flt"].is_float is True

    def test_invalid_float_length_is_downgraded(self):
        content = SAMPLE_DBC.replace("SIG_VALTYPE_ 256 Flt : 1;", "SIG_VALTYPE_ 256 SigA : 1;")
        db = CanDatabase.from_dbc_str(content)
        sig = db.messages["0x100:std"].signals["SigA"]
        assert sig.is_float is False
        assert "SIG_VALTYPE_" in _warning_names(db)

    def test_bus_type_inferred_when_missing(self):
        content = SAMPLE_DBC.replace(
            'BA_ "BusType" "CAN FD";', ""
        ).replace(
            'BA_ "VFrameFormat" BO_ 256 0;', 'BA_ "VFrameFormat" BO_ 256 3;'
        )
        db = CanDatabase.from_dbc_str(content)
        assert db.bus_type == "CAN FD"
        assert "BusType" in _warning_names(db)

    def test_extended_frame_from_vframe_format_without_bit31(self):
        content = SAMPLE_DBC.replace(
            "BO_ 2147483904 ExtMsg", "BO_ 257 ExtMsg"
        ).replace(
            'BA_ "VFrameFormat" BO_ 256 0;',
            'BA_ "VFrameFormat" BO_ 256 0;\nBA_ "VFrameFormat" BO_ 257 1;',
        )
        # 移除不含 VFrameFormat 的扩展帧原始定义，避免重复
        content = content.replace(
            "BO_ 257 ExtMsg: 8 ECU2", "BO_ 257 ExtMsg: 8 ECU2"
        )
        db = CanDatabase.from_dbc_str(content)
        assert "0x101:ext" in db.messages
        assert db.messages["0x101:ext"].is_extended_frame is True

    def test_properties_roundtrip_and_legacy_key(self):
        db = CanDatabase.from_dbc_str(SAMPLE_DBC)
        props = db.to_properties_str()
        assert "messages.0x100" in props
        restored = CanDatabase.from_properties_str(props)
        assert set(restored.messages) == {"0x100:std", "0x100:ext"}
        assert restored.messages["0x100:std"].signals["Flt"].is_float is True

        legacy = (
            "database.name=Old\n"
            "messages.0x100.name=LegacyMsg\n"
            "messages.0x100.dlc=8\n"
        )
        old_db = CanDatabase.from_properties_str(legacy)
        assert set(old_db.messages) == {"0x100:std"}

    def test_duplicate_message_is_reported(self):
        content = '''VERSION ""

NS_ :
BS_:
BU_: ECU1

BO_ 256 First: 8 ECU1
 SG_ A : 0|8@1+ (1,0) [0|255] "" ECU1
BO_ 256 Second: 8 ECU1
 SG_ B : 0|8@1+ (1,0) [0|255] "" ECU1
'''
        db = CanDatabase.from_dbc_str(content)

        duplicates = [
            w for w in db.import_warnings if w["code"] == "message_duplicate"
        ]
        assert len(duplicates) == 1
        assert duplicates[0]["count"] == 1
        assert "First / Second (0x100:std)" in duplicates[0]["examples"]
        # cantools 保留后声明的报文，导入提示必须让用户知道前者被覆盖
        assert list(db.messages) == ["0x100:std"]
        assert db.messages["0x100:std"].name == "Second"

    def test_properties_always_persist_value_type(self):
        db = CanDatabase()
        cases = [
            (0x100, SignalValueType.UINT, 8),
            (0x101, SignalValueType.INT, 8),
            (0x102, SignalValueType.FLOAT, 32),
            (0x103, SignalValueType.DOUBLE, 64),
        ]
        for can_id, value_type, length in cases:
            db.add_message(Message(
                can_id=can_id,
                name=f"Msg{value_type.value}",
                signals={"S": Signal(
                    name="S", start_bit=0, length=length, value_type=value_type,
                )},
            ))

        props = db.to_properties_str()
        for value_type in ("uint", "int", "float", "double"):
            assert f".value_type={value_type}" in props

        restored = CanDatabase.from_properties_str(props)
        restored_types = {
            msg.signals["S"].value_type for msg in restored.messages.values()
        }
        assert restored_types == {
            SignalValueType.UINT,
            SignalValueType.INT,
            SignalValueType.FLOAT,
            SignalValueType.DOUBLE,
        }


class TestSignalValidation:
    def test_value_type_enum(self):
        sig = Signal.from_dict({"name": "V", "length": 64, "value_type": "double"})
        assert sig.value_type is SignalValueType.DOUBLE
        assert sig.is_float is True
        assert sig.is_signed is False
        assert sig.float_bits == 64
        assert str(SignalValueType.UINT) == "uint"
        assert str(SignalValueType.FLOAT) == "float"

        with pytest.raises(ValueError):
            Signal.from_dict({"name": "Bad", "value_type": "bool"})

    def test_float_requires_valid_length(self):
        db = CanDatabase()
        msg = Message(can_id=0x100, name="M", is_extended_frame=False)
        db.add_message(msg)
        sig = Signal(name="F", start_bit=0, length=8, value_type=SignalValueType.FLOAT)
        ok, err, _ = db.validate_signal(msg, sig)
        assert ok is False
        assert "float" in err.lower() or "32" in err

    def test_errors_include_msg_key(self):
        db = CanDatabase()
        db.add_message(Message(can_id=0x100, name="", is_extended_frame=False))
        errors = db.full_validate()
        assert errors
        assert errors[0]["msg_key"] == "0x100:std"
        assert errors[0]["msg_id"] == 0x100

class TestCCodeGen:
    def test_autosar_extended_id_mask_and_unique_identifiers(self):
        db = CanDatabase()
        db.add_message(Message(
            can_id=0x100, name="Std",
            signals={"A": Signal(name="A", start_bit=0, length=8, byte_order="intel")},
        ))
        db.add_message(Message(
            can_id=0x100, name="Ext", is_extended_frame=True,
            signals={"B": Signal(name="B", start_bit=0, length=8, byte_order="intel")},
        ))

        header = db.to_c_header_str()
        source = db.to_c_source_str()

        assert "#define CANCOM_USERDEF_0X100_ID" in header
        assert "#define CANCOM_USERDEF_0X80000100_ID" in header
        assert header.count("#define CANCOM_USERDEF_0X100_ID") == 1
        assert "2147483904" in header
        assert "CanCom_UserDef_0x80000100_Signals" in source
        assert "CanCom_UserDef_0x100_Signals" in source
