"""Catalogue I/O and filtering, with compatible imports for existing callers."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .catalog_models import CatalogItem, QuantityRecord, RawVolumeRecord
from .catalog_scan import (
    _scalar as _scalar,
    _quantity_from_group as _quantity_from_group,
    _attrs as _attrs,
    _float_attr as _float_attr,
    _spatial_metadata as _spatial_metadata,
    _spatial_metadata_root_volume as _spatial_metadata_root_volume,
    _nominal_dataset_height as _nominal_dataset_height,
    iter_aggregate_files as iter_aggregate_files,
    iter_raw_volume_files as iter_raw_volume_files,
    _records_from_root_volume as _records_from_root_volume,
    scan_raw_volume as scan_raw_volume,
    scan_raw_volume_fast as scan_raw_volume_fast,
    scan_aggregate as scan_aggregate,
    scan_aggregate_fast as scan_aggregate_fast,
)
from .catalog_pvol import (
    catalog_url_is_pvol_root as catalog_url_is_pvol_root,
    catalog_public_base_from_root_url as catalog_public_base_from_root_url,
    join_catalog_url as join_catalog_url,
    is_pvol_root_payload as is_pvol_root_payload,
    is_pvol_coverage_payload as is_pvol_coverage_payload,
    is_pvol_day_payload as is_pvol_day_payload,
    _valid_spatial as _valid_spatial,
    pvol_spatial_root_attrs as pvol_spatial_root_attrs,
    pvol_radar_records as pvol_radar_records,
    pvol_catalog_summary as pvol_catalog_summary,
    _pvol_radar_by_slug as _pvol_radar_by_slug,
    pvol_coverage_keys as pvol_coverage_keys,
    pvol_item_from_coverage_day as pvol_item_from_coverage_day,
    pvol_items_from_coverage as pvol_items_from_coverage,
    _as_text_list as _as_text_list,
    _as_int_list as _as_int_list,
    _optional_float as _optional_float,
    _records_from_field_entry as _records_from_field_entry,
    _merge_field_index_files as _merge_field_index_files,
    pvol_item_from_day_catalog as pvol_item_from_day_catalog,
)
from .catalog_scan import AGGREGATE_RE, RAW_VOLUME_RE, DATA_GROUP_RE, ROOT_DATA_GROUP_RE, EARTH_RADIUS_M
from .catalog_pvol import PVOL_ROOT_SUFFIX


def build_catalog(
    aggregate_base: Path,
    output: Path,
    radar: str | None = None,
    year: str | None = None,
    date: str | None = None,
    max_files: int | None = None,
    object_store_base: str = "",
    metadata_mode: str = "deep",
) -> list[CatalogItem]:
    if metadata_mode not in {"deep", "fast"}:
        raise ValueError("metadata_mode must be 'deep' or 'fast'")
    items: list[CatalogItem] = []
    normalized_date = date.replace("-", "") if date else None
    scanner = scan_aggregate_fast if metadata_mode == "fast" else scan_aggregate
    for path in iter_aggregate_files(aggregate_base, radar, year):
        if normalized_date and not path.name.startswith(f"{normalized_date}_"):
            continue
        if max_files is not None and len(items) >= max_files:
            break
        items.append(scanner(path, aggregate_base, object_store_base))
    write_catalog(output, items)
    return items


def build_raw_volume_catalog(
    raw_volume_base: Path,
    output: Path,
    radar: str | None = None,
    year: str | None = None,
    date: str | None = None,
    max_files: int | None = None,
    object_store_base: str = "",
    metadata_mode: str = "deep",
) -> list[CatalogItem]:
    if metadata_mode not in {"deep", "fast"}:
        raise ValueError("metadata_mode must be 'deep' or 'fast'")
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for path in iter_raw_volume_files(raw_volume_base, radar, year, date):
        if max_files is not None and sum(len(group["raw_volumes"]) for group in grouped.values()) >= max_files:
            break
        if metadata_mode == "fast":
            radar_name, radar_num, item_date, volume = scan_raw_volume_fast(path, raw_volume_base, object_store_base)
            records = []
            root_attrs = {}
        else:
            radar_name, radar_num, item_date, volume, records, root_attrs = scan_raw_volume(path, raw_volume_base, object_store_base)
        key = (radar_name, item_date)
        group = grouped.setdefault(
            key,
            {
                "radar": radar_name,
                "radar_num": radar_num,
                "date": item_date,
                "raw_volumes": [],
                "quantity_records": [],
                "root_attrs": {"uk_wsr:source_type": "raw_volume_day"},
            },
        )
        group["raw_volumes"].append(volume)
        group["quantity_records"].extend(records)
        if root_attrs.get("uk_wsr:spatial") and "uk_wsr:spatial" not in group["root_attrs"]:
            group["root_attrs"]["uk_wsr:spatial"] = root_attrs["uk_wsr:spatial"]

    if metadata_mode == "fast":
        for group in grouped.values():
            by_pulse: dict[str, list[RawVolumeRecord]] = {}
            for volume in group["raw_volumes"]:
                by_pulse.setdefault(volume.pulse, []).append(volume)
            for pulse, volumes in by_pulse.items():
                first = min(volumes, key=lambda volume: volume.time)
                try:
                    _radar_name, _radar_num, _item_date, scanned_volume, template_records, root_attrs = scan_raw_volume(
                        Path(first.path),
                        raw_volume_base,
                        object_store_base,
                    )
                except Exception:
                    continue
                quantities = sorted({record.quantity for record in template_records})
                for volume in volumes:
                    volume.quantities = quantities
                    for record in template_records:
                        group["quantity_records"].append(
                            QuantityRecord(
                                pulse=volume.pulse,
                                time=volume.time,
                                dataset=record.dataset,
                                kind=record.kind,
                                index=record.index,
                                quantity=record.quantity,
                                shape=list(record.shape),
                                dtype=record.dtype,
                                elevation_deg=record.elevation_deg,
                                nominal_height_m=record.nominal_height_m,
                            )
                        )
                if root_attrs.get("uk_wsr:spatial") and "uk_wsr:spatial" not in group["root_attrs"]:
                    group["root_attrs"]["uk_wsr:spatial"] = root_attrs["uk_wsr:spatial"]

    items: list[CatalogItem] = []
    for group in grouped.values():
        records = group["quantity_records"]
        volumes = sorted(group["raw_volumes"], key=lambda volume: (volume.pulse, volume.time))
        pulses = sorted({record.pulse for record in records})
        quantities_by_pulse = {
            pulse: sorted({record.quantity for record in records if record.pulse == pulse})
            for pulse in pulses
        }
        times_by_pulse = {
            pulse: sorted({record.time for record in records if record.pulse == pulse})
            for pulse in pulses
        }
        first_volume = volumes[0] if volumes else None
        items.append(
            CatalogItem(
                radar=group["radar"],
                radar_num=group["radar_num"],
                date=group["date"],
                path=first_volume.path if first_volume else "",
                file_size=sum(volume.file_size for volume in volumes),
                modified_time=max((volume.modified_time for volume in volumes), default=0),
                pulses=pulses,
                times=sorted({record.time for record in records}),
                quantities=sorted({record.quantity for record in records}),
                quantity_records=records,
                object_key=first_volume.object_key if first_volume else "",
                object_url=first_volume.object_url if first_volume else "",
                source_type="raw_volume_day",
                raw_volumes=volumes,
                root_attrs=group["root_attrs"],
                quantities_by_pulse=quantities_by_pulse,
                times_by_pulse=times_by_pulse,
            )
        )
    items.sort(key=lambda item: (item.radar, item.date))
    write_catalog(output, items)
    return items


def write_catalog(path: Path, items: list[CatalogItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "items": [
            {
                **asdict(item),
                "quantity_records": [asdict(record) for record in item.quantity_records],
            }
            for item in items
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _catalog_items_from_payload(payload: dict[str, Any]) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    item_fields = {entry.name for entry in fields(CatalogItem)}
    for raw in payload.get("items", []):
        raw = dict(raw)
        records = [QuantityRecord(**record) for record in raw.pop("quantity_records", [])]
        raw_volumes = [RawVolumeRecord(**record) for record in raw.pop("raw_volumes", [])]
        raw.setdefault("root_attrs", {})
        raw.setdefault("quantities_by_pulse", {})
        raw.setdefault("times_by_pulse", {})
        raw.setdefault("source_type", "aggregate_day")
        raw = {key: value for key, value in raw.items() if key in item_fields}
        items.append(CatalogItem(**raw, quantity_records=records, raw_volumes=raw_volumes))
    return items


def load_catalog(path: Path) -> list[CatalogItem]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _catalog_items_from_payload(payload)


def load_catalog_url(url: str, timeout_s: float = 30.0) -> list[CatalogItem]:
    with urlopen(url, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _catalog_items_from_payload(payload)


def load_catalog_source(path: Path, remote_url: str = "") -> list[CatalogItem]:
    if path.exists():
        return load_catalog(path)
    if remote_url:
        return load_catalog_url(remote_url)
    return load_catalog(path)


def filter_catalog(
    items: list[CatalogItem],
    radar: str | None = None,
    start: str | None = None,
    end: str | None = None,
    pulse: str | None = None,
    quantity: str | None = None,
) -> list[CatalogItem]:
    result = items
    if radar:
        result = [item for item in result if item.radar == radar]
    if start:
        result = [item for item in result if item.date >= start.replace("-", "")]
    if end:
        result = [item for item in result if item.date <= end.replace("-", "")]
    if pulse:
        result = [item for item in result if pulse in item.pulses]
    if quantity:
        result = [item for item in result if quantity in item.quantities]
    return result


def catalog_summary(items: list[CatalogItem]) -> dict[str, Any]:
    radars = sorted({item.radar for item in items})
    dates = sorted({item.date for item in items})
    pulses = sorted({pulse for item in items for pulse in item.pulses})
    quantities = sorted({quantity for item in items for quantity in item.quantities})
    return {
        "item_count": len(items),
        "radars": radars,
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "pulses": pulses,
        "quantities": quantities,
        "file_size_total": sum(item.file_size for item in items),
        "by_radar": {
            radar: {
                "item_count": sum(1 for item in items if item.radar == radar),
                "start_date": min((item.date for item in items if item.radar == radar), default=None),
                "end_date": max((item.date for item in items if item.radar == radar), default=None),
            }
            for radar in radars
        },
    }
