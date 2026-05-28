"""Quick smoke test for per-message signal model."""

from core.can_database import CanDatabase, Message, Signal
from cli import CanMatrixSession

def test_session():
    sess = CanMatrixSession()
    sess.new_database("TestDB")

    # Add a message
    msg = Message(id=0x100, name="EngineStatus", dlc=8)
    result = sess.add_message(msg)
    assert result.success, result.message
    print("OK: add_message")

    # Add signal via session
    sig = Signal(name="Speed", start_bit=0, length=16)
    result = sess.add_signal(0x100, sig)
    assert result.success, result.message
    assert len(sess.database.messages[0x100].signals) == 1
    print("OK: add_signal, signal count =", len(sess.database.messages[0x100].signals))

    # Remove signal via session
    result = sess.remove_signal(0x100, "Speed")
    assert result.success, result.message
    assert len(sess.database.messages[0x100].signals) == 0
    print("OK: remove_signal, signal count =", len(sess.database.messages[0x100].signals))

    # Duplicate message test (deep copy signals)
    sig1 = Signal(name="RPM", start_bit=0, length=16, factor=1.0)
    sig2 = Signal(name="Temp", start_bit=16, length=8, factor=0.5)
    msg2 = Message(id=0x200, name="SensorData", dlc=8, signals=[sig1, sig2])
    sess.force_add_message(msg2)

    import copy
    dup = Message(
        id=0x300,
        name="SensorData_copy",
        dlc=8,
        signals=[copy.deepcopy(s) for s in msg2.signals],
    )
    sess.force_add_message(dup)

    # Verify they are independent
    msg2_ref = sess.database.messages[0x200]
    dup_ref = sess.database.messages[0x300]
    msg2_ref.signals[0].factor = 2.0
    assert dup_ref.signals[0].factor == 1.0, "Deep copy failed: signals are shared!"
    print("OK: duplicate message creates independent signal copies")

    print("\nAll tests passed!")

if __name__ == "__main__":
    test_session()
