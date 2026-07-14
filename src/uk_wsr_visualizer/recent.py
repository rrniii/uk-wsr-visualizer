"""Persistent recent-selection storage for the desktop viewer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .compat import UTC

MAX_RECENT_SELECTIONS = 12
RECENT_SELECTION_FIELDS = {
    "radar",
    "date",
    "pulse",
    "time",
    "quantity",
    "dataset",
    "item_label",
    "object_key",
    "object_url",
    "source_type",
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean_selection(selection: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key in RECENT_SELECTION_FIELDS:
        value = selection.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    if not cleaned.get("radar") or not cleaned.get("date"):
        raise ValueError("recent selection requires radar and date")
    cleaned["updated_at"] = _now()
    return cleaned


def _selection_key(selection: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(selection.get("radar", "")),
        str(selection.get("date", "")),
        str(selection.get("pulse", "")),
        str(selection.get("time", "")),
        str(selection.get("quantity", "")),
        str(selection.get("dataset", "")),
    )


def load_recent_selections(path: Path) -> list[dict[str, str]]:
    """Load recent selections from disk, returning an empty list on missing data."""

    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            cleaned_item = _clean_selection(item)
        except ValueError:
            continue
        if isinstance(item.get("updated_at"), str):
            cleaned_item["updated_at"] = item["updated_at"]
        cleaned.append(cleaned_item)
    return cleaned[:MAX_RECENT_SELECTIONS]


def save_recent_selections(path: Path, selections: list[dict[str, str]]) -> None:
    """Persist recent selections atomically enough for local desktop use."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "items": selections[:MAX_RECENT_SELECTIONS]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def record_recent_selection(
    path: Path,
    selection: dict[str, Any],
    *,
    limit: int = MAX_RECENT_SELECTIONS,
) -> list[dict[str, str]]:
    """Insert a selection at the top of the recent list, de-duplicating by field choice."""

    cleaned = _clean_selection(selection)
    existing = load_recent_selections(path)
    key = _selection_key(cleaned)
    merged = [cleaned] + [item for item in existing if _selection_key(item) != key]
    selections = merged[: max(1, limit)]
    save_recent_selections(path, selections)
    return selections


def clear_recent_selections(path: Path) -> None:
    """Remove the persisted recent-selection file if present."""

    try:
        path.unlink()
    except FileNotFoundError:
        return
