"""Helpers for radar site spatial metadata.

Catalogs can expose radar locations from several sources.  The functions in
this module keep that metadata in one small, validated shape before it is
passed to the API, STAC, or browser UI.
"""

from __future__ import annotations

import math
from typing import Any


def _finite_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _valid_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    coords = [_finite_float(item) for item in value]
    if any(item is None for item in coords):
        return None
    west, south, east, north = coords  # type: ignore[misc]
    if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
        return None
    if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        return None
    if west > east or south > north:
        return None
    return [float(west), float(south), float(east), float(north)]


def normalize_spatial(raw: Any, default_source: str | None = None) -> dict[str, Any]:
    """Return validated radar-site spatial metadata.

    Missing or malformed coordinates return an empty dictionary.  Exact ``0,0``
    is also treated as unavailable for this UK WSR application because it is a
    common placeholder for missing coordinates and is not a valid UK radar
    site.
    """

    if not isinstance(raw, dict):
        return {}
    latitude = _finite_float(raw.get("latitude", raw.get("lat")))
    longitude = _finite_float(raw.get("longitude", raw.get("lon")))
    if latitude is None or longitude is None:
        return {}
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return {}
    if latitude == 0.0 and longitude == 0.0:
        return {}

    spatial: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
    }
    height_m = _finite_float(raw.get("height_m", raw.get("height", raw.get("altitude"))))
    if height_m is not None:
        spatial["height_m"] = height_m
    max_range_m = _finite_float(raw.get("max_range_m"))
    if max_range_m is not None and max_range_m >= 0.0:
        spatial["max_range_m"] = max_range_m
    bbox = _valid_bbox(raw.get("bbox"))
    if bbox is not None:
        spatial["bbox"] = bbox
    source = str(raw.get("source") or default_source or "").strip()
    if source:
        spatial["source"] = source
    return spatial


def spatial_available(raw: Any) -> bool:
    """Return true when spatial metadata contains a usable radar location."""

    return bool(normalize_spatial(raw))
