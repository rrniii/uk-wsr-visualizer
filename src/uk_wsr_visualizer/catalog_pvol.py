"""Decode public PVOL catalogue metadata; no HDF5 download is needed."""

from __future__ import annotations

import re
from typing import Any

from .object_store import join_object_url
from .radars import RADAR_BY_SLUG, RADAR_NUM_BY_SLUG
from .catalog_models import CatalogItem, QuantityRecord, RawVolumeRecord

# Each archive era has its own product prefix.
PVOL_ROOT_SUFFIX = "/catalog/pvol/catalog.json"


def catalog_url_is_pvol_root(url: str) -> bool:
    return url.rstrip("/").endswith(PVOL_ROOT_SUFFIX)


def catalog_public_base_from_root_url(url: str) -> str:
    clean = url.rstrip("/")
    if clean.endswith(PVOL_ROOT_SUFFIX):
        product_root = clean[: -len(PVOL_ROOT_SUFFIX)].rstrip("/")
        return product_root.rsplit("/", 1)[0]
    marker = "/catalog/pvol/"
    if marker in clean:
        product_root = clean.split(marker, 1)[0]
        return product_root.rsplit("/", 1)[0]
    return clean.rsplit("/", 1)[0]


def join_catalog_url(public_base: str, key: str) -> str:
    return f"{public_base.rstrip('/')}/{key.lstrip('/')}"


def is_pvol_root_payload(payload: dict[str, Any]) -> bool:
    radars = payload.get("radars")
    return isinstance(radars, list) and any(isinstance(entry, dict) and entry.get("coverage_keys") for entry in radars)


def is_pvol_coverage_payload(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("days"), list) and isinstance(payload.get("radar"), str) and isinstance(payload.get("year"), str)


def is_pvol_day_payload(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("files"), list) and isinstance(payload.get("date"), str) and isinstance(payload.get("radar"), str)


def _valid_spatial(spatial: Any) -> dict[str, Any]:
    if not isinstance(spatial, dict):
        return {}
    try:
        lat = float(spatial["latitude"])
        lon = float(spatial["longitude"])
    except (KeyError, TypeError, ValueError):
        return {}
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return {}
    result: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
    }
    try:
        if spatial.get("height_m") is not None:
            result["height_m"] = float(spatial["height_m"])
    except (TypeError, ValueError):
        pass
    source = spatial.get("source")
    if source:
        result["source"] = str(source)
    if isinstance(spatial.get("bbox"), list):
        result["bbox"] = spatial["bbox"]
    return result


def pvol_spatial_root_attrs(root: dict[str, Any], radar: dict[str, Any]) -> dict[str, Any]:
    spatial = _valid_spatial(radar.get("spatial"))
    if not spatial:
        return {}
    attrs: dict[str, Any] = {
        "uk_wsr:spatial": spatial,
        "radar_latitude": spatial["latitude"],
        "radar_longitude": spatial["longitude"],
        "radar_spatial_source": spatial.get("source") or root.get("spatial_source", ""),
    }
    if spatial.get("height_m") is not None:
        attrs["radar_height_m"] = spatial["height_m"]
    if root.get("spatial_source"):
        attrs["root_spatial_source"] = root["spatial_source"]
    if root.get("spatial_updated_at"):
        attrs["root_spatial_updated_at"] = root["spatial_updated_at"]
    return attrs


