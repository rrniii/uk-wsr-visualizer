"""Catalog scanning for UK WSR aggregate HDF5 files."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .dependencies import require_h5py
from .object_store import aggregate_object_key, join_object_url, raw_volume_object_key
from .radars import RADAR_BY_SLUG, RADAR_NUM_BY_SLUG

EARTH_RADIUS_M = 6_371_000.0

AGGREGATE_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate\.h5$")
RAW_VOLUME_RE = re.compile(
    r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate_(?P<pulse>[^_]+)_(?P<time>[0-9]{4})\.h5$"
)
DATA_GROUP_RE = re.compile(
    r"^(?P<pulse>[^/]+)/(?P<time>[0-9]{4})/dataset(?P<dataset>[0-9]+)/(?P<kind>data|quality)(?P<index>[0-9]+)$"
)
ROOT_DATA_GROUP_RE = re.compile(r"^dataset(?P<dataset>[0-9]+)/(?P<kind>data|quality)(?P<index>[0-9]+)$")
# A PVOL catalog is rooted below a product prefix.  The product may be the
# dual-polarisation archive or the separately published pre-dual archive, so
# do not bake a single object-store prefix into URL recognition.
PVOL_ROOT_SUFFIX = "/catalog/pvol/catalog.json"


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


def _scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        import numpy as np  # type: ignore

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            if value.shape == ():
                return _scalar(value.item())
            if value.size == 1:
                return _scalar(value.reshape(-1)[0])
            return [_scalar(v) for v in value.tolist()]
    except ImportError:
        pass
    return value


def _quantity_from_group(group: Any) -> str:
    what = group.get("what")
    if what is not None and "quantity" in what.attrs:
        return str(_scalar(what.attrs["quantity"]))
    return "<missing quantity>"


def _attrs(group: Any | None) -> dict[str, Any]:
    if group is None:
        return {}
    return {key: _scalar(value) for key, value in group.attrs.items()}


def _float_attr(attrs: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in attrs and attrs[name] not in ("", None):
            return float(attrs[name])
    return None


def _spatial_metadata(h5: Any) -> dict[str, Any]:
    for pulse in h5:
        pulse_group = h5[pulse]
        if not hasattr(pulse_group, "items"):
            continue
        for time in pulse_group:
            time_group = pulse_group[time]
            if not hasattr(time_group, "get"):
                continue
            where = _attrs(time_group.get("where"))
            lat = _float_attr(where, "lat", "latitude", "site_latitude")
            lon = _float_attr(where, "lon", "longitude", "site_longitude")
            if lat is None or lon is None:
                continue
            max_range_m: float | None = None
            for dataset_name in time_group:
                if not str(dataset_name).startswith("dataset"):
                    continue
                dataset_where = _attrs(time_group[dataset_name].get("where"))
                nbins = _float_attr(dataset_where, "nbins")
                rscale = _float_attr(dataset_where, "rscale")
                rstart = _float_attr(dataset_where, "rstart") or 0.0
                if nbins is not None and rscale is not None:
                    max_range_m = rstart * 1000.0 + nbins * rscale
                    break
            if max_range_m is None:
                max_range_m = 0.0
            lat_delta = math.degrees(max_range_m / EARTH_RADIUS_M)
            lon_delta = math.degrees(max_range_m / (EARTH_RADIUS_M * max(math.cos(math.radians(lat)), 0.01)))
            return {
                "latitude": lat,
                "longitude": lon,
                "height_m": _float_attr(where, "height", "height_m", "altitude"),
                "max_range_m": max_range_m,
                "bbox": [lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta],
            }
    return {}


def _spatial_metadata_root_volume(h5: Any) -> dict[str, Any]:
    where = _attrs(h5.get("where")) if hasattr(h5, "get") else {}
    lat = _float_attr(where, "lat", "latitude", "site_latitude")
    lon = _float_attr(where, "lon", "longitude", "site_longitude")
    if lat is None or lon is None:
        return {}
    max_range_m: float | None = None
    for dataset_name in h5:
        if not str(dataset_name).startswith("dataset"):
            continue
        dataset_where = _attrs(h5[dataset_name].get("where"))
        nbins = _float_attr(dataset_where, "nbins")
        rscale = _float_attr(dataset_where, "rscale")
        rstart = _float_attr(dataset_where, "rstart") or 0.0
        if nbins is not None and rscale is not None:
            max_range_m = rstart * 1000.0 + nbins * rscale
            break
    if max_range_m is None:
        max_range_m = 0.0
    lat_delta = math.degrees(max_range_m / EARTH_RADIUS_M)
    lon_delta = math.degrees(max_range_m / (EARTH_RADIUS_M * max(math.cos(math.radians(lat)), 0.01)))
    return {
        "latitude": lat,
        "longitude": lon,
        "height_m": _float_attr(where, "height", "height_m", "altitude"),
        "max_range_m": max_range_m,
        "bbox": [lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta],
    }


def _nominal_dataset_height(top_where: dict[str, Any], dataset_where: dict[str, Any]) -> float | None:
    direct = _float_attr(dataset_where, "height", "height_m", "altitude")
    if direct is not None:
        return direct
    elevation = _float_attr(dataset_where, "elangle", "elevation", "elevation_angle")
    nbins = _float_attr(dataset_where, "nbins")
    rscale = _float_attr(dataset_where, "rscale")
    if elevation is None or nbins is None or rscale is None:
        return None
    rstart_m = (_float_attr(dataset_where, "rstart") or 0.0) * 1000.0
    midpoint_range_m = rstart_m + (nbins * rscale) / 2.0
    site_height_m = _float_attr(top_where, "height", "height_m", "altitude") or 0.0
    return site_height_m + midpoint_range_m * math.sin(math.radians(elevation))


def iter_aggregate_files(base: Path, radar: str | None = None, year: str | None = None):
    roots: list[Path]
    if radar:
        roots = [base / radar]
    else:
        roots = [base / site for site in sorted(RADAR_BY_SLUG)]
    for root in roots:
        if year:
            root = root / year
        if not root.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in sorted(filenames):
                match = AGGREGATE_RE.match(filename)
                if match:
                    yield Path(dirpath) / filename


def iter_raw_volume_files(base: Path, radar: str | None = None, year: str | None = None, date: str | None = None):
    roots: list[Path]
    if radar:
        roots = [base / radar]
    else:
        roots = [base / site for site in sorted(RADAR_BY_SLUG)]
    normalized_date = date.replace("-", "") if date else None
    for root in roots:
        if year:
            root = root / year
        if not root.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in sorted(filenames):
                match = RAW_VOLUME_RE.match(filename)
                if match and (not normalized_date or match.group("date") == normalized_date):
                    yield Path(dirpath) / filename


def _records_from_root_volume(h5: Any, pulse: str, time: str) -> list[QuantityRecord]:
    records: list[QuantityRecord] = []

    def visit(name: str, obj: Any) -> None:
        h5py = require_h5py()
        if not isinstance(obj, h5py.Group):
            return
        group_match = ROOT_DATA_GROUP_RE.match(name)
        if not group_match:
            return
        data = obj.get("data")
        groups = group_match.groupdict()
        dataset_group = h5[f"dataset{groups['dataset']}"]
        top_where = _attrs(h5.get("where"))
        dataset_where = _attrs(dataset_group.get("where"))
        records.append(
            QuantityRecord(
                pulse=pulse,
                time=time,
                **groups,
                quantity=_quantity_from_group(obj),
                shape=list(data.shape) if data is not None else [],
                dtype=str(data.dtype) if data is not None else "",
                elevation_deg=_float_attr(dataset_where, "elangle", "elevation", "elevation_angle"),
                nominal_height_m=_nominal_dataset_height(top_where, dataset_where),
            )
        )

    h5.visititems(visit)
    return records


def scan_raw_volume(path: Path, raw_volume_base: Path, object_store_base: str = "") -> tuple[str, str, str, RawVolumeRecord, list[QuantityRecord], dict[str, Any]]:
    h5py = require_h5py()
    match = RAW_VOLUME_RE.match(path.name)
    if not match:
        raise ValueError(f"not a UK WSR Visualizer raw-volume filename: {path}")
    date = match.group("date")
    radar_num = match.group("num")
    pulse = match.group("pulse")
    time = match.group("time")
    radar = path.parent.parent.parent.parent.name if path.parent.parent.name == date else ""
    if not radar:
        radar = next((slug for slug, num in RADAR_NUM_BY_SLUG.items() if num == radar_num), "")
    if not radar:
        raise ValueError(f"could not infer radar for {path}")

    with h5py.File(path, "r") as h5:
        root_attrs = {key: _scalar(value) for key, value in h5.attrs.items()}
        root_attrs["uk_wsr:source_type"] = "raw_volume_day"
        root_attrs["uk_wsr:spatial"] = _spatial_metadata_root_volume(h5)
        records = _records_from_root_volume(h5, pulse, time)

    stat = path.stat()
    object_key = raw_volume_object_key(radar, date, pulse, path.name)
    volume = RawVolumeRecord(
        pulse=pulse,
        time=time,
        path=str(path),
        filename=path.name,
        file_size=stat.st_size,
        modified_time=stat.st_mtime,
        object_key=object_key,
        object_url=join_object_url(object_store_base, object_key),
        quantities=sorted({record.quantity for record in records}),
    )
    return radar, radar_num, date, volume, records, root_attrs


def scan_raw_volume_fast(path: Path, raw_volume_base: Path, object_store_base: str = "") -> tuple[str, str, str, RawVolumeRecord]:
    match = RAW_VOLUME_RE.match(path.name)
    if not match:
        raise ValueError(f"not a UK WSR Visualizer raw-volume filename: {path}")
    date = match.group("date")
    radar_num = match.group("num")
    pulse = match.group("pulse")
    time = match.group("time")
    radar = path.parent.parent.parent.parent.name if path.parent.parent.name == date else ""
    if not radar:
        radar = next((slug for slug, num in RADAR_NUM_BY_SLUG.items() if num == radar_num), "")
    if not radar:
        raise ValueError(f"could not infer radar for {path}")
    stat = path.stat()
    object_key = raw_volume_object_key(radar, date, pulse, path.name)
    volume = RawVolumeRecord(
        pulse=pulse,
        time=time,
        path=str(path),
        filename=path.name,
        file_size=stat.st_size,
        modified_time=stat.st_mtime,
        object_key=object_key,
        object_url=join_object_url(object_store_base, object_key),
        quantities=[],
    )
    return radar, radar_num, date, volume


def scan_aggregate(path: Path, aggregate_base: Path, object_store_base: str = "") -> CatalogItem:
    h5py = require_h5py()
    match = AGGREGATE_RE.match(path.name)
    if not match:
        raise ValueError(f"not a UK WSR aggregate filename: {path}")
    date = match.group("date")
    radar_num = match.group("num")
    radar = path.parent.parent.name if path.parent.name.isdigit() else ""
    if not radar:
        radar = next((slug for slug, num in RADAR_NUM_BY_SLUG.items() if num == radar_num), "")
    if not radar:
        raise ValueError(f"could not infer radar for {path}")

    records: list[QuantityRecord] = []
    root_attrs: dict[str, Any] = {}
    with h5py.File(path, "r") as h5:
        root_attrs = {key: _scalar(value) for key, value in h5.attrs.items()}
        spatial = _spatial_metadata(h5)
        if spatial:
            root_attrs["uk_wsr:spatial"] = spatial

        def visit(name: str, obj: Any) -> None:
            if not isinstance(obj, h5py.Group):
                return
            group_match = DATA_GROUP_RE.match(name)
            if not group_match:
                return
            data = obj.get("data")
            groups = group_match.groupdict()
            time_group = h5[f"{groups['pulse']}/{groups['time']}"]
            dataset_group = h5[f"{groups['pulse']}/{groups['time']}/dataset{groups['dataset']}"]
            top_where = _attrs(time_group.get("where"))
            dataset_where = _attrs(dataset_group.get("where"))
            records.append(
                QuantityRecord(
                    **groups,
                    quantity=_quantity_from_group(obj),
                    shape=list(data.shape) if data is not None else [],
                    dtype=str(data.dtype) if data is not None else "",
                    elevation_deg=_float_attr(dataset_where, "elangle", "elevation", "elevation_angle"),
                    nominal_height_m=_nominal_dataset_height(top_where, dataset_where),
                )
            )

        h5.visititems(visit)

    stat = path.stat()
    object_key = aggregate_object_key(radar, date)
    quantities_by_pulse = {
        pulse: sorted({record.quantity for record in records if record.pulse == pulse})
        for pulse in sorted({record.pulse for record in records})
    }
    times_by_pulse = {
        pulse: sorted({record.time for record in records if record.pulse == pulse})
        for pulse in sorted({record.pulse for record in records})
    }
    return CatalogItem(
        radar=radar,
        radar_num=radar_num,
        date=date,
        path=str(path),
        file_size=stat.st_size,
        modified_time=stat.st_mtime,
        pulses=sorted({record.pulse for record in records}),
        times=sorted({record.time for record in records}),
        quantities=sorted({record.quantity for record in records}),
        quantity_records=records,
        object_key=object_key,
        object_url=join_object_url(object_store_base, object_key),
        root_attrs=root_attrs,
        quantities_by_pulse=quantities_by_pulse,
        times_by_pulse=times_by_pulse,
    )


def scan_aggregate_fast(path: Path, aggregate_base: Path, object_store_base: str = "") -> CatalogItem:
    match = AGGREGATE_RE.match(path.name)
    if not match:
        raise ValueError(f"not a UK WSR aggregate filename: {path}")
    date = match.group("date")
    radar_num = match.group("num")
    radar = path.parent.parent.name if path.parent.name.isdigit() else ""
    if not radar:
        radar = next((slug for slug, num in RADAR_NUM_BY_SLUG.items() if num == radar_num), "")
    if not radar:
        raise ValueError(f"could not infer radar for {path}")

    stat = path.stat()
    object_key = aggregate_object_key(radar, date)
    return CatalogItem(
        radar=radar,
        radar_num=radar_num,
        date=date,
        path=str(path),
        file_size=stat.st_size,
        modified_time=stat.st_mtime,
        pulses=[],
        times=[],
        quantities=[],
        quantity_records=[],
        object_key=object_key,
        object_url=join_object_url(object_store_base, object_key),
        root_attrs={"uk_wsr:catalog_mode": "fast"},
        quantities_by_pulse={},
        times_by_pulse={},
    )


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
