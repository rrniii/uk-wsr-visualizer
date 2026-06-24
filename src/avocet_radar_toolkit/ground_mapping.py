"""Ground-mapping helpers for UK radar biological applications.

The functions in this module translate the lecture practical steps into
dependency-light Python primitives: radar-centred base grids, beam height,
terrain clearance, topographic blockage, simple VPR sampling fractions, and
radiosonde-derived effective-earth-radius propagation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dependencies import require_numpy, require_rasterio
from .geospatial import EARTH_RADIUS_M, RadarGridMetadata, geographic_point


@dataclass(frozen=True)
class RadarSampleGrid:
    """Polar sample grid with projected and geographic cell centres."""

    range_km: Any
    azimuth_deg: Any
    x_m: Any
    y_m: Any
    longitude: Any
    latitude: Any
    cell_area_ha: Any


def make_radar_sample_grid(
    metadata: RadarGridMetadata,
    max_range_km: float | None = None,
    range_step_km: float = 1.0,
    azimuth_step_deg: float = 1.0,
    min_range_km: float | None = None,
) -> RadarSampleGrid:
    """Create a radar-centred polar base grid for landscape joins.

    Rows are azimuth sectors clockwise from north and columns are range bins.
    Cell centres are returned in radar-centred metres and WGS84 lon/lat.
    """

    if range_step_km <= 0:
        raise ValueError("range_step_km must be positive")
    if azimuth_step_deg <= 0 or azimuth_step_deg > 360:
        raise ValueError("azimuth_step_deg must be in the interval (0, 360]")

    np = require_numpy()
    start_km = metadata.rstart_km if min_range_km is None else float(min_range_km)
    stop_km = metadata.max_range_m / 1000.0 if max_range_km is None else float(max_range_km)
    if stop_km <= start_km:
        raise ValueError("max_range_km must be greater than min range")

    range_edges_km = np.arange(start_km, stop_km + range_step_km, range_step_km, dtype="float64")
    if range_edges_km[-1] > stop_km:
        range_edges_km[-1] = stop_km
    range_centres_km = (range_edges_km[:-1] + range_edges_km[1:]) / 2.0
    azimuth_edges_deg = np.arange(0.0, 360.0 + azimuth_step_deg, azimuth_step_deg, dtype="float64")
    if azimuth_edges_deg[-1] > 360.0:
        azimuth_edges_deg[-1] = 360.0
    azimuth_centres_deg = (azimuth_edges_deg[:-1] + azimuth_edges_deg[1:]) / 2.0

    ranges_m = range_centres_km[None, :] * 1000.0
    azimuth_rad = np.radians(azimuth_centres_deg[:, None])
    x_m = ranges_m * np.sin(azimuth_rad)
    y_m = ranges_m * np.cos(azimuth_rad)

    lon = np.empty_like(x_m)
    lat = np.empty_like(y_m)
    for row in range(x_m.shape[0]):
        for col in range(x_m.shape[1]):
            lon[row, col], lat[row, col] = geographic_point(metadata, float(x_m[row, col]), float(y_m[row, col]))

    delta_theta = np.radians(np.diff(azimuth_edges_deg))[:, None]
    annulus_area_m2 = 0.5 * ((range_edges_km[1:] * 1000.0) ** 2 - (range_edges_km[:-1] * 1000.0) ** 2)
    cell_area_ha = (delta_theta * annulus_area_m2[None, :]) / 10_000.0

    return RadarSampleGrid(
        range_km=np.broadcast_to(range_centres_km[None, :], x_m.shape).copy(),
        azimuth_deg=np.broadcast_to(azimuth_centres_deg[:, None], x_m.shape).copy(),
        x_m=x_m,
        y_m=y_m,
        longitude=lon,
        latitude=lat,
        cell_area_ha=cell_area_ha,
    )


def beam_center_height_m(
    range_m: Any,
    elevation_deg: float,
    site_height_m: float = 0.0,
    effective_earth_radius_factor: float = 4.0 / 3.0,
) -> Any:
    """Beam-centre height above sea level using the effective-earth model."""

    np = require_numpy()
    range_array = np.asarray(range_m, dtype="float64")
    k_re = effective_earth_radius_factor * EARTH_RADIUS_M
    elevation_rad = math.radians(elevation_deg)
    return np.sqrt(range_array**2 + k_re**2 + 2.0 * range_array * k_re * math.sin(elevation_rad)) - k_re + site_height_m


def beam_radius_m(range_m: Any, beam_width_deg: float = 1.0) -> Any:
    """Approximate half-power beam radius at range."""

    np = require_numpy()
    return np.asarray(range_m, dtype="float64") * math.tan(math.radians(beam_width_deg) / 2.0)


def partial_beam_blockage_fraction(terrain_height_m: Any, beam_height_m: Any, radius_m: Any) -> Any:
    """Fraction of a circular beam cross-section below terrain height."""

    np = require_numpy()
    terrain = np.asarray(terrain_height_m, dtype="float64")
    centre = np.asarray(beam_height_m, dtype="float64")
    radius = np.maximum(np.asarray(radius_m, dtype="float64"), 1e-9)
    x = (terrain - centre) / radius
    clipped = np.clip(x, -1.0, 1.0)
    fraction = (clipped * np.sqrt(np.maximum(0.0, 1.0 - clipped**2)) + np.arcsin(clipped) + math.pi / 2.0) / math.pi
    return np.where(x <= -1.0, 0.0, np.where(x >= 1.0, 1.0, fraction))


def topographic_blockage_fraction(
    terrain_height_m: Any,
    range_m: Any,
    elevation_deg: float,
    site_height_m: float = 0.0,
    beam_width_deg: float = 1.0,
    effective_earth_radius_factor: float = 4.0 / 3.0,
    cumulative_along_radial: bool = True,
) -> Any:
    """Estimate terrain beam blockage for each azimuth/range grid cell.

    When ``cumulative_along_radial`` is true, each range bin inherits the
    highest nearer blockage fraction along the same azimuth.
    """

    np = require_numpy()
    centre = beam_center_height_m(range_m, elevation_deg, site_height_m, effective_earth_radius_factor)
    radius = beam_radius_m(range_m, beam_width_deg)
    local = partial_beam_blockage_fraction(terrain_height_m, centre, radius)
    if cumulative_along_radial:
        return np.maximum.accumulate(local, axis=1)
    return local


def beam_ground_clearance_m(
    terrain_height_m: Any,
    range_m: Any,
    elevation_deg: float,
    site_height_m: float = 0.0,
    effective_earth_radius_factor: float = 4.0 / 3.0,
) -> Any:
    """Beam-centre clearance above terrain."""

    return beam_center_height_m(range_m, elevation_deg, site_height_m, effective_earth_radius_factor) - terrain_height_m


def vertical_profile_detection_fraction(
    range_m: Any,
    elevation_deg: float,
    terrain_height_m: Any,
    altitude_m_agl: Any,
    profile_weight: Any,
    site_height_m: float = 0.0,
    beam_width_deg: float = 1.0,
    effective_earth_radius_factor: float = 4.0 / 3.0,
) -> Any:
    """Fraction of a supplied vertical profile sampled by the radar beam."""

    np = require_numpy()
    altitude = np.asarray(altitude_m_agl, dtype="float64")
    weights = np.asarray(profile_weight, dtype="float64")
    if altitude.ndim != 1 or weights.ndim != 1 or altitude.size != weights.size:
        raise ValueError("altitude_m_agl and profile_weight must be same-length one-dimensional arrays")
    total = float(np.nansum(weights))
    if total <= 0:
        raise ValueError("profile_weight must sum to a positive value")

    centre_asl = beam_center_height_m(range_m, elevation_deg, site_height_m, effective_earth_radius_factor)
    radius = beam_radius_m(range_m, beam_width_deg)
    lower_agl = centre_asl - radius - terrain_height_m
    upper_agl = centre_asl + radius - terrain_height_m
    out = np.zeros(np.asarray(range_m).shape, dtype="float64")
    for altitude_value, weight in zip(altitude, weights):
        out += np.where((altitude_value >= lower_agl) & (altitude_value <= upper_agl), weight, 0.0)
    return out / total


def sample_dem_at_grid(dem_path: Path, grid: RadarSampleGrid) -> Any:
    """Sample a raster DEM at grid-cell centres.

    The DEM can be in WGS84 or any CRS understood by rasterio.
    """

    np = require_numpy()
    rasterio, _from_origin = require_rasterio()
    from rasterio.warp import transform  # type: ignore

    with rasterio.open(dem_path) as dataset:
        lon = np.asarray(grid.longitude, dtype="float64").reshape(-1)
        lat = np.asarray(grid.latitude, dtype="float64").reshape(-1)
        if dataset.crs and str(dataset.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
            xs, ys = transform("EPSG:4326", dataset.crs, lon.tolist(), lat.tolist())
        else:
            xs, ys = lon.tolist(), lat.tolist()
        values = np.fromiter((sample[0] for sample in dataset.sample(zip(xs, ys))), dtype="float64", count=lon.size)
        nodata = dataset.nodata
    if nodata is not None:
        values = np.where(values == nodata, np.nan, values)
    return values.reshape(np.asarray(grid.longitude).shape)


def water_vapour_pressure_hpa(dewpoint_c: Any) -> Any:
    """Vapour pressure from dewpoint using the Bolton approximation."""

    np = require_numpy()
    dewpoint = np.asarray(dewpoint_c, dtype="float64")
    return 6.112 * np.exp((17.67 * dewpoint) / (dewpoint + 243.5))


def refractivity_n_units(pressure_hpa: Any, temperature_c: Any, dewpoint_c: Any) -> Any:
    """Atmospheric refractivity N from pressure, temperature, and dewpoint."""

    np = require_numpy()
    pressure = np.asarray(pressure_hpa, dtype="float64")
    temperature_k = np.asarray(temperature_c, dtype="float64") + 273.15
    vapour_pressure = water_vapour_pressure_hpa(dewpoint_c)
    return 77.6 * (pressure / temperature_k) + 3.73e5 * (vapour_pressure / (temperature_k**2))


def refractivity_gradient_n_per_km(
    height_m: Any,
    pressure_hpa: Any,
    temperature_c: Any,
    dewpoint_c: Any,
    fit_top_m: float = 1000.0,
) -> float:
    """Fit a low-level refractivity gradient in N-units per kilometre."""

    np = require_numpy()
    height = np.asarray(height_m, dtype="float64")
    n_units = refractivity_n_units(pressure_hpa, temperature_c, dewpoint_c)
    keep = np.isfinite(height) & np.isfinite(n_units) & (height <= fit_top_m)
    if int(np.count_nonzero(keep)) < 2:
        raise ValueError("at least two finite sounding levels below fit_top_m are required")
    slope, _intercept = np.polyfit(height[keep] / 1000.0, n_units[keep], 1)
    return float(slope)


def effective_earth_radius_factor_from_gradient(gradient_n_per_km: float) -> float:
    """Convert refractivity gradient to effective earth radius factor k."""

    denominator = 1.0 + (EARTH_RADIUS_M / 1000.0) * gradient_n_per_km * 1e-6
    if abs(denominator) < 1e-9:
        return math.inf
    return 1.0 / denominator


def classify_refractivity_gradient(gradient_n_per_km: float) -> str:
    """Classify beam propagation from the low-level refractivity gradient."""

    if gradient_n_per_km <= -157.0:
        return "trapping_or_ducting"
    if gradient_n_per_km <= -79.0:
        return "super_refractive"
    if gradient_n_per_km <= 0.0:
        return "standard_or_normal"
    return "sub_refractive"
