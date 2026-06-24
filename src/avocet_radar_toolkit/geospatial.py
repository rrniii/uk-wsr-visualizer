"""Geospatial field extraction and radar-centred grid helpers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .dependencies import require_h5py, require_numpy
from .export_types import FieldSelection
from .radars import require_radar

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class RadarGridMetadata:
    radar: str
    date: str
    pulse: str
    time: str
    quantity: str
    dataset: str
    latitude: float
    longitude: float
    height_m: float | None
    elevation_deg: float | None
    rstart_km: float
    rscale_m: float
    nbins: int
    nrays: int
    nodata: float = -9999.0
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def max_range_m(self) -> float:
        return self.rstart_km * 1000.0 + self.rscale_m * self.nbins

    @property
    def projected_crs_proj4(self) -> str:
        return (
            f"+proj=aeqd +lat_0={self.latitude} +lon_0={self.longitude} "
            "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )

    def projected_bbox(self) -> list[float]:
        radius = self.max_range_m
        return [-radius, -radius, radius, radius]

    def geographic_bbox(self) -> list[float]:
        radius = self.max_range_m
        lat_delta = math.degrees(radius / EARTH_RADIUS_M)
        cos_lat = max(math.cos(math.radians(self.latitude)), 0.01)
        lon_delta = math.degrees(radius / (EARTH_RADIUS_M * cos_lat))
        return [
            self.longitude - lon_delta,
            self.latitude - lat_delta,
            self.longitude + lon_delta,
            self.latitude + lat_delta,
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "max_range_m": self.max_range_m,
            "projected_crs_proj4": self.projected_crs_proj4,
            "projected_bbox": self.projected_bbox(),
            "geographic_bbox": self.geographic_bbox(),
        }


@dataclass(frozen=True)
class CartesianField:
    values: Any
    x: Any
    y: Any
    metadata: RadarGridMetadata

    @property
    def pixel_size_m(self) -> float:
        return float(abs(self.x[1] - self.x[0])) if len(self.x) > 1 else self.metadata.rscale_m

    @property
    def west(self) -> float:
        return float(self.x[0] - self.pixel_size_m / 2.0)

    @property
    def north(self) -> float:
        return float(self.y[0] + self.pixel_size_m / 2.0)


@dataclass(frozen=True)
class RadarBinLocation:
    row: int
    column: int
    range_m: float
    range_km: float
    azimuth_deg: float
    x_m: float
    y_m: float
    longitude: float
    latitude: float
    elevation_deg: float | None


def scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        np = require_numpy()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            if value.shape == ():
                return scalar(value.item())
            if value.size == 1:
                return scalar(value.reshape(-1)[0])
            return [scalar(v) for v in value.tolist()]
    except RuntimeError:
        pass
    return value


def _attrs(group: Any | None) -> dict[str, Any]:
    if group is None:
        return {}
    return {key: scalar(value) for key, value in group.attrs.items()}


def _attr_float(attrs: dict[str, Any], keys: tuple[str, ...], default: float | None = None) -> float | None:
    for key in keys:
        if key in attrs and attrs[key] not in ("", None):
            return float(attrs[key])
    return default


def _attr_int(attrs: dict[str, Any], keys: tuple[str, ...], default: int | None = None) -> int | None:
    value = _attr_float(attrs, keys, None)
    return int(value) if value is not None else default


def _apply_odim_data_scaling(data: Any, what_attrs: dict[str, Any]) -> Any:
    np = require_numpy()
    raw = np.asarray(data)
    output = raw.astype("float32", copy=True)
    nodata = _attr_float(what_attrs, ("nodata", "no_data"), None)
    undetect = _attr_float(what_attrs, ("undetect",), None)
    missing = np.zeros(raw.shape, dtype=bool)
    if nodata is not None:
        missing |= raw == nodata
    if undetect is not None:
        missing |= raw == undetect
    gain = _attr_float(what_attrs, ("gain",), 1.0)
    offset = _attr_float(what_attrs, ("offset",), 0.0)
    output = output * float(gain if gain is not None else 1.0) + float(offset if offset is not None else 0.0)
    output[missing] = np.nan
    return output


def _quantity_from_group(group: Any) -> str:
    what = group.get("what")
    if what is not None and "quantity" in what.attrs:
        return str(scalar(what.attrs["quantity"]))
    return ""


def _dataset_name_from_path(name: str) -> str:
    for part in name.split("/"):
        if part.startswith("dataset"):
            return part
    return ""


def _dataset_matches(name: str, dataset: str | None) -> bool:
    if not dataset:
        return True
    wanted = dataset if dataset.startswith("dataset") else f"dataset{dataset}"
    return _dataset_name_from_path(name) == wanted


def find_field_group(h5: Any, selection: FieldSelection) -> tuple[str, Any]:
    h5py = require_h5py()
    prefix = f"{selection.pulse}/{selection.time}/"
    matches: list[tuple[str, Any]] = []

    def visit(name: str, obj: Any) -> None:
        if not isinstance(obj, h5py.Group):
            return
        if not name.startswith(prefix) or "/data" not in name:
            return
        if not _dataset_matches(name, selection.dataset):
            return
        if _quantity_from_group(obj) == selection.quantity:
            matches.append((name, obj))

    h5.visititems(visit)
    if not matches:
        def visit_root_volume(name: str, obj: Any) -> None:
            if not isinstance(obj, h5py.Group):
                return
            if not name.startswith("dataset") or "/data" not in name:
                return
            if not _dataset_matches(name, selection.dataset):
                return
            if _quantity_from_group(obj) == selection.quantity:
                matches.append((name, obj))

        h5.visititems(visit_root_volume)
    if not matches:
        raise ValueError(
            f"no field found for pulse={selection.pulse}, time={selection.time}, "
            f"quantity={selection.quantity}, dataset={selection.dataset or 'auto'}"
        )
    if selection.cappi_height_m is not None and selection.dataset is None:
        return min(matches, key=lambda match: _height_score(h5, match[0], selection.cappi_height_m))
    return matches[0]


def _dataset_where_attrs(h5: Any, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = name.split("/")
    if parts and parts[0].startswith("dataset"):
        dataset_group = h5[parts[0]]
        return _attrs(h5.get("where")), _attrs(dataset_group.get("where"))
    if len(parts) < 3:
        return {}, {}
    time_group = h5[f"{parts[0]}/{parts[1]}"]
    dataset_group = h5[f"{parts[0]}/{parts[1]}/{parts[2]}"]
    return _attrs(time_group.get("where")), _attrs(dataset_group.get("where"))


def dataset_nominal_height_m(top_where: dict[str, Any], dataset_where: dict[str, Any]) -> float | None:
    direct = _attr_float(dataset_where, ("height", "height_m", "altitude"), None)
    if direct is not None:
        return direct
    elevation = _attr_float(dataset_where, ("elangle", "elevation", "elevation_angle"), None)
    nbins = _attr_float(dataset_where, ("nbins",), None)
    rscale = _attr_float(dataset_where, ("rscale",), None)
    if elevation is None or nbins is None or rscale is None:
        return None
    rstart_m = (_attr_float(dataset_where, ("rstart",), 0.0) or 0.0) * 1000.0
    midpoint_range_m = rstart_m + (nbins * rscale) / 2.0
    site_height_m = _attr_float(top_where, ("height", "height_m", "altitude"), 0.0) or 0.0
    return site_height_m + midpoint_range_m * math.sin(math.radians(elevation))


def _height_score(h5: Any, name: str, target_height_m: float) -> float:
    top_where, dataset_where = _dataset_where_attrs(h5, name)
    height = dataset_nominal_height_m(top_where, dataset_where)
    if height is None:
        return float("inf")
    return abs(height - target_height_m)


def _filter_float_value(filters: dict[str, Any] | None, key: str) -> float | None:
    if not filters:
        return None
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def field_selection_from_request(request: Any) -> FieldSelection:
    return FieldSelection(
        pulse=request.pulse or "",
        time=request.time or "",
        quantity=request.quantity or "",
        dataset=request.dataset,
        cappi_height_m=_filter_float_value(getattr(request, "filters", None), "cappi_height_m"),
    )


def read_polar_field(source: Path, radar: str, date: str, selection: FieldSelection) -> tuple[Any, RadarGridMetadata]:
    h5py = require_h5py()
    np = require_numpy()
    site = require_radar(radar)

    with h5py.File(source, "r") as h5:
        name, group = find_field_group(h5, selection)
        raw_data = group["data"][()]
        parts = name.split("/")
        dataset_name = _dataset_name_from_path(name) or selection.dataset or ""
        if parts and parts[0].startswith("dataset"):
            top_where = _attrs(h5.get("where"))
            dataset_group = h5[dataset_name]
        else:
            time_group = h5[f"{selection.pulse}/{selection.time}"]
            top_where = _attrs(time_group.get("where"))
            dataset_group = h5[f"{selection.pulse}/{selection.time}/{dataset_name}"]
        dataset_where = _attrs(dataset_group.get("where"))
        data_what = _attrs(group.get("what"))
        data = _apply_odim_data_scaling(raw_data, data_what)
        nominal_height_m = dataset_nominal_height_m(top_where, dataset_where)

    nrays, nbins = int(data.shape[0]), int(data.shape[1])
    latitude = _attr_float(top_where, ("lat", "latitude", "site_latitude"), site.latitude)
    longitude = _attr_float(top_where, ("lon", "longitude", "site_longitude"), site.longitude)
    if latitude is None or longitude is None:
        raise ValueError(
            "radar latitude/longitude are missing from ODIM where attrs and the local radar registry; "
            f"cannot georeference {radar}"
        )
    metadata = RadarGridMetadata(
        radar=radar,
        date=date,
        pulse=selection.pulse,
        time=selection.time,
        quantity=selection.quantity,
        dataset=dataset_name,
        latitude=latitude,
        longitude=longitude,
        height_m=_attr_float(top_where, ("height", "height_m", "altitude"), None),
        elevation_deg=_attr_float(dataset_where | top_where, ("elangle", "elevation", "elevation_angle"), None),
        rstart_km=float(_attr_float(dataset_where, ("rstart",), 0.0) or 0.0),
        rscale_m=float(_attr_float(dataset_where, ("rscale",), 1000.0) or 1000.0),
        nbins=int(_attr_int(dataset_where, ("nbins",), nbins) or nbins),
        nrays=int(_attr_int(dataset_where, ("nrays",), nrays) or nrays),
        attrs={
            "where": top_where,
            "dataset_where": dataset_where,
            "what": data_what,
            "avocet:odim_scaling_applied": True,
            "avocet:nominal_height_m": nominal_height_m,
            "avocet:cappi_target_height_m": selection.cappi_height_m,
        },
    )
    return data, metadata


def _filter_float(filters: dict[str, Any], key: str) -> float | None:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def apply_polar_filters(data: Any, metadata: RadarGridMetadata, filters: dict[str, Any] | None = None) -> Any:
    filters = filters or {}
    if not filters:
        return data
    np = require_numpy()
    output = np.asarray(data, dtype="float32").copy()
    keep = np.ones(output.shape, dtype=bool)

    min_range = _filter_float(filters, "min_range_km")
    max_range = _filter_float(filters, "max_range_km")
    if min_range is not None or max_range is not None:
        ranges_km = (metadata.rstart_km * 1000.0 + (np.arange(output.shape[1]) + 0.5) * metadata.rscale_m) / 1000.0
        range_keep = np.ones(output.shape[1], dtype=bool)
        if min_range is not None:
            range_keep &= ranges_km >= min_range
        if max_range is not None:
            range_keep &= ranges_km <= max_range
        keep &= range_keep[np.newaxis, :]

    min_azimuth = _filter_float(filters, "min_azimuth_deg")
    max_azimuth = _filter_float(filters, "max_azimuth_deg")
    if min_azimuth is not None or max_azimuth is not None:
        azimuths = ((np.arange(output.shape[0]) + 0.5) / max(output.shape[0], 1)) * 360.0
        min_azimuth = 0.0 if min_azimuth is None else min_azimuth % 360.0
        max_azimuth = 360.0 if max_azimuth is None else max_azimuth % 360.0
        if min_azimuth <= max_azimuth:
            azimuth_keep = (azimuths >= min_azimuth) & (azimuths <= max_azimuth)
        else:
            azimuth_keep = (azimuths >= min_azimuth) | (azimuths <= max_azimuth)
        keep &= azimuth_keep[:, np.newaxis]

    min_value = _filter_float(filters, "min_value")
    max_value = _filter_float(filters, "max_value")
    if min_value is not None:
        keep &= output >= min_value
    if max_value is not None:
        keep &= output <= max_value

    output[~keep] = np.nan
    return output


def polar_to_cartesian(data: Any, metadata: RadarGridMetadata, pixel_size_m: float | None = None) -> CartesianField:
    np = require_numpy()
    pixel = float(pixel_size_m or metadata.rscale_m)
    radius = metadata.max_range_m
    count = int(math.ceil((2.0 * radius) / pixel))
    count = max(count, 2)
    axis = np.linspace(-radius + pixel / 2.0, radius - pixel / 2.0, count, dtype="float32")
    x_grid, y_grid = np.meshgrid(axis, axis[::-1])
    range_m = np.sqrt((x_grid * x_grid) + (y_grid * y_grid))
    azimuth = (np.degrees(np.arctan2(x_grid, y_grid)) + 360.0) % 360.0

    bin_index = np.floor((range_m - metadata.rstart_km * 1000.0) / metadata.rscale_m).astype("int64")
    ray_index = np.floor((azimuth / 360.0) * data.shape[0]).astype("int64") % data.shape[0]
    valid = (range_m <= metadata.max_range_m) & (bin_index >= 0) & (bin_index < data.shape[1])

    output = np.full(axis.shape + axis.shape, metadata.nodata, dtype="float32")
    output[valid] = data[ray_index[valid], bin_index[valid]]
    output = np.where(np.isfinite(output), output, metadata.nodata).astype("float32")
    return CartesianField(values=output, x=axis, y=axis[::-1], metadata=metadata)


def read_cartesian_field(
    source: Path,
    radar: str,
    date: str,
    selection: FieldSelection,
    pixel_size_m: float | None = None,
    filters: dict[str, Any] | None = None,
) -> CartesianField:
    data, metadata = read_polar_field(source, radar, date, selection)
    data = apply_polar_filters(data, metadata, filters)
    return polar_to_cartesian(data, metadata, pixel_size_m=pixel_size_m)


def geographic_point(metadata: RadarGridMetadata, x_m: float, y_m: float) -> tuple[float, float]:
    lat0 = math.radians(metadata.latitude)
    lon0 = math.radians(metadata.longitude)
    rho = math.hypot(x_m, y_m)
    if rho == 0:
        return metadata.longitude, metadata.latitude
    c = rho / EARTH_RADIUS_M
    az = math.atan2(x_m, y_m)
    lat = math.asin(math.cos(c) * math.sin(lat0) + (y_m * math.sin(c) * math.cos(lat0) / rho))
    lon = lon0 + math.atan2(x_m * math.sin(c), rho * math.cos(lat0) * math.cos(c) - y_m * math.sin(lat0) * math.sin(c))
    return math.degrees(lon), math.degrees(lat)


def radar_bin_location(metadata: RadarGridMetadata, row: int, column: int) -> RadarBinLocation:
    clipped_row = max(0, min(int(row), metadata.nrays - 1))
    clipped_column = max(0, min(int(column), metadata.nbins - 1))
    range_m = metadata.rstart_km * 1000.0 + (clipped_column + 0.5) * metadata.rscale_m
    azimuth_deg = ((clipped_row + 0.5) / max(metadata.nrays, 1)) * 360.0
    azimuth_rad = math.radians(azimuth_deg)
    x_m = range_m * math.sin(azimuth_rad)
    y_m = range_m * math.cos(azimuth_rad)
    longitude, latitude = geographic_point(metadata, x_m, y_m)
    return RadarBinLocation(
        row=clipped_row,
        column=clipped_column,
        range_m=range_m,
        range_km=range_m / 1000.0,
        azimuth_deg=azimuth_deg,
        x_m=x_m,
        y_m=y_m,
        longitude=longitude,
        latitude=latitude,
        elevation_deg=metadata.elevation_deg,
    )