def pvol_radar_records(root: dict[str, Any]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for entry in root.get("radars", []):
        if not isinstance(entry, dict):
            continue
        slug = str(entry.get("radar") or "")
        if not slug:
            continue
        site = RADAR_BY_SLUG.get(slug)
        spatial = _valid_spatial(entry.get("spatial"))
        record: dict[str, object] = {
            "slug": slug,
            "radar_num": str(entry.get("radar_num") or (site.radar_num if site else "")),
            "label": site.label if site else slug.replace("-", " ").title(),
            "latitude": spatial.get("latitude"),
            "longitude": spatial.get("longitude"),
            "height_m": spatial.get("height_m"),
            "spatial_source": spatial.get("source") or root.get("spatial_source", ""),
            "first_date": entry.get("first_date"),
            "last_date": entry.get("last_date"),
            "date_count": entry.get("date_count", 0),
            "file_count": entry.get("file_count", 0),
            "years": entry.get("years", []),
        }
        records.append(record)
    return sorted(records, key=lambda record: str(record["label"]))


def pvol_catalog_summary(root: dict[str, Any]) -> dict[str, Any]:
    radars = [entry for entry in root.get("radars", []) if isinstance(entry, dict)]
    dates = [
        str(value)
        for entry in radars
        for value in (entry.get("first_date"), entry.get("last_date"))
        if value
    ]
    by_radar = {
        str(entry.get("radar")): {
            "item_count": int(entry.get("date_count") or 0),
            "start_date": entry.get("first_date"),
            "end_date": entry.get("last_date"),
            "first_plot_ready_date": entry.get("first_date"),
            "latest_plot_ready_date": entry.get("last_date"),
            "plot_ready_probe": False,
            "file_count": int(entry.get("file_count") or 0),
            "size_bytes": int(entry.get("size_bytes") or 0),
            "years": entry.get("years", []),
        }
        for entry in radars
        if entry.get("radar")
    }
    return {
        "item_count": sum(int(entry.get("date_count") or 0) for entry in radars),
        "radars": sorted(by_radar),
        "start_date": min(dates) if dates else None,
        "end_date": max(dates) if dates else None,
        "pulses": ["lp", "sp"],
        "quantities": [],
        "file_size_total": sum(int(entry.get("size_bytes") or 0) for entry in radars),
        "interim": bool(root.get("interim", False)),
        "upload_complete": bool(root.get("upload_complete", True)),
        "spatial_source": root.get("spatial_source", ""),
        "spatial_updated_at": root.get("spatial_updated_at", ""),
        "by_radar": by_radar,
    }


def _pvol_radar_by_slug(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("radar")): entry
        for entry in root.get("radars", [])
        if isinstance(entry, dict) and entry.get("radar")
    }


def pvol_coverage_keys(root: dict[str, Any], radar: str | None = None, start: str | None = None, end: str | None = None) -> list[tuple[dict[str, Any], str]]:
    radar_entries = _pvol_radar_by_slug(root)
    selected = [radar_entries[radar]] if radar and radar in radar_entries else list(radar_entries.values())
    start_year = str(start)[:4] if start else ""
    end_year = str(end)[:4] if end else ""
    keys: list[tuple[dict[str, Any], str]] = []
    for entry in selected:
        for key in entry.get("coverage_keys", []):
            key_text = str(key)
            key_year = next((part for part in key_text.split("/") if part.isdigit() and len(part) == 4), "")
            if start_year and key_year and key_year < start_year:
                continue
            if end_year and key_year and key_year > end_year:
                continue
            keys.append((entry, key_text))
    return keys


def pvol_item_from_coverage_day(root: dict[str, Any], radar_entry: dict[str, Any], day: dict[str, Any], public_base_url: str) -> CatalogItem:
    radar = str(radar_entry.get("radar") or day.get("radar") or "")
    radar_num = str(radar_entry.get("radar_num") or RADAR_NUM_BY_SLUG.get(radar, ""))
    date = str(day.get("date") or "")
    pulse_counts = day.get("pulse_counts", {}) if isinstance(day.get("pulse_counts"), dict) else {}
    pulses = sorted(str(pulse) for pulse in pulse_counts)
    catalog_key = str(day.get("catalog_key") or "")
    pvol_prefix = str(day.get("pvol_prefix") or "")
    root_attrs: dict[str, Any] = {
        "uk_wsr:source_type": "raw_volume_day",
        "interim": bool(root.get("interim", False)),
        "upload_complete": bool(root.get("upload_complete", True)),
        "file_count": int(day.get("file_count") or 0),
        "catalog_key": catalog_key,
        "pvol_prefix": pvol_prefix,
        "uk_wsr:pvol_day_catalog_key": catalog_key,
    }
    root_attrs.update(pvol_spatial_root_attrs(root, radar_entry))
    return CatalogItem(
        radar=radar,
        radar_num=radar_num,
        date=date,
        path=pvol_prefix,
        file_size=int(day.get("size_bytes") or 0),
        modified_time=0.0,
        pulses=pulses,
        times=[],
        quantities=[],
        quantity_records=[],
        object_key=catalog_key,
        object_url=join_catalog_url(public_base_url, catalog_key) if catalog_key else "",
        source_type="raw_volume_day",
        raw_volumes=[],
        validation_status="interim" if root.get("interim", False) else "published",
        root_attrs=root_attrs,
        quantities_by_pulse={pulse: [] for pulse in pulses},
        times_by_pulse={pulse: [] for pulse in pulses},
    )


