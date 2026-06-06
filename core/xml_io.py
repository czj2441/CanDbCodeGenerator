"""XML format read / write -- auxiliary format.

Uses xml.etree.ElementTree for standard-library-only dependency.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

from core.can_database import CanDatabase, Message, Signal


def save_xml(database: CanDatabase, filepath: str) -> None:
    """Serialize a CanDatabase to a formatted XML file.

    Signals are nested as <signal> elements inside each <message>.
    """
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    root = ET.Element("can_database", name=database.name)

    # Messages
    for msg in sorted(database.messages.values(), key=lambda m: m.id):
        msg_elem = ET.SubElement(
            root,
            "message",
            id=f"0x{msg.id:X}",
            name=msg.name,
            dlc=str(msg.dlc),
            cycle_time=str(msg.cycle_time),
            sender=msg.sender,
            comment=msg.comment,
        )

        for sig in msg.signals:
            ET.SubElement(
                msg_elem,
                "signal",
                name=sig.name,
                start_bit=str(sig.start_bit),
                length=str(sig.length),
                byte_order=sig.byte_order,
                is_signed=str(sig.is_signed).lower(),
                factor=str(sig.factor),
                offset=str(sig.offset),
                min_val=str(sig.min_val),
                max_val=str(sig.max_val),
                unit=sig.unit,
                comment=sig.comment,
                multiplexer_mode=sig.multiplexer_mode,
                multiplexer_value=str(sig.multiplexer_value),
            )

    raw = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")

    with open(filepath, "wb") as f:
        f.write(pretty)


def load_xml(filepath: str) -> CanDatabase:
    """Load a CanDatabase from an XML file.

    Signals are nested as <signal> elements inside each <message>.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"XML file not found: {filepath}")

    tree = ET.parse(filepath)
    root = tree.getroot()

    db_name = root.get("name", "Untitled")
    database = CanDatabase(name=str(db_name))

    for msg_elem in root.findall("message"):
        raw_id = msg_elem.get("id", "0")
        msg_id = int(raw_id, 16) if raw_id.startswith("0x") else int(raw_id)

        msg = Message(
            id=msg_id,
            name=str(msg_elem.get("name", "")),
            dlc=int(msg_elem.get("dlc", "8")),
            cycle_time=int(msg_elem.get("cycle_time", "0")),
            comment=str(msg_elem.get("comment", "")),
            sender=str(msg_elem.get("sender", "")),
        )

        for sig_elem in msg_elem.findall("signal"):
            sig = Signal(
                name=str(sig_elem.get("name", "")),
                start_bit=int(sig_elem.get("start_bit", "0")),
                length=int(sig_elem.get("length", "8")),
                byte_order=str(sig_elem.get("byte_order", "intel")),
                is_signed=sig_elem.get("is_signed", "false").lower() == "true",
                factor=float(sig_elem.get("factor", "1.0")),
                offset=float(sig_elem.get("offset", "0.0")),
                min_val=float(sig_elem.get("min_val", "0.0")),
                max_val=float(sig_elem.get("max_val", "0.0")),
                unit=str(sig_elem.get("unit", "")),
                comment=str(sig_elem.get("comment", "")),
                multiplexer_mode=str(sig_elem.get("multiplexer_mode", "none")),
                multiplexer_value=int(sig_elem.get("multiplexer_value", "0")),
            )
            msg.signals.append(sig)

        database.add_message(msg)

    return database