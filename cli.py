"""CLI / headless interface for CanMatrix Editor.

All operations that the GUI can perform are exposed here as a plain
Python API, enabling unit tests, integration tests, and batch scripts
without ever launching a window.
"""

from __future__ import annotations

import os

from models import CanDatabase, Message, Signal
from core.dbc_io import import_dbc, export_dbc
from core.json_io import load_json, save_json
from core.properties_io import load_properties, save_properties
from core.xml_io import load_xml, save_xml


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class OpResult:
    """Outcome of a single operation (add/edit/delete/load/save)."""

    def __init__(self, success: bool, message: str = "", data: object = None):
        self.success = success
        self.message = message
        self.data = data

    @staticmethod
    def ok(msg: str = "", data: object = None) -> OpResult:
        return OpResult(True, msg, data)

    @staticmethod
    def fail(msg: str) -> OpResult:
        return OpResult(False, msg)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class CanMatrixSession:
    """Headless session that mirrors the MainWindow's state and actions.

    Every public method corresponds to exactly one user-facing operation
    in the GUI.
    """

    def __init__(self) -> None:
        self.database: CanDatabase = CanDatabase()
        self.current_filepath: str | None = None
        self._modified: bool = False

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def new_database(self, name: str = "Untitled") -> OpResult:
        self.database = CanDatabase(name)
        self.current_filepath = None
        self._modified = False
        return OpResult.ok(f"New database '{name}' created.")

    def open_file(self, filepath: str) -> OpResult:
        if not os.path.isfile(filepath):
            return OpResult.fail(f"File not found: {filepath}")

        ext = os.path.splitext(filepath)[1].lower()
        try:
            if ext == ".properties":
                self.database = load_properties(filepath)
            elif ext == ".json":
                self.database = load_json(filepath)
            elif ext == ".xml":
                self.database = load_xml(filepath)
            elif ext == ".dbc":
                self.database = import_dbc(filepath)
            else:
                return OpResult.fail(f"Unsupported format: {ext}")
        except Exception as exc:
            return OpResult.fail(f"Failed to open {filepath}: {exc}")

        self.current_filepath = filepath
        total_sigs = sum(len(m.signals) for m in self.database.messages.values())
        self._modified = False
        return OpResult.ok(
            f"Opened {os.path.basename(filepath)} "
            f"({len(self.database.messages)} messages, "
            f"{total_sigs} signals)."
        )

    def save(self, filepath: str | None = None) -> OpResult:
        target = filepath or self.current_filepath
        if target is None:
            target = "untitled.properties"
        try:
            save_properties(self.database, target)
        except Exception as exc:
            return OpResult.fail(f"Save failed: {exc}")
        self.current_filepath = target
        self._modified = False
        return OpResult.ok(f"Saved to {os.path.basename(target)}.")

    def save_as(self, filepath: str, fmt: str = "properties") -> OpResult:
        try:
            if fmt == "json":
                save_json(self.database, filepath)
            elif fmt == "xml":
                save_xml(self.database, filepath)
            else:
                save_properties(self.database, filepath)
        except Exception as exc:
            return OpResult.fail(f"Save as {fmt} failed: {exc}")
        return OpResult.ok(f"Saved as {os.path.basename(filepath)}.")

    def export_dbc(self, filepath: str) -> OpResult:
        try:
            export_dbc(self.database, filepath)
        except Exception as exc:
            return OpResult.fail(f"Export DBC failed: {exc}")
        return OpResult.ok(f"Exported to {os.path.basename(filepath)}.")

    # ------------------------------------------------------------------
    # Message CRUD
    # ------------------------------------------------------------------

    def add_message(self, msg: Message) -> OpResult:
        if msg.id in self.database.messages:
            return OpResult.fail(
                f"Message ID 0x{msg.id:X} already exists."
            )
        self.database.add_message(msg)
        self._modified = True
        return OpResult.ok(f"Added message 0x{msg.id:X} '{msg.name}'.")

    def force_add_message(self, msg: Message) -> OpResult:
        existed = msg.id in self.database.messages
        self.database.add_message(msg)
        self._modified = True
        action = "Overwrote" if existed else "Added"
        return OpResult.ok(f"{action} message 0x{msg.id:X} '{msg.name}'.")

    def remove_message(self, msg_id: int) -> OpResult:
        msg = self.database.remove_message(msg_id)
        if msg is None:
            return OpResult.fail(f"Message 0x{msg_id:X} not found.")
        self._modified = True
        return OpResult.ok(f"Removed message 0x{msg_id:X} '{msg.name}'.")

    def update_message(self, msg_id: int, **kwargs) -> OpResult:
        ok = self.database.update_message(msg_id, **kwargs)
        if not ok:
            return OpResult.fail(f"Message 0x{msg_id:X} not found.")
        self._modified = True
        return OpResult.ok(f"Updated message 0x{msg_id:X}.")

    def get_message(self, msg_id: int) -> Message | None:
        return self.database.get_message(msg_id)

    def list_messages(self) -> list[Message]:
        return sorted(self.database.messages.values(), key=lambda m: m.id)

    # ------------------------------------------------------------------
    # Signal CRUD  (per-message)
    # ------------------------------------------------------------------

    def add_signal(self, msg_id: int, sig: Signal) -> OpResult:
        """Add a signal to a message."""
        ok = self.database.add_signal_to_message(msg_id, sig)
        if not ok:
            return OpResult.fail(f"Message 0x{msg_id:X} not found.")
        self._modified = True
        return OpResult.ok(f"Added signal '{sig.name}' to 0x{msg_id:X}.")

    def remove_signal(self, msg_id: int, sig_name: str) -> OpResult:
        """Remove a signal from a message by name."""
        ok = self.database.remove_signal_from_message(msg_id, sig_name)
        if not ok:
            return OpResult.fail(
                f"Signal '{sig_name}' not found in 0x{msg_id:X}."
            )
        self._modified = True
        return OpResult.ok(f"Removed signal '{sig_name}' from 0x{msg_id:X}.")

    def update_signal(self, msg_id: int, sig_name: str, **kwargs) -> OpResult:
        """Update a signal's attributes directly on the message."""
        msg = self.database.messages.get(msg_id)
        if msg is None:
            return OpResult.fail(f"Message 0x{msg_id:X} not found.")
        for sig in msg.signals:
            if sig.name == sig_name:
                for key, value in kwargs.items():
                    if hasattr(sig, key):
                        setattr(sig, key, value)
                self._modified = True
                return OpResult.ok(f"Updated signal '{sig_name}' in 0x{msg_id:X}.")
        return OpResult.fail(
            f"Signal '{sig_name}' not found in 0x{msg_id:X}."
        )

    def list_signals(self, msg_id: int) -> list[Signal] | None:
        """Return Signal objects for a message."""
        sigs = self.database.get_signals_for_message(msg_id)
        if self.database.messages.get(msg_id) is None:
            return None
        return sigs

    def list_all_signals(self) -> list[Signal]:
        """Return all signals across all messages, sorted by name."""
        all_sigs: list[Signal] = []
        for msg in self.database.messages.values():
            all_sigs.extend(msg.signals)
        return sorted(all_sigs, key=lambda s: s.name)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_modified(self) -> bool:
        return self._modified

    @property
    def message_count(self) -> int:
        return len(self.database.messages)

    def total_signal_count(self) -> int:
        """Count all signals across all messages."""
        return sum(len(msg.signals) for msg in self.database.messages.values())

    def summary(self) -> str:
        lines = [
            f"Database: {self.database.name}",
            f"File:     {self.current_filepath or '(unsaved)'}",
            f"Messages: {self.message_count}",
            f"Signals:  {self.total_signal_count()} (total across messages)",
            f"Modified: {self._modified}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    sess = CanMatrixSession()
    print(sess.summary())

    if len(sys.argv) > 1:
        result = sess.open_file(sys.argv[1])
        print(result.message)
        print()
        for msg in sess.list_messages():
            print(f"  0x{msg.id:04X}  {msg.name:<30s}  DLC={msg.dlc}  signals={len(msg.signals)}")
            for sig in msg.signals:
                print(f"    └─ {sig.name}  start={sig.start_bit}  len={sig.length}  "
                      f"{sig.byte_order}  factor={sig.factor}  unit={sig.unit}")