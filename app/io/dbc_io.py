"""DBC import / export using the cantools library."""

from __future__ import annotations

import logging
import os

from app.models import CanDatabase

logger = logging.getLogger(__name__)


def import_dbc(filepath: str) -> CanDatabase:
    """Load a DBC file and convert it to the internal CanDatabase model.

    Signals are per-message — same name in different messages can have
    different attributes (DBC semantics).
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"DBC file not found: {filepath}")

    logger.info("Importing DBC: %s", filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    db_name = os.path.splitext(os.path.basename(filepath))[0]
    database = CanDatabase.from_dbc_str(content)
    database.name = db_name  # from_dbc_str 默认名，这里用文件名覆盖
    logger.info("DBC imported: %s (%d messages, %d signals)",
                filepath, len(database.messages), database.total_signals())
    return database


def export_dbc(database: CanDatabase, filepath: str) -> None:
    """Export the internal CanDatabase to a DBC file using cantools.

    Signals are per-message and read directly from Message.signals.
    """
    logger.info("Exporting DBC: %s (%d messages)", filepath, len(database.messages))
    content = database.to_dbc_str()
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("DBC exported: %s", filepath)
