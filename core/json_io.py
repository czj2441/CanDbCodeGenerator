"""JSON format read / write -- auxiliary format."""

from __future__ import annotations

import json
import os

from core.can_database import CanDatabase


def save_json(database: CanDatabase, filepath: str) -> None:
    """Serialize a CanDatabase to a JSON file."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    data = database.to_json_dict()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(filepath: str) -> CanDatabase:
    """Load a CanDatabase from a JSON file."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"JSON file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    return CanDatabase.from_json_dict(data)