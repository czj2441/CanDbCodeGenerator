"""DBC import / export using the cantools library."""

from __future__ import annotations

import logging
import os
from typing import Any

import cantools
import cantools.database
from cantools.database.conversion import (
    IdentityConversion,
    LinearConversion,
)

from app.models import (
    CanDatabase,
    Message,
    Signal,
)

logger = logging.getLogger(__name__)


def import_dbc(filepath: str) -> CanDatabase:
    """Load a DBC file and convert it to the internal CanDatabase model.

    Signals are per-message — same name in different messages can have
    different attributes (DBC semantics).
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"DBC file not found: {filepath}")

    logger.info("Importing DBC: %s", filepath)
    can_db: Any = cantools.database.load_file(filepath)

    db_name = os.path.splitext(os.path.basename(filepath))[0]
    database = CanDatabase(name=db_name)

    for can_msg in can_db.messages:
        cycle_time = _extract_cycle_time(can_msg)
        sender = _extract_sender(can_msg)
        comment = can_msg.comment or ""

        msg = Message(
            id=can_msg.frame_id,
            name=can_msg.name,
            dlc=can_msg.length,
            cycle_time=cycle_time,
            comment=str(comment),
            sender=sender,
        )

        for can_sig in can_msg.signals:
            # Map cantools byte_order (may be 'little_endian'/'big_endian' or enum) to our format
            byte_order = can_sig.byte_order
            if hasattr(byte_order, "name"):
                order_str = byte_order.name.lower()
            else:
                order_str = str(byte_order).lower()
            # Normalize to our internal format: intel/motorola
            if order_str in ("little", "little_endian", "intel"):
                order_str = "intel"
            elif order_str in ("big", "big_endian", "motorola"):
                order_str = "motorola"

            # Multiplexer info
            mux_mode = "none"
            mux_value = 0
            if can_sig.is_multiplexer:
                mux_mode = "multiplexer"
            elif can_sig.multiplexer_ids is not None and len(can_sig.multiplexer_ids) > 0:
                mux_mode = "multiplexed"
                mux_value = can_sig.multiplexer_ids[0] if can_sig.multiplexer_ids else 0

            sig = Signal(
                name=can_sig.name,
                start_bit=can_sig.start,
                length=can_sig.length,
                byte_order=order_str,
                is_signed=can_sig.is_signed,
                factor=can_sig.scale if can_sig.scale is not None else 1.0,
                offset=can_sig.offset if can_sig.offset is not None else 0.0,
                min_val=can_sig.minimum if can_sig.minimum is not None else 0.0,
                max_val=can_sig.maximum if can_sig.maximum is not None else 0.0,
                unit=can_sig.unit or "",
                comment=can_sig.comment or "",
                receivers=can_sig.receivers[:] if can_sig.receivers else [],
                multiplexer_mode=mux_mode,
                multiplexer_value=mux_value,
            )
            msg.signals.append(sig)

        database.add_message(msg)

    logger.info("DBC imported: %s (%d messages, %d signals)",
                filepath, len(database.messages), database.total_signals())
    return database


def export_dbc(database: CanDatabase, filepath: str) -> None:
    """Export the internal CanDatabase to a DBC file using cantools.

    Signals are per-message and read directly from Message.signals.
    """
    logger.info("Exporting DBC: %s (%d messages)", filepath, len(database.messages))
    # Build cantools database objects
    can_db = cantools.database.Database()

    for msg in sorted(database.messages.values(), key=lambda m: m.id):
        can_signals: list = []

        for sig in msg.signals:
            # Determine conversion type
            if sig.factor == 1.0 and sig.offset == 0.0:
                conversion = IdentityConversion(is_float=False)
            else:
                conversion = LinearConversion(
                    scale=sig.factor,
                    offset=sig.offset,
                    is_float=False,
                )

            # Build cantools Signal
            can_sig = cantools.database.Signal(
                name=sig.name,
                start=sig.start_bit,
                length=sig.length,
                # cantools 要求 byte_order 为 'little_endian' 或 'big_endian'
                byte_order="big_endian" if sig.byte_order == "motorola" else "little_endian",
                is_signed=sig.is_signed,
                unit=sig.unit,
                minimum=sig.min_val if sig.min_val != 0.0 else None,
                maximum=sig.max_val if sig.max_val != 0.0 else None,
                comment=sig.comment,
                receivers=sig.receivers[:] if sig.receivers else [],
                conversion=conversion,
                is_multiplexer=(sig.multiplexer_mode == "multiplexer"),
                multiplexer_ids=[sig.multiplexer_value] if sig.multiplexer_mode == "multiplexed" else None,
            )
            can_signals.append(can_sig)

        can_msg = cantools.database.Message(
            frame_id=msg.id,
            name=msg.name,
            length=msg.dlc,
            signals=can_signals,
            comment=msg.comment,
            senders=[sender] if (sender := msg.sender) else [],
            cycle_time=cycle if (cycle := msg.cycle_time) > 0 else None,
        )
        can_db.messages.append(can_msg)

    cantools.database.dump_file(can_db, filepath)
    logger.info("DBC exported: %s", filepath)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_cycle_time(can_msg: Any) -> int:
    """Extract cycle time (ms) from cantools message attributes."""
    try:
        attrs = getattr(can_msg, "dbc", None)
        if attrs is not None and hasattr(attrs, "attributes"):
            for attr_name, attr_val in attrs.attributes.items():
                if "cycle" in attr_name.lower() or "cycletime" in attr_name.lower():
                    try:
                        return int(attr_val)
                    except (ValueError, TypeError):
                        pass
    except Exception as e:
        logger.debug("Failed to extract cycle_time: %s", e)
    return 0


def _extract_sender(can_msg: Any) -> str:
    """Extract sender node name from cantools message."""
    try:
        senders = getattr(can_msg, "senders", None)
        if senders and isinstance(senders, list) and len(senders) > 0:
            return str(senders[0])
    except Exception as e:
        logger.debug("Failed to extract sender: %s", e)
    return ""
