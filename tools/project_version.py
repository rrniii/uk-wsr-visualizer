#!/usr/bin/env python3
"""Print the project version from pyproject.toml."""

from __future__ import annotations

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]

with (ROOT / "pyproject.toml").open("rb") as handle:
    data = tomllib.load(handle)

print(data["project"]["version"])
