"""Geospatial field extraction and radar-centred grid helpers."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .dependencies import require_h5py, require_numpy
from .export_types import FieldSelection
from .qc import QCMaskFlag, QCMaskResult, build_qc_mask, qc_config_from_filters
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
    height_m: float | None
    azimuth_deg: float
    x_m: float
    y_m: float
    longitude: float
    latitude: float
    elevation_deg: float | None


@dataclass(frozen=True)
class NoiseFloorResult:
    """Metadata describing an optional range-dependent display noise filter."""

    enabled: bool
    method: str = "none"
    operation: str = "none"
    margin_db: float | None = None
    percentile: float | None = None
    window_bins: int | None = None
    masked_count: int = 0
    texture_masked_count: int = 0
    texture_threshold_db: float | None = None
    texture_near_margin_db: float | None = None
    texture_max_db: float | None = None
    finite_before: int = 0
    finite_after: int = 0
    floor_profile: list[float | None] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolarFilterResult:
    """Filtered polar field plus provenance for filters that alter displayed values."""

    values: Any
    noise_floor: NoiseFloorResult
    qc: QCMaskResult | None = None


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
            "uk_wsr:odim_scaling_applied": True,
            "uk_wsr:nominal_height_m": nominal_height_m,
            "uk_wsr:cappi_target_height_m": selection.cappi_height_m,
        },
    )
    return data, metadata


def _filter_float(filters: dict[str, Any], key: str) -> float | None:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def _filter_bool(filters: dict[str, Any], key: str) -> bool:
    value = filters.get(key)
    if isinstance(value, bool):
        return value
    if value in ("", None, "NONE"):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _filter_text(filters: dict[str, Any], key: str, default: str) -> str:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return default
    return str(value).strip().lower()


def _rolling_nanmedian(values: Any, window_bins: int) -> Any:
    np = require_numpy()
    profile = np.asarray(values, dtype="float32")
    if profile.size == 0:
        return profile
    window = max(1, int(window_bins))
    if window % 2 == 0:
        window += 1
    if window == 1:
        return profile
    half = window // 2
    smoothed = np.full(profile.shape, np.nan, dtype="float32")
    for index in range(profile.size):
        left = max(0, index - half)
        right = min(profile.size, index + half + 1)
        segment = profile[left:right]
        if np.isfinite(segment).any():
            smoothed[index] = float(np.nanmedian(segment))
    return smoothed


def _fill_nan_profile(profile: Any) -> Any:
    np = require_numpy()
    values = np.asarray(profile, dtype="float32")
    if values.size == 0 or np.isfinite(values).all():
        return values
    valid = np.isfinite(values)
    if not valid.any():
        return np.zeros(values.shape, dtype="float32")
    indices = np.arange(values.size)
    filled = np.interp(indices, indices[valid], values[valid]).astype("float32")
    return filled


def _estimated_noise_floor_profile(data: Any, percentile: float, window_bins: int) -> Any:
    np = require_numpy()
    values = np.asarray(data, dtype="float32")
    profile = np.full(values.shape[1], np.nan, dtype="float32")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return profile
    global_min = float(np.nanmin(finite))
    for column in range(values.shape[1]):
        column_values = values[:, column]
        column_values = column_values[np.isfinite(column_values)]
        if column_values.size == 0:
            continue
        # Many ODIM reflectivity fields use a constant minimum after scaling for undetect.
        # Excluding that repeated floor gives a more useful low-signal profile for plotting.
        above_floor = column_values[column_values > global_min + 1.0e-3]
        if above_floor.size >= max(3, column_values.size // 20):
            column_values = above_floor
        profile[column] = float(np.nanpercentile(column_values, percentile))
    return _fill_nan_profile(_rolling_nanmedian(profile, window_bins))


def _local_texture_and_support(data: Any, support_db: float) -> tuple[Any, Any]:
    """Return DBZH local texture and count of nearby similar gates.

    The public UK PVOL files do not include NCP. This derived diagnostic gives
    the display filter a conservative way to suppress isolated speckle using the
    field being plotted, without requiring a calibration-specific quantity.
    """

    np = require_numpy()
    values = np.asarray(data, dtype="float32")
    rows, columns = values.shape
    texture = np.full(values.shape, np.nan, dtype="float32")
    similar = np.zeros(values.shape, dtype="int16")
    for row in range(rows):
        for column in range(columns):
            value = values[row, column]
            if not np.isfinite(value):
                continue
            differences: list[float] = []
            for neighbour_row, neighbour_column in (
                ((row - 1) % rows, column),
                ((row + 1) % rows, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if neighbour_column < 0 or neighbour_column >= columns:
                    continue
                neighbour = values[neighbour_row, neighbour_column]
                if not np.isfinite(neighbour):
                    continue
                difference = abs(float(value) - float(neighbour))
                differences.append(difference)
                if difference <= support_db:
                    similar[row, column] += 1
            if len(differences) >= 2:
                texture[row, column] = float(np.nanpercentile(np.asarray(differences, dtype="float32"), 75))
    return texture, similar


def _json_profile(values: Any) -> list[float | None]:
    np = require_numpy()
    out: list[float | None] = []
    for value in np.asarray(values, dtype="float32").tolist():
        out.append(float(value) if np.isfinite(value) else None)
    return out


def _noise_floor_from_qc(result: QCMaskResult) -> NoiseFloorResult:
    np = require_numpy()
    config = result.config
    mask = np.asarray(result.mask, dtype="uint16")
    domain_bits = int(QCMaskFlag.NO_DATA | QCMaskFlag.USER_DOMAIN)
    noise_bits = int(QCMaskFlag.NOISE_FLOOR | QCMaskFlag.TEXTURE_SPECKLE)
    analysis_domain = (mask & domain_bits) == 0
    noise_mask = analysis_domain & ((mask & noise_bits) != 0)
    texture_mask = analysis_domain & ((mask & int(QCMaskFlag.TEXTURE_SPECKLE)) != 0)
    finite_before = int(analysis_domain.sum())
    masked_count = int(noise_mask.sum()) if config.noise_floor_enabled else 0
    finite_after = finite_before - masked_count
    return NoiseFloorResult(
        enabled=config.noise_floor_enabled,
        method=config.noise_floor_method if config.noise_floor_enabled else "none",
        operation=config.operation if config.noise_floor_enabled else "none",
        margin_db=config.noise_floor_margin_db if config.noise_floor_enabled else None,
        percentile=config.noise_floor_percentile if config.noise_floor_enabled else None,
        window_bins=config.noise_floor_window_bins if config.noise_floor_enabled else None,
        masked_count=masked_count,
        texture_masked_count=int(texture_mask.sum()) if config.noise_floor_enabled else 0,
        texture_threshold_db=config.texture_threshold_db if config.noise_floor_enabled and config.texture_enabled else None,
        texture_near_margin_db=config.texture_near_margin_db if config.noise_floor_enabled and config.texture_enabled else None,
        texture_max_db=config.texture_max_dbz if config.noise_floor_enabled and config.texture_enabled else None,
        finite_before=finite_before,
        finite_after=finite_after,
        floor_profile=list(result.floor_profile) if config.noise_floor_enabled else [],
    )


def apply_noise_floor_filter(data: Any, filters: dict[str, Any] | None = None) -> PolarFilterResult:
    qc_result = build_qc_mask(data, config=qc_config_from_filters(filters))
    return PolarFilterResult(values=qc_result.values, noise_floor=_noise_floor_from_qc(qc_result), qc=qc_result)


def apply_polar_filters(
    data: Any,
    metadata: RadarGridMetadata,
    filters: dict[str, Any] | None = None,
    *,
    return_metadata: bool = False,
) -> Any:
    filters = filters or {}
    if not filters:
        noise_floor = NoiseFloorResult(enabled=False)
        return PolarFilterResult(values=data, noise_floor=noise_floor) if return_metadata else data
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

    qc_result = build_qc_mask(
        output,
        metadata,
        config=qc_config_from_filters(filters),
        domain_mask=~keep,
    )
    filter_result = PolarFilterResult(
        values=qc_result.values,
        noise_floor=_noise_floor_from_qc(qc_result),
        qc=qc_result,
    )
    return filter_result if return_metadata else filter_result.values


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
    height_m = None
    if metadata.elevation_deg is not None:
        k_re = (4.0 / 3.0) * EARTH_RADIUS_M
        site_height_m = metadata.height_m or 0.0
        elevation_rad = math.radians(metadata.elevation_deg)
        height_m = math.sqrt(range_m**2 + k_re**2 + 2.0 * range_m * k_re * math.sin(elevation_rad)) - k_re + site_height_m
    return RadarBinLocation(
        row=clipped_row,
        column=clipped_column,
        range_m=range_m,
        range_km=range_m / 1000.0,
        height_m=height_m,
        azimuth_deg=azimuth_deg,
        x_m=x_m,
        y_m=y_m,
        longitude=longitude,
        latitude=latitude,
        elevation_deg=metadata.elevation_deg,
    )
