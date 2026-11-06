"""Inspect local HDF5 files without changing their contents."""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

from .dependencies import require_h5py
from .object_store import aggregate_object_key, raw_volume_object_key, join_object_url
from .radars import RADAR_BY_SLUG, RADAR_NUM_BY_SLUG
from .catalog_models import CatalogItem, QuantityRecord, RawVolumeRecord

EARTH_RADIUS_M = 6_371_000.0

AGGREGATE_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate\.h5$")

RAW_VOLUME_RE = re.compile(
    r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate_(?P<pulse>[^_]+)_(?P<time>[0-9]{4})\.h5$"
)

DATA_GROUP_RE = re.compile(
    r"^(?P<pulse>[^/]+)/(?P<time>[0-9]{4})/dataset(?P<dataset>[0-9]+)/(?P<kind>data|quality)(?P<index>[0-9]+)$"
)

ROOT_DATA_GROUP_RE = re.compile(r"^dataset(?P<dataset>[0-9]+)/(?P<kind>data|quality)(?P<index>[0-9]+)$")



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
