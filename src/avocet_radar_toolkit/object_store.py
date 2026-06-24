"""JASMIN Object Store key and URL helpers."""

from __future__ import annotations

import re
from pathlib import Path

from .radars import require_radar

DEFAULT_OBJECT_PREFIX = "uk-radar"


def normalize_object_prefix(prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    clean = prefix.strip("/")
    if not clean:
        raise ValueError("object-store prefix must not be empty")
    if re.search(r"[\s\\]", clean):
        raise ValueError(f"invalid object-store prefix: {prefix!r}")
    return clean


def _key(prefix: str, *parts: str) -> str:
    root = normalize_object_prefix(prefix)
    clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
    return "/".join([root, *clean_parts])


def aggregate_object_key(radar: str, date: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    site = require_radar(radar)
    year = date[:4]
    filename = f"{date}_polar_pl_radar{site.radar_num}_aggregate.h5"
    return _key(prefix, "aggregate-h5", f"radar={radar}", f"year={year}", filename)


def raw_volume_object_key(radar: str, date: str, pulse: str, filename: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    require_radar(radar)
    year = date[:4]
    return _key(prefix, "raw-volume", f"radar={radar}", f"year={year}", f"date={date}", f"pulse={pulse}", filename)


def preview_object_prefix(radar: str, date: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    require_radar(radar)
    return _key(prefix, "previews", f"radar={radar}", f"date={date}")


def preview_object_key(
    radar: str,
    date: str,
    pulse: str,
    time: str,
    quantity: str,
    filename: str,
    prefix: str = DEFAULT_OBJECT_PREFIX,
) -> str:
    return _key(preview_object_prefix(radar, date, prefix), f"pulse={pulse}", f"time={time}", f"quantity={quantity}", filename)


def stac_object_key(collection: str, item_id: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "catalog", "stac", collection, f"{item_id}.json")


def stac_collection_object_key(collection: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "catalog", "stac", collection, "collection.json")


def stac_catalog_object_key(prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "catalog", "stac", "catalog.json")


def catalog_inventory_object_key(filename: str = "catalog.json", prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "catalog", "inventory", filename)


def manifest_object_key(run_id: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "manifests", "sync-runs", f"{run_id}.json")


def latest_manifest_object_key(prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "manifests", "latest.json")


def checksum_object_key(year: str, radar: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    require_radar(radar)
    return _key(prefix, "checksums", "sha256", year, f"{radar}.json")


def public_status_object_key(prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "status.json")


def public_landing_object_key(prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "index.html")


def public_dataset_metadata_object_key(prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "dataset.json")


def validation_report_object_key(relative_path: Path, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "validation", "wct", *relative_path.parts)


def tile_object_prefix(radar: str, date: str, pulse: str, quantity: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    require_radar(radar)
    return _key(prefix, "tiles", f"radar={radar}", f"date={date}", f"pulse={pulse}", f"quantity={quantity}")


def export_object_prefix(job_id: str, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    return _key(prefix, "exports", f"job={job_id}")


def export_product_object_key(relative_path: Path, prefix: str = DEFAULT_OBJECT_PREFIX) -> str:
    parts = relative_path.parts
    if len(parts) > 1 and re.fullmatch(r"[0-9a-f]{16,64}", parts[0]):
        return _key(export_object_prefix(parts[0], prefix), *parts[1:])
    return _key(prefix, "exports", *parts)


def join_object_url(base_url: str, key: str) -> str:
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/{key.lstrip('/')}"


def relative_aggregate_path(aggregate_base: Path, radar: str, date: str) -> Path:
    site = require_radar(radar)
    return Path(radar) / date[:4] / f"{date}_polar_pl_radar{site.radar_num}_aggregate.h5"


def relative_raw_volume_path(radar: str, date: str, pulse: str, filename: str) -> Path:
    require_radar(radar)
    return Path("raw-volume") / radar / date[:4] / date / pulse / filename
