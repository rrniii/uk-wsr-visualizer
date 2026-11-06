"""Build identity retained when a desktop package has no Git checkout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def packaged_build_info() -> dict[str, Any]:
    path = Path(__file__).with_name("build-info.json")
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "uk-wsr-build-v1":
        raise ValueError("Invalid packaged build metadata")
    return payload