def pvol_items_from_coverage(root: dict[str, Any], radar_entry: dict[str, Any], coverage: dict[str, Any], public_base_url: str) -> list[CatalogItem]:
    items = [
        pvol_item_from_coverage_day(root, radar_entry, day, public_base_url)
        for day in coverage.get("days", [])
        if isinstance(day, dict) and day.get("date")
    ]
    return sorted(items, key=lambda item: (item.radar, item.date))


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(entry) for entry in value if entry not in (None, "")]
    if isinstance(value, tuple):
        return [str(entry) for entry in value if entry not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _as_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for entry in value:
        try:
            result.append(int(entry))
        except (TypeError, ValueError):
            return []
    return result


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _records_from_field_entry(entry: dict[str, Any]) -> list[QuantityRecord]:
    pulse = str(entry.get("pulse") or "")
    time = str(entry.get("time") or "")
    default_dataset = str(entry.get("dataset") or entry.get("sweep") or "1")
    default_kind = str(entry.get("kind") or "data")
    default_elevation = _optional_float(
        entry.get("elevation_deg") or entry.get("elevation") or entry.get("elangle")
    )
    default_height = _optional_float(entry.get("nominal_height_m") or entry.get("height_m"))
    default_shape = _as_int_list(entry.get("shape"))
    containers = []
    for name in ("quantity_records", "fields", "variables", "quantities"):
        value = entry.get(name)
        if isinstance(value, list):
            containers.extend(value)
    records: list[QuantityRecord] = []
    for index, raw in enumerate(containers, start=1):
        if isinstance(raw, str):
            field = {"quantity": raw}
        elif isinstance(raw, dict):
            field = raw
        else:
            continue
        quantity = str(field.get("quantity") or field.get("variable") or field.get("name") or "")
        if not quantity:
            continue
        dataset = str(field.get("dataset") or field.get("dataset_index") or field.get("sweep") or default_dataset)
        kind = str(field.get("kind") or default_kind)
        field_index = str(field.get("index") or field.get("data_index") or field.get("field_index") or index)
        records.append(
            QuantityRecord(
                pulse=pulse,
                time=time,
                dataset=dataset,
                kind=kind,
                index=field_index,
                quantity=quantity,
                shape=_as_int_list(field.get("shape")) or default_shape,
                dtype=str(field.get("dtype") or ""),
                elevation_deg=_optional_float(
                    field.get("elevation_deg") or field.get("elevation") or field.get("elangle")
                )
                if any(name in field for name in ("elevation_deg", "elevation", "elangle"))
                else default_elevation,
                nominal_height_m=_optional_float(field.get("nominal_height_m") or field.get("height_m"))
                if any(name in field for name in ("nominal_height_m", "height_m"))
                else default_height,
            )
        )
    for dataset_entry in entry.get("datasets", []) if isinstance(entry.get("datasets"), list) else []:
        if not isinstance(dataset_entry, dict):
            continue
        dataset = str(dataset_entry.get("dataset") or dataset_entry.get("dataset_index") or dataset_entry.get("sweep") or default_dataset)
        dataset_elevation = _optional_float(
            dataset_entry.get("elevation_deg") or dataset_entry.get("elevation") or dataset_entry.get("elangle")
        )
        dataset_height = _optional_float(dataset_entry.get("nominal_height_m") or dataset_entry.get("height_m"))
        dataset_shape = _as_int_list(dataset_entry.get("shape")) or default_shape
        for index, quantity in enumerate(
            _as_text_list(dataset_entry.get("quantities") or dataset_entry.get("variables")),
            start=1,
        ):
            records.append(
                QuantityRecord(
                    pulse=pulse,
                    time=time,
                    dataset=dataset,
                    kind=str(dataset_entry.get("kind") or default_kind),
                    index=str(index),
                    quantity=quantity,
                    shape=dataset_shape,
                    dtype=str(dataset_entry.get("dtype") or ""),
                    elevation_deg=dataset_elevation if dataset_elevation is not None else default_elevation,
                    nominal_height_m=dataset_height if dataset_height is not None else default_height,
                )
            )
    return records


def _merge_field_index_files(day_files: list[dict[str, Any]], field_index: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not field_index or not isinstance(field_index.get("files"), list):
        return day_files
    indexed_files = [entry for entry in field_index.get("files", []) if isinstance(entry, dict)]
    if not day_files:
        return indexed_files
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in indexed_files:
        key = (
            str(entry.get("pulse") or ""),
            str(entry.get("time") or ""),
            str(entry.get("filename") or entry.get("object_key") or ""),
        )
        lookup[key] = entry
        lookup[(key[0], key[1], "")] = entry
    merged: list[dict[str, Any]] = []
    for entry in day_files:
        key = (
            str(entry.get("pulse") or ""),
            str(entry.get("time") or ""),
            str(entry.get("filename") or entry.get("object_key") or ""),
        )
        sidecar = lookup.get(key) or lookup.get((key[0], key[1], ""))
        merged.append({**entry, **sidecar} if sidecar else entry)
    return merged


def pvol_item_from_day_catalog(
    root: dict[str, Any],
    base_item: CatalogItem,
    day: dict[str, Any],
    public_base_url: str,
    field_index: dict[str, Any] | None = None,
) -> CatalogItem:
    day_files = [entry for entry in day.get("files", []) if isinstance(entry, dict)]
    files = _merge_field_index_files(day_files, field_index)
    records_by_file: dict[tuple[str, str, str], list[QuantityRecord]] = {}
    quantity_records: list[QuantityRecord] = []
    for entry in files:
        records = _records_from_field_entry(entry)
        key = (
            str(entry.get("pulse") or ""),
            str(entry.get("time") or ""),
            str(entry.get("filename") or entry.get("object_key") or ""),
        )
        records_by_file[key] = records
        quantity_records.extend(records)
    raw_volumes = [
        RawVolumeRecord(
            pulse=str(entry.get("pulse") or ""),
            time=str(entry.get("time") or ""),
            path=str(entry.get("object_url") or ""),
            filename=str(entry.get("filename") or ""),
            file_size=int(entry.get("size_bytes") or 0),
            modified_time=float(entry.get("modified_time") or 0.0),
            object_key=str(entry.get("object_key") or ""),
            object_url=str(entry.get("object_url") or join_catalog_url(public_base_url, str(entry.get("object_key") or ""))),
            quantities=sorted(
                {
                    record.quantity
                    for record in records_by_file.get(
                        (
                            str(entry.get("pulse") or ""),
                            str(entry.get("time") or ""),
                            str(entry.get("filename") or entry.get("object_key") or ""),
                        ),
                        [],
                    )
                }
                or set(_as_text_list(entry.get("quantities") or entry.get("variables")))
            ),
        )
        for entry in files
        if entry.get("pulse") and entry.get("time") and entry.get("filename")
    ]
    pulses = sorted({volume.pulse for volume in raw_volumes}) or sorted(str(pulse) for pulse in day.get("pulses", []))
    times_by_pulse = {
        str(pulse): [str(value) for value in times]
        for pulse, times in (day.get("times_by_pulse", {}) if isinstance(day.get("times_by_pulse"), dict) else {}).items()
        if isinstance(times, list)
    }
    if not times_by_pulse:
        for pulse in pulses:
            times_by_pulse[pulse] = sorted({volume.time for volume in raw_volumes if volume.pulse == pulse})
    quantities_by_pulse = {
        pulse: sorted({record.quantity for record in quantity_records if record.pulse == pulse})
        for pulse in pulses
    }
    root_attrs = dict(base_item.root_attrs)
    root_attrs.update(
        {
            "catalog_key": str(day.get("catalog_key") or root_attrs.get("catalog_key", "")),
            "pvol_prefix": str(day.get("pvol_prefix") or root_attrs.get("pvol_prefix", "")),
            "interim": bool(day.get("interim", root.get("interim", False))),
            "upload_complete": bool(day.get("upload_complete", root.get("upload_complete", True))),
            "file_count": int(day.get("file_count") or len(raw_volumes)),
            "field_index_loaded": bool(quantity_records),
        }
    )
    return CatalogItem(
        radar=str(day.get("radar") or base_item.radar),
        radar_num=str(day.get("radar_num") or base_item.radar_num),
        date=str(day.get("date") or base_item.date),
        path=base_item.path,
        file_size=int(day.get("size_bytes") or base_item.file_size),
        modified_time=max((volume.modified_time for volume in raw_volumes), default=base_item.modified_time),
        pulses=sorted({record.pulse for record in quantity_records}) or pulses,
        times=sorted({record.time for record in quantity_records}) or sorted({time for times in times_by_pulse.values() for time in times}),
        quantities=sorted({record.quantity for record in quantity_records}),
        quantity_records=quantity_records,
        object_key=base_item.object_key,
        object_url=base_item.object_url,
        source_type="raw_volume_day",
        raw_volumes=raw_volumes,
        validation_status="interim" if root_attrs.get("interim") else "published",
        root_attrs=root_attrs,
        quantities_by_pulse=quantities_by_pulse or {pulse: [] for pulse in pulses},
        times_by_pulse=times_by_pulse,
    )
