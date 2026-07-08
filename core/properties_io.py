"""Java Properties format read / write -- primary storage format.

Storage layout (flat dotted keys)::

    database.name=MyProject
    messages.0x100.name=EngineStatus
    messages.0x100.dlc=8
    messages.0x100.signals.RPM.start_bit=0
"""

from __future__ import annotations

import os

from models import CanDatabase


def save_properties(database: CanDatabase, filepath: str) -> None:
    """Serialize a CanDatabase to a Properties file."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    content = database.to_properties_str()
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, filepath)


def load_properties(filepath: str) -> CanDatabase:
    """Load a CanDatabase from a Properties file."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Properties file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    return CanDatabase.from_properties_str(content)
