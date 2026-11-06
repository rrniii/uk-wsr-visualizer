"""Catalogue records shared by discovery, rendering and exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuantityRecord:
    pulse: str
    time: str
    dataset: str
    kind: str
    index: str
    quantity: str
    shape: list[int] = field(default_factory=list)
    dtype: str = ""
    elevation_deg: float | None = None
    nominal_height_m: float | None = None


@dataclass
class RawVolumeRecord:
    pulse: str
    time: str
    path: str
    filename: str
    file_size: int
    modified_time: float
    object_key: str
    object_url: str = ""
    quantities: list[str] = field(default_factory=list)


@dataclass
class CatalogItem:
    radar: str
    radar_num: str
    date: str
    path: str
    file_size: int
    modified_time: float
    pulses: list[str]
    times: list[str]
    quantities: list[str]
    quantity_records: list[QuantityRecord]
    object_key: str
    object_url: str = ""
    source_type: str = "aggregate_day"
    raw_volumes: list[RawVolumeRecord] = field(default_factory=list)
    validation_status: str = "unknown"
    root_attrs: dict[str, Any] = field(default_factory=dict)
    quantities_by_pulse: dict[str, list[str]] = field(default_factory=dict)
    times_by_pulse: dict[str, list[str]] = field(default_factory=dict)

    @property
    def item_id(self) -> str:
        return f"{self.radar}-{self.date}"

    def raw_volume_for(self, pulse: str, time: str) -> RawVolumeRecord | None:
        for volume in self.raw_volumes:
            if volume.pulse == pulse and volume.time == time:
                return volume
        return None
