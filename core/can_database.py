"""Core data model for CAN database management.

DBC semantics: signals are per-message definitions. Each message has its own
signal list, and signals with the same name in different messages can have
completely different attributes (start bit, length, scaling, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A single CAN signal definition (per-message entity)."""

    name: str = ""
    start_bit: int = 0
    length: int = 8
    byte_order: str = "little_endian"  # "little_endian" | "big_endian"
    is_signed: bool = False
    factor: float = 1.0
    offset: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    unit: str = ""
    comment: str = ""
    receivers: list[str] = field(default_factory=list)
    multiplexer_mode: str = "none"  # "none" | "multiplexer" | "multiplexed"
    multiplexer_value: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "start_bit": self.start_bit,
            "length": self.length,
            "byte_order": self.byte_order,
            "is_signed": self.is_signed,
            "factor": self.factor,
            "offset": self.offset,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "unit": self.unit,
            "comment": self.comment,
            "receivers": self.receivers[:],
            "multiplexer_mode": self.multiplexer_mode,
            "multiplexer_value": self.multiplexer_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        """Create a Signal from a dict."""
        return cls(
            name=str(data.get("name", "")),
            start_bit=int(data.get("start_bit", 0)),
            length=int(data.get("length", 8)),
            byte_order=str(data.get("byte_order", "little_endian")),
            is_signed=bool(data.get("is_signed", False)),
            factor=float(data.get("factor", 1.0)),
            offset=float(data.get("offset", 0.0)),
            min_val=float(data.get("min_val", 0.0)),
            max_val=float(data.get("max_val", 0.0)),
            unit=str(data.get("unit", "")),
            comment=str(data.get("comment", "")),
            receivers=list(data.get("receivers", [])),
            multiplexer_mode=str(data.get("multiplexer_mode", "none")),
            multiplexer_value=int(data.get("multiplexer_value", 0)),
        )


@dataclass
class Message:
    """A CAN message with its own signal definitions."""

    id: int = 0
    name: str = ""
    dlc: int = 8
    cycle_time: int = 0  # ms, 0 = event-triggered
    comment: str = ""
    sender: str = ""
    signals: list[Signal] = field(default_factory=list)  # signal objects

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (signals as dicts)."""
        return {
            "id": self.id,
            "name": self.name,
            "dlc": self.dlc,
            "cycle_time": self.cycle_time,
            "comment": self.comment,
            "sender": self.sender,
            "signals": [sig.to_dict() for sig in self.signals],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create a Message from a dict.  *signals* is a list of dicts."""
        return cls(
            id=int(data.get("id", 0)),
            name=str(data.get("name", "")),
            dlc=int(data.get("dlc", 8)),
            cycle_time=int(data.get("cycle_time", 0)),
            comment=str(data.get("comment", "")),
            sender=str(data.get("sender", "")),
            signals=[Signal.from_dict(sig_data) for sig_data in data.get("signals", [])],
        )


# ---------------------------------------------------------------------------
# CanDatabase
# ---------------------------------------------------------------------------

class CanDatabase:
    """Top-level CAN database.

    Signals are per-message definitions. No global signal registry.
    """

    def __init__(self, name: str = "Untitled") -> None:
        self.name: str = name
        self.messages: dict[int, Message] = {}

    # -- Message CRUD --------------------------------------------------------

    def add_message(self, msg: Message) -> None:
        """Add or replace a message keyed by its CAN ID."""
        self.messages[msg.id] = msg

    def remove_message(self, msg_id: int) -> Message | None:
        """Remove a message.  Does *not* delete signal definitions."""
        return self.messages.pop(msg_id, None)

    def get_message(self, msg_id: int) -> Message | None:
        """Retrieve a message by CAN ID."""
        return self.messages.get(msg_id)

    def update_message(self, msg_id: int, **kwargs: Any) -> bool:
        """Update message attributes by keyword."""
        msg = self.messages.get(msg_id)
        if msg is None:
            return False
        for key, value in kwargs.items():
            if hasattr(msg, key):
                setattr(msg, key, value)
        return True

    # -- Signal ↔ Message linking -------------------------------------------

    def add_signal_to_message(self, msg_id: int, sig: Signal) -> bool:
        """Append a signal to a message. No dedup — DBC allows same-name
        signals with different attributes in different messages."""
        msg = self.messages.get(msg_id)
        if msg is None:
            return False
        msg.signals.append(sig)
        return True

    def remove_signal_from_message(self, msg_id: int, sig_name: str) -> bool:
        """Remove a signal by name from one message. Removes only the first match."""
        msg = self.messages.get(msg_id)
        if msg is None:
            return False
        for idx, sig in enumerate(msg.signals):
            if sig.name == sig_name:
                msg.signals.pop(idx)
                return True
        return False

    def get_signals_for_message(self, msg_id: int) -> list[Signal]:
        """Return Signal objects for a message, in order."""
        msg = self.messages.get(msg_id)
        if msg is None:
            return []
        return msg.signals[:]

    # -- Serialization helpers -----------------------------------------------

    def to_toml_dict(self) -> dict[str, Any]:
        """Produce a TOML-friendly dict. Signals are nested inside messages."""
        return {
            "database": {"name": self.name},
            "messages": [
                msg.to_dict()
                for msg in sorted(self.messages.values(), key=lambda m: m.id)
            ],
        }

    @classmethod
    def from_toml_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """Build CanDatabase from a parsed TOML dict."""
        db_info = data.get("database", {})
        db = cls(name=str(db_info.get("name", "Untitled")))

        # Messages (signals field is a list of dicts)
        for msg_data in data.get("messages", []):
            msg = Message.from_dict(msg_data)
            db.messages[msg.id] = msg

        return db

    def to_json_dict(self) -> dict[str, Any]:
        """Produce a JSON-friendly dict (same structure as TOML)."""
        return self.to_toml_dict()

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """Build CanDatabase from a parsed JSON dict."""
        return cls.from_toml_dict(data)

    def to_xml_dict(self) -> dict[str, Any]:
        """Produce dict structure suitable for XML serialization."""
        return self.to_toml_dict()

    @classmethod
    def from_xml_dict(cls, data: dict[str, Any]) -> CanDatabase:
        """Build CanDatabase from a parsed XML dict."""
        return cls.from_toml_dict(data)