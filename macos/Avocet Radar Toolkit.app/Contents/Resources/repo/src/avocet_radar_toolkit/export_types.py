"""Shared export selection types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSelection:
    pulse: str
    time: str
    quantity: str
    dataset: str | None = None
    cappi_height_m: float | None = None
