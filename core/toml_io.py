"""TOML format read / write -- primary storage format.

TOML is chosen for its human readability, diff-friendliness, and excellent
Git version-control compatibility.

Storage layout (per-message nested signals)::

    [database]
    name = "MyProject"

    [[messages]]
    id = 0x100
    name = "EngineStatus"
    dlc = 8

      [[messages.signals]]
      name = "RPM"
      start_bit = 0
      length = 16
      ...
"""

from __future__ import annotations

import os

import toml

from models import CanDatabase, Message, Signal


def save_toml(database: CanDatabase, filepath: str) -> None:
    """Serialize a CanDatabase to a TOML file.

    Signals are nested inside each message's [[messages]] table.
    """
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    lines: list[str] = []

    # Header
    lines.append("# CanMatrix Editor - CAN Database Definition")
    lines.append("")
    lines.append("[database]")
    lines.append(f'name = "{database.name}"')
    lines.append("")

    # Messages (sorted by CAN ID)
    for msg in sorted(database.messages.values(), key=lambda m: m.id):
        lines.append("[[messages]]")
        lines.append(f"id = 0x{msg.id:X}")
        lines.append(f'name = "{msg.name}"')
        lines.append(f"dlc = {msg.dlc}")
        if msg.cycle_time > 0:
            lines.append(f"cycle_time = {msg.cycle_time}")
        if msg.sender:
            lines.append(f'sender = "{msg.sender}"')
        if msg.comment:
            lines.append(f'comment = "{msg.comment}"')
        # Signals as nested array of tables
        if msg.signals:
            lines.append("")
            for sig in msg.signals:
                lines.append("  [[messages.signals]]")
                lines.append(f'    name = "{sig.name}"')
                lines.append(f"    start_bit = {sig.start_bit}")
                lines.append(f"    length = {sig.length}")
                lines.append(f'    byte_order = "{sig.byte_order}"')
                lines.append(f"    is_signed = {str(sig.is_signed).lower()}")
                if sig.factor != 1.0:
                    lines.append(f"    factor = {_format_float(sig.factor)}")
                if sig.offset != 0.0:
                    lines.append(f"    offset = {_format_float(sig.offset)}")
                if sig.min_val != 0.0:
                    lines.append(f"    min_val = {_format_float(sig.min_val)}")
                if sig.max_val != 0.0:
                    lines.append(f"    max_val = {_format_float(sig.max_val)}")
                if sig.unit:
                    lines.append(f'    unit = "{sig.unit}"')
                if sig.comment:
                    lines.append(f'    comment = "{sig.comment}"')
                if sig.receivers:
                    recv = ", ".join(sig.receivers)
                    lines.append(f'    receivers = ["{recv}"]')
                if sig.multiplexer_mode != "none":
                    lines.append(f'    multiplexer_mode = "{sig.multiplexer_mode}"')
                    if sig.multiplexer_mode == "multiplexed":
                        lines.append(f"    multiplexer_value = {sig.multiplexer_value}")
                lines.append("")
        else:
            lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _format_float(value: float) -> str:
    """Format float without trailing zeros for clean TOML output."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def load_toml(filepath: str) -> CanDatabase:
    """Load a CanDatabase from a TOML file.

    Supports nested signals inside [[messages.signals]] tables.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"TOML file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = toml.load(f)

    return CanDatabase.from_toml_dict(data)