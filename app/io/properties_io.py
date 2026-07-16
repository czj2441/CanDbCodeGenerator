"""Java Properties format read / write -- primary storage format.

Storage layout (flat dotted keys)::

    database.name=MyProject
    messages.0x100.name=EngineStatus
    messages.0x100.dlc=8
    messages.0x100.signals.RPM.start_bit=0
"""

from __future__ import annotations

import logging
import os

from app.models import CanDatabase

logger = logging.getLogger(__name__)


def save_properties(database: CanDatabase, filepath: str) -> None:
    """Serialize a CanDatabase to a Properties file."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    content = database.to_properties_str()
    tmp_path = filepath + ".tmp"
    logger.info("Saving properties: %s (%d bytes)", filepath, len(content))
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
    except OSError as e:
        logger.error("Failed to save properties %s: %s", filepath, e, exc_info=True)
        raise


def load_properties(filepath: str) -> CanDatabase:
    """Load a CanDatabase from a Properties file."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Properties file not found: {filepath}")
    logger.info("Loading properties: %s", filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    db = CanDatabase.from_properties_str(content)
    logger.info("Loaded properties: %d messages", len(db.messages))
    return db
