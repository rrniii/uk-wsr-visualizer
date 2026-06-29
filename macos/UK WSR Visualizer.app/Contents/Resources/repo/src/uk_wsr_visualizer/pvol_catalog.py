"""Lazy reader for the interim public PVOL object-store catalog.

The public PVOL catalog is intentionally split into a small root catalog,
per-radar/per-year coverage files, and per-day file catalogs.  This module keeps
that structure lazy so the desktop app can start quickly without loading the
millions of individual PVOL file records in the object store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen

from .catalog import CatalogItem, RawVolumeRecord
from .object_store import join_object_url

PVOL_ROOT_SUFFIX = "/ukmo-nimrod/catalog/pvol/catalog.json"
PVOL_VARIABLE_HINTS = [
    "DBZH",
    "TH",
    "TV",
    "VRADH",
    "VRADV",
    "WRADH",
    "WRADV",
    "ZDR",
    "RHOHV",
    "PHIDP",
    "KDP",
    "SNRH",
    "SNRV",
]


def is_pvol_root_url(url: str) -> bool:
    """Return true when a URL points at the split PVOL root catalog."""

    return bool(url) and url.rstrip("/").endswith(PVOL_ROOT_SUFFIX)


def is_pvol_root_payload(payload: dict[str, Any]) -> bool:
    """Return true when a JSON payload looks like the split PVOL root catalog."""

    return isinstance(payload.get("radars"), list) and payload.get("product") == "pvol"


def pvol_public_base_from_root_url(root_url: str) -> str:
    """Derive the public object-store base URL from a PVOL root catalog URL."""

    stripped = root_url.rstrip("/")
    if stripped.endswith(PVOL_ROOT_SUFFIX):
        return stripped[: -len(PVOL_ROOT_SUFFIX)]
    return stripped.rsplit("/ukmo-nimrod/", 1)[0] if "/ukmo-nimrod/" in stripped else stripped


def _fetch_json(url: str, timeout_s: float = 30.0) -> dict[str, Any]:
    with urlopen(url, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _date(value: str | None) -> str:
    return str(value or "").replace("-", "")


def _years_between(start: str | None, end: str | None, fallback_years: list[str]) -> list[str]:
    start_date = _date(start)
    end_date = _date(end)
    if start_date or end_date:
        start_year = int((start_date or end_date)[:4])
        end_year = int((end_date or start_date)[:4])
        return [str(year) for year in range(start_year, end_year + 1)]
    return fallback_years


@dataclass(frozen=True)
class PvolDayCatalog:
    """Resolved per-day PVOL catalog payload plus its source URL."""

    url: str
    payload: dict[str, Any]


class PvolCatalogClient:
    """Lazy access to the interim uploaded-only PVOL catalog."""

    def __init__(self, root_url: str, public_base_url: str | None = None, timeout_s: float = 30.0) -> None:
        self.root_url = root_url
        self.public_base_url = (public_base_url or pvol_public_base_from_root_url(root_url)).rstrip("/")
        self.timeout_s = timeout_s
        self._root: dict[str, Any] | None = None
        self._coverage: dict[tuple[str, str], dict[str, Any]] = {}
        self._day_catalogs: dict[tuple[str, str], PvolDayCatalog] = {}

    def root(self) -> dict[str, Any]:
        if self._root is None:
            self._root = _fetch_json(self.root_url, self.timeout_s)
            if not is_pvol_root_payload(self._root):
                raise ValueError(f"not an interim PVOL root catalog: {self.root_url}")
        return self._root

    def radar_entries(self) -> list[dict[str, Any]]:
        return list(self.root().get("radars", []))

    def radar_entry(self, radar: str) -> dict[str, Any] | None:
        for entry in self.radar_entries():
            if entry.get("radar") == radar:
                return entry
        return None

    def coverage_url(self, radar: str, year: str) -> str | None:
        entry = self.radar_entry(radar)
        if not entry:
            return None
        suffix = f"/{year}/coverage.json"
        for key in entry.get("coverage_keys", []):
            if str(key).endswith(suffix):
                return join_object_url(self.public_base_url, str(key))
        return None

    def coverage(self, radar: str, year: str) -> dict[str, Any] | None:
        cache_key = (radar, str(year))
        if cache_key in self._coverage:
            return self._coverage[cache_key]
        url = self.coverage_url(radar, str(year))
        if not url:
            return None
        payload = _fetch_json(url, self.timeout_s)
        self._coverage[cache_key] = payload
        return payload

    def day_catalog(self, radar: str, date: str) -> PvolDayCatalog | None:
        normalized = _date(date)
        cache_key = (radar, normalized)
        if cache_key in self._day_catalogs:
            return self._day_catalogs[cache_key]
        item = self.day_item(radar, normalized)
        catalog_key = item.root_attrs.get("uk_wsr:pvol_catalog_key")
        if not catalog_key:
            return None
        url = join_object_url(self.public_base_url, str(catalog_key))
        payload = _fetch_json(url, self.timeout_s)
        catalog = PvolDayCatalog(url=url, payload=payload)
        self._day_catalogs[cache_key] = catalog
        return catalog

    def summary(self) -> dict[str, Any]:
        root = self.root()
        radars = sorted(str(entry["radar"]) for entry in root.get("radars", []) if entry.get("radar"))
        first_dates = [str(entry.get("first_date")) for entry in root.get("radars", []) if entry.get("first_date")]
        last_dates = [str(entry.get("last_date")) for entry in root.get("radars", []) if entry.get("last_date")]
        by_radar = {}
        for entry in root.get("radars", []):
            radar = str(entry.get("radar", ""))
            if not radar:
                continue
            by_radar[radar] = {
                "item_count": int(entry.get("date_count") or 0),
                "start_date": entry.get("first_date"),
                "end_date": entry.get("last_date"),
                "first_plot_ready_date": entry.get("first_date"),
                "latest_plot_ready_date": entry.get("last_date"),
                "plot_ready_probe": True,
                "file_count": int(entry.get("file_count") or 0),
                "size_bytes": int(entry.get("size_bytes") or 0),
                "years": list(entry.get("years", [])),
            }
        return {
            "item_count": int(root.get("day_count") or sum(value["item_count"] for value in by_radar.values())),
            "radars": radars,
            "start_date": min(first_dates) if first_dates else None,
            "end_date": max(last_dates) if last_dates else None,
            "pulses": [],
            "quantities": PVOL_VARIABLE_HINTS,
            "file_size_total": int(root.get("size_bytes") or 0),
            "by_radar": by_radar,
            "interim": bool(root.get("interim")),
            "upload_complete": bool(root.get("upload_complete")),
            "catalog_source": self.root_url,
            "coverage_csv": join_object_url(self.public_base_url, str(root.get("coverage_csv_key", ""))),
        }

    def availability(self, radar: str | None = None) -> dict[str, Any]:
        summary = self.summary()
        if not radar:
            return {
                "radar": "",
                "item_count": summary["item_count"],
                "start_date": summary["start_date"],
                "end_date": summary["end_date"],
                "first_plot_ready_date": summary["start_date"],
                "latest_plot_ready_date": summary["end_date"],
                "plot_ready_probe": True,
                "interim": summary["interim"],
                "upload_complete": summary["upload_complete"],
            }
        entry = summary["by_radar"].get(radar, {})
        return {
            "radar": radar,
            "item_count": entry.get("item_count", 0),
            "start_date": entry.get("start_date"),
            "end_date": entry.get("end_date"),
            "first_plot_ready_date": entry.get("first_plot_ready_date"),
            "latest_plot_ready_date": entry.get("latest_plot_ready_date"),
            "plot_ready_probe": True,
            "interim": summary["interim"],
            "upload_complete": summary["upload_complete"],
        }

    def search(
        self,
        radar: str | None = None,
        start: str | None = None,
        end: str | None = None,
        pulse: str | None = None,
        quantity: str | None = None,
    ) -> list[CatalogItem]:
        if quantity and quantity not in PVOL_VARIABLE_HINTS:
            return []
        start_date = _date(start)
        end_date = _date(end)
        entries = [self.radar_entry(radar)] if radar else self.radar_entries()
        entries = [entry for entry in entries if entry]
        if not radar and not (start_date or end_date):
            return []

        items: list[CatalogItem] = []
        for entry in entries:
            entry_years = [str(year) for year in entry.get("years", [])]
            for year in _years_between(start_date, end_date, entry_years):
                coverage = self.coverage(str(entry["radar"]), year)
                if not coverage:
                    continue
                for day in coverage.get("days", []):
                    item = self.item_from_coverage_day(entry, day)
                    if start_date and item.date < start_date:
                        continue
                    if end_date and item.date > end_date:
                        continue
                    if pulse and pulse not in item.pulses:
                        continue
                    items.append(item)
        return sorted(items, key=lambda item: (item.radar, item.date))

    def day_item(self, radar: str, date: str) -> CatalogItem:
        normalized = _date(date)
        entry = self.radar_entry(radar)
        if not entry:
            raise KeyError(f"radar not found in PVOL catalog: {radar}")
        coverage = self.coverage(radar, normalized[:4])
        if not coverage:
            raise KeyError(f"coverage not found for {radar} {normalized[:4]}")
        for day in coverage.get("days", []):
            if str(day.get("date")) == normalized:
                return self.item_from_coverage_day(entry, day)
        raise KeyError(f"day not found in PVOL catalog: {radar} {normalized}")

    def item_from_coverage_day(self, radar_entry: dict[str, Any], day: dict[str, Any]) -> CatalogItem:
        pulse_counts = day.get("pulse_counts", {}) if isinstance(day.get("pulse_counts"), dict) else {}
        pulses = sorted(str(pulse) for pulse in pulse_counts)
        return CatalogItem(
            radar=str(radar_entry.get("radar", "")),
            radar_num=str(radar_entry.get("radar_num", "")),
            date=str(day.get("date", "")),
            path="",
            file_size=int(day.get("size_bytes") or 0),
            modified_time=0.0,
            pulses=pulses,
            times=[],
            quantities=PVOL_VARIABLE_HINTS.copy(),
            quantity_records=[],
            object_key=str(day.get("pvol_prefix", "")),
            object_url="",
            source_type="raw_volume_day",
            raw_volumes=[],
            root_attrs={
                "uk_wsr:source_type": "raw_volume_day",
                "uk_wsr:catalog_mode": "interim_pvol",
                "uk_wsr:pvol_catalog_key": day.get("catalog_key", ""),
                "uk_wsr:pvol_prefix": day.get("pvol_prefix", ""),
                "uk_wsr:interim": True,
                "uk_wsr:upload_complete": False,
                "uk_wsr:file_count": int(day.get("file_count") or 0),
                "uk_wsr:pulse_counts": pulse_counts,
            },
            quantities_by_pulse={pulse: PVOL_VARIABLE_HINTS.copy() for pulse in pulses},
            times_by_pulse={pulse: [] for pulse in pulses},
        )

    def hydrate_day_item(self, item: CatalogItem) -> CatalogItem:
        day_catalog = self.day_catalog(item.radar, item.date)
        if day_catalog is None:
            return item
        payload = day_catalog.payload
        files = payload.get("files", [])
        raw_volumes = [
            RawVolumeRecord(
                pulse=str(record.get("pulse", "")),
                time=str(record.get("time", "")),
                path=str(record.get("object_url", "")),
                filename=str(record.get("filename", "")),
                file_size=int(record.get("size_bytes") or 0),
                modified_time=float(record.get("modified_time") or 0.0),
                object_key=str(record.get("object_key", "")),
                object_url=str(record.get("object_url", "")),
                quantities=PVOL_VARIABLE_HINTS.copy(),
            )
            for record in files
        ]
        pulses = sorted({volume.pulse for volume in raw_volumes if volume.pulse})
        times = sorted({volume.time for volume in raw_volumes if volume.time})
        times_by_pulse = {
            pulse: sorted({volume.time for volume in raw_volumes if volume.pulse == pulse})
            for pulse in pulses
        }
        first_volume = raw_volumes[0] if raw_volumes else None
        return CatalogItem(
            radar=str(payload.get("radar") or item.radar),
            radar_num=str(payload.get("radar_num") or item.radar_num),
            date=str(payload.get("date") or item.date),
            path=first_volume.path if first_volume else "",
            file_size=int(payload.get("size_bytes") or item.file_size),
            modified_time=max((volume.modified_time for volume in raw_volumes), default=0.0),
            pulses=pulses,
            times=times,
            quantities=PVOL_VARIABLE_HINTS.copy(),
            quantity_records=[],
            object_key=first_volume.object_key if first_volume else item.object_key,
            object_url=first_volume.object_url if first_volume else item.object_url,
            source_type="raw_volume_day",
            raw_volumes=sorted(raw_volumes, key=lambda volume: (volume.pulse, volume.time)),
            validation_status=item.validation_status,
            root_attrs={
                **item.root_attrs,
                "uk_wsr:pvol_day_catalog_url": day_catalog.url,
                "uk_wsr:interim": bool(payload.get("interim", True)),
                "uk_wsr:upload_complete": bool(payload.get("upload_complete", False)),
                "uk_wsr:file_count": int(payload.get("file_count") or len(raw_volumes)),
                "uk_wsr:pulse_counts": payload.get("pulse_counts", item.root_attrs.get("uk_wsr:pulse_counts", {})),
            },
            quantities_by_pulse={pulse: PVOL_VARIABLE_HINTS.copy() for pulse in pulses},
            times_by_pulse=times_by_pulse,
        )
