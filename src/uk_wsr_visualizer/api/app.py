"""FastAPI app for the UK WSR Visualizer."""

from __future__ import annotations

import json
import time as time_module
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover - exercised when dependencies are missing.
    raise RuntimeError("FastAPI dependencies are missing. Install with: pip install -e .") from exc

from ..animation import AnimationRequest, run_animation
from ..catalog import (
    CatalogItem,
    QuantityRecord,
    RawVolumeRecord,
    catalog_public_base_from_root_url,
    catalog_summary,
    catalog_url_is_pvol_root,
    filter_catalog,
    join_catalog_url,
    load_catalog_source,
    load_catalog_url,
    pvol_catalog_summary,
    pvol_coverage_keys,
    pvol_item_from_day_catalog,
    pvol_items_from_coverage,
    pvol_radar_records,
    scan_raw_volume,
)
from ..citations import citation_payload
from ..config import Settings
from ..dependencies import require_numpy
from ..export import ExportRequest, contour_feature_collection, export_download_path, read_job, run_export
from ..freshness import build_freshness_report
from ..geospatial import apply_polar_filters, field_selection_from_request, read_cartesian_field, read_polar_field_with_companions
from ..http_cache import load_json_cached
from ..math_ops import MathOperand, MathRequest, run_math
from ..object_store import join_object_url
from ..object_store_manifest import load_plan, public_dataset_metadata_payload, public_landing_html
from ..preview import PreviewRequest, _scale_to_uint8, generate_preview, identify_value, preview_metadata
from ..radars import radar_records
from ..recent import clear_recent_selections, load_recent_selections, record_recent_selection
from ..remote_cache import (
    cached_raw_volume_path,
    clear_raw_cache,
    ensure_raw_volume_cached,
    hydrate_item_from_raw_aggregate,
    prune_raw_cache,
    raw_cache_status,
)
from ..session import import_project, list_sessions, load_session, project_from_dict, project_to_dict, save_session, session_to_project
from ..stac import AGGREGATE_COLLECTION_ID, collection_to_stac, item_to_stac, root_catalog_to_stac
from ..tiles import TileRequest, generate_tile_pyramid, tile_manifest

PLOT_METADATA_DOWNLOAD_LIMIT_BYTES = 512 * 1024 * 1024


def _elapsed_ms(start: float) -> float:
    return round((time_module.perf_counter() - start) * 1000.0, 2)


@contextmanager
def _timed_step(steps: list[dict[str, object]], name: str):
    start = time_module.perf_counter()
    try:
        yield
    finally:
        steps.append({"name": name, "elapsed_ms": _elapsed_ms(start)})


def _item_payload(item: CatalogItem) -> dict[str, object]:
    return {
        **asdict(item),
        "quantity_records": [asdict(record) for record in item.quantity_records],
    }


def _raw_volume_item_has_files(item: CatalogItem) -> bool:
    return item.source_type == "raw_volume_day" and bool(item.raw_volumes)


def _quantity_display_config(quantity: str, requested_palette: str) -> dict[str, object]:
    """Return default palette and scale choices for common radar variables."""

    normalized = quantity.strip()
    upper = normalized.upper()
    lower = normalized.lower()
    palette = requested_palette if requested_palette not in {"", "auto", "standard"} else ""
    limits: tuple[float | None, float | None] = (None, None)
    mask_below_min = False

    if upper in {"DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"} or "reflectivity" in lower:
        palette = palette or "homeyer"
        limits = (-30.0, 75.0)
        mask_below_min = True
    elif upper in {"VRAD", "VRADH", "VRADV", "VEL", "VELH", "VELV", "V"} or "velocity" in lower:
        palette = palette or "BuDRd18"
        limits = (-30.0, 30.0)
    elif upper in {"WRAD", "WRADH", "WRADV", "WIDTH", "SW", "SWRAD"} or "spectrum_width" in lower:
        palette = palette or "NWS_SPW"
        limits = (0.0, 10.0)
    elif upper in {"ZDR", "ZDRH", "ZDRV"} or "differential_reflectivity" in lower:
        palette = palette or "RefDiff"
        limits = (-1.0, 8.0)
    elif upper in {"RHOHV", "RHO", "CC", "SQIH"} or "cross_correlation" in lower:
        palette = palette or "RefDiff"
        limits = (0.5, 1.05)
    elif upper in {"PHIDP", "UPHIDP", "PHI"} or "differential_phase" in lower:
        palette = palette or "Wild25"
        limits = (-180.0, 180.0)
    elif upper in {"KDP", "KDPH", "KDPV"} or "specific_differential_phase" in lower:
        palette = palette or "Theodore16"
        limits = (-2.0, 5.0)
    elif upper in {"RATE", "RRATE", "RATE_H", "RATE_Z", "R"} or "rain_rate" in lower:
        palette = palette or "RRate11"
        limits = (0.0, 50.0)
    elif upper in {"SNR", "SNRH", "SNRV"} or "signal_to_noise" in lower:
        palette = palette or "Carbone17"
        limits = (-20.0, 30.0)
    else:
        palette = palette or "gray"
    return {"palette": palette, "scale_min": limits[0], "scale_max": limits[1], "mask_below_min": mask_below_min}


def _scale_to_uint8_with_limits(data, scale_min: float | None, scale_max: float | None):
    """Scale a numeric array to image bytes using optional display limits."""

    if scale_min is None or scale_max is None:
        return _scale_to_uint8(data)
    np = require_numpy()
    array = np.asarray(data, dtype=float)
    array = np.where(np.isfinite(array), array, np.nan)
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return np.zeros(array.shape, dtype=np.uint8), {
            "valid_min": None,
            "valid_max": None,
            "scale_min": float(scale_min),
            "scale_max": float(scale_max),
        }
    if scale_max <= scale_min:
        scale_max = scale_min + 1.0
    scaled = (array - scale_min) / (scale_max - scale_min)
    scaled = np.clip(scaled, 0, 1)
    scaled = np.where(np.isfinite(scaled), scaled, 0)
    return (scaled * 255).astype(np.uint8), {
        "valid_min": float(np.nanmin(valid)),
        "valid_max": float(np.nanmax(valid)),
        "scale_min": float(scale_min),
        "scale_max": float(scale_max),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local API and static viewer application."""

    settings = settings or Settings.from_env()
    app = FastAPI(title="UK WSR Visualizer", version="0.2.1")
    static_dir = Path(__file__).resolve().parents[1] / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    hydrated_items: dict[str, CatalogItem] = {}
    raw_volume_catalog_exists_cache: dict[tuple[str, str], bool] = {}
    pvol_root_cache: dict[str, object] | None = None
    pvol_coverage_cache: dict[str, dict[str, object]] = {}
    pvol_day_cache: dict[str, dict[str, object]] = {}
    pvol_field_index_cache: dict[str, dict[str, object] | None] = {}
    http_json_cache_dir = settings.data_dir / "http-json-cache"
    raw_prefetch_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="uk-wsr-raw-prefetch")
    raw_prefetch_jobs: dict[str, object] = {}
    ppi_response_cache: dict[str, dict[str, object]] = {}
    ppi_response_cache_order: list[str] = []
    max_ppi_response_cache_entries = 32
    performance_events: deque[dict[str, object]] = deque(maxlen=400)

    def record_performance_event(event: dict[str, object]) -> None:
        payload = {
            "created_at": time_module.strftime("%Y-%m-%dT%H:%M:%SZ", time_module.gmtime()),
            **event,
        }
        performance_events.append(payload)

    @app.middleware("http")
    async def performance_middleware(request, call_next):
        start = time_module.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = _elapsed_ms(start)
            path = str(request.url.path)
            try:
                response.headers["X-UK-WSR-Elapsed-Ms"] = str(elapsed)
            except Exception:
                pass
            if path.startswith("/api/"):
                record_performance_event(
                    {
                        "kind": "request",
                        "method": request.method,
                        "path": path,
                        "query": str(request.url.query),
                        "status_code": status_code,
                        "elapsed_ms": elapsed,
                    }
                )

    def catalog() -> list[CatalogItem]:
        try:
            return load_catalog_source(settings.catalog_path, settings.remote_catalog_url)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"catalog unavailable: {exc}") from exc

    def using_remote_catalog() -> bool:
        return bool(settings.remote_catalog_url) and not settings.catalog_path.exists()

    def using_pvol_catalog() -> bool:
        return using_remote_catalog() and catalog_url_is_pvol_root(settings.remote_catalog_url)

    def catalog_source_label() -> str:
        return settings.remote_catalog_url if using_remote_catalog() else str(settings.catalog_path)

    def load_json_url(url: str, timeout_s: float = 30.0) -> dict[str, object]:
        return load_json_cached(url, http_json_cache_dir, timeout_s=timeout_s)

    def pvol_public_base() -> str:
        return settings.object_store_external_base or catalog_public_base_from_root_url(settings.remote_catalog_url)

    def pvol_root() -> dict[str, object]:
        nonlocal pvol_root_cache
        if pvol_root_cache is None:
            pvol_root_cache = load_json_url(settings.remote_catalog_url)
        return pvol_root_cache

    def pvol_coverage(key: str) -> dict[str, object]:
        if key not in pvol_coverage_cache:
            pvol_coverage_cache[key] = load_json_url(join_catalog_url(pvol_public_base(), key), timeout_s=30.0)
        return pvol_coverage_cache[key]

    def pvol_day_catalog(key: str) -> dict[str, object]:
        if key not in pvol_day_cache:
            pvol_day_cache[key] = load_json_url(join_catalog_url(pvol_public_base(), key), timeout_s=30.0)
        return pvol_day_cache[key]

    def pvol_field_index(key: str, day: dict[str, object]) -> dict[str, object] | None:
        candidates: list[str] = []
        explicit_url = str(day.get("field_index_url") or "")
        explicit_key = str(day.get("field_index_key") or day.get("field-index_key") or "")
        if explicit_url:
            candidates.append(explicit_url)
        if explicit_key:
            candidates.append(join_catalog_url(pvol_public_base(), explicit_key))
        if key.endswith("/catalog.json"):
            base = key[: -len("catalog.json")]
            candidates.extend(
                [
                    join_catalog_url(pvol_public_base(), f"{base}field-index.json"),
                    join_catalog_url(pvol_public_base(), f"{base}field_index.json"),
                ]
            )
        for url in dict.fromkeys(candidates):
            if url not in pvol_field_index_cache:
                try:
                    pvol_field_index_cache[url] = load_json_url(url, timeout_s=12.0)
                except Exception:
                    pvol_field_index_cache[url] = None
            cached = pvol_field_index_cache[url]
            if isinstance(cached, dict) and isinstance(cached.get("files"), list):
                return cached
        return None

    def pvol_latest_items_from_root() -> list[CatalogItem]:
        root = pvol_root()
        items: list[CatalogItem] = []
        for radar_entry in root.get("radars", []):
            if not isinstance(radar_entry, dict):
                continue
            date = str(radar_entry.get("last_date") or "")
            radar = str(radar_entry.get("radar") or "")
            if not radar or not date:
                continue
            day = {
                "date": date,
                "catalog_key": f"ukmo-nimrod/catalog/pvol/{radar}/{date[:4]}/{date[4:6]}/{date[6:8]}/catalog.json",
                "pvol_prefix": f"ukmo-nimrod/pvol/{radar}/{date[:4]}/{date[4:6]}/{date[6:8]}",
                "file_count": 0,
                "size_bytes": 0,
                "pulse_counts": {},
            }
            items.append(pvol_items_from_coverage(root, radar_entry, {"days": [day]}, pvol_public_base())[0])
        return sorted(items, key=lambda item: (item.radar, item.date))

    def pvol_search_items(
        radar: str | None = None,
        start: str | None = None,
        end: str | None = None,
        pulse: str | None = None,
        quantity: str | None = None,
    ) -> list[CatalogItem]:
        root = pvol_root()
        if not radar and not start and not end:
            items = pvol_latest_items_from_root()
        else:
            items = []
            for radar_entry, key in pvol_coverage_keys(root, radar=radar, start=start, end=end):
                items.extend(pvol_items_from_coverage(root, radar_entry, pvol_coverage(key), pvol_public_base()))
        items = filter_catalog(items, radar=radar, start=start, end=end, pulse=pulse)
        if quantity:
            # PVOL coverage records deliberately avoid per-file quantity scans; quantity filtering applies
            # after selected days are hydrated from their day catalog and one representative scan.
            items = [item for item in items if not item.quantities or quantity in item.quantities]
        return items

    def find_item(radar: str, date: str) -> CatalogItem:
        item_key = f"{radar}:{date}"
        if item_key in hydrated_items:
            return hydrated_items[item_key]
        if using_pvol_catalog():
            for item in pvol_search_items(radar=radar, start=date, end=date):
                if item.radar == radar and item.date == date:
                    return item
            raise HTTPException(status_code=404, detail="catalog item not found")
        for item in catalog():
            if item.radar == radar and item.date == date:
                return item
        raise HTTPException(status_code=404, detail="catalog item not found")

    def raw_volume_day_catalog_item(item: CatalogItem) -> CatalogItem | None:
        if using_pvol_catalog():
            key = str(item.root_attrs.get("catalog_key") or item.root_attrs.get("uk_wsr:pvol_day_catalog_key") or "")
            if not key:
                return None
            try:
                day = pvol_day_catalog(key)
                return pvol_item_from_day_catalog(pvol_root(), item, day, pvol_public_base(), pvol_field_index(key, day))
            except Exception:
                return None
        if not settings.object_store_external_base:
            return None
        url = raw_volume_day_catalog_url(item.radar, item.date)
        try:
            items = load_catalog_url(url, timeout_s=12.0)
        except Exception:
            return None
        for candidate in items:
            if candidate.radar == item.radar and candidate.date == item.date and candidate.source_type == "raw_volume_day":
                return candidate
        return None

    def raw_volume_day_catalog_url(radar: str, date: str) -> str:
        key = f"uk-radar/catalog/inventory/raw-volume/{radar}/{date[:4]}/{date}/catalog.json"
        return join_object_url(settings.object_store_external_base, key)

    def raw_volume_day_catalog_exists(radar: str, date: str) -> bool:
        if not settings.object_store_external_base:
            return False
        cache_key = (radar, date)
        if cache_key in raw_volume_catalog_exists_cache:
            return raw_volume_catalog_exists_cache[cache_key]
        try:
            request = Request(raw_volume_day_catalog_url(radar, date), method="HEAD")
            with urlopen(request, timeout=0.75) as response:
                exists = 200 <= response.status < 300
        except Exception:
            exists = False
        raw_volume_catalog_exists_cache[cache_key] = exists
        return exists

    def item_has_time_metadata(item: CatalogItem) -> bool:
        if item.source_type == "raw_volume_day":
            return _raw_volume_item_has_files(item)
        if item.quantity_records:
            return True
        if item.times:
            return True
        return any(times for times in item.times_by_pulse.values())

    def first_plot_ready_date(items: list[CatalogItem]) -> str | None:
        for item in sorted(items, key=lambda candidate: candidate.date):
            if _raw_volume_item_has_files(item) or (item.source_type != "raw_volume_day" and item_has_time_metadata(item)) or raw_volume_day_catalog_exists(item.radar, item.date):
                return item.date
        return None

    def latest_plot_ready_date(items: list[CatalogItem]) -> str | None:
        for item in sorted(items, key=lambda candidate: candidate.date, reverse=True):
            if _raw_volume_item_has_files(item) or (item.source_type != "raw_volume_day" and item_has_time_metadata(item)) or raw_volume_day_catalog_exists(item.radar, item.date):
                return item.date
        return None

    def populate_raw_volume_metadata(item: CatalogItem) -> CatalogItem:
        """Inspect one cached scan per pulse so the UI can list fields/elevations without parsing every file."""

        if item.source_type != "raw_volume_day" or not item.raw_volumes or item.quantity_records:
            return item
        records: list[QuantityRecord] = []
        root_attrs = dict(item.root_attrs)
        quantities_by_pulse: dict[str, list[str]] = {}
        by_pulse: dict[str, list[object]] = {}
        for volume in item.raw_volumes:
            by_pulse.setdefault(volume.pulse, []).append(volume)
        for pulse, volumes in by_pulse.items():
            first = min(volumes, key=lambda volume: volume.time)
            try:
                source = ensure_raw_volume_cached(
                    item,
                    first,
                    settings.remote_aggregate_cache_dir,
                    settings.object_store_external_base,
                    max_age_seconds=settings.remote_cache_ttl_seconds,
                    max_bytes=settings.remote_cache_max_bytes,
                )
                _radar, _radar_num, _date, _scanned_volume, template_records, scanned_attrs = scan_raw_volume(
                    source,
                    settings.remote_aggregate_cache_dir,
                    settings.object_store_external_base,
                )
            except Exception:
                continue
            quantities = sorted({record.quantity for record in template_records})
            quantities_by_pulse[pulse] = quantities
            for volume in volumes:
                volume.quantities = quantities
                for record in template_records:
                    records.append(
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
            if scanned_attrs.get("uk_wsr:spatial") and "uk_wsr:spatial" not in root_attrs:
                root_attrs["uk_wsr:spatial"] = scanned_attrs["uk_wsr:spatial"]
        if not records:
            return item
        return CatalogItem(
            radar=item.radar,
            radar_num=item.radar_num,
            date=item.date,
            path=item.path,
            file_size=item.file_size,
            modified_time=item.modified_time,
            pulses=sorted({record.pulse for record in records}),
            times=sorted({record.time for record in records}),
            quantities=sorted({record.quantity for record in records}),
            quantity_records=records,
            object_key=item.object_key,
            object_url=item.object_url,
            source_type=item.source_type,
            raw_volumes=item.raw_volumes,
            validation_status=item.validation_status,
            root_attrs=root_attrs,
            quantities_by_pulse=quantities_by_pulse,
            times_by_pulse=item.times_by_pulse,
        )

    def hydrate_item(item: CatalogItem) -> CatalogItem:
        """Resolve a catalog day to a plot-ready raw-volume source when possible."""

        item_key = f"{item.radar}:{item.date}"
        if item_key in hydrated_items and _raw_volume_item_has_files(hydrated_items[item_key]):
            return hydrated_items[item_key]
        if _raw_volume_item_has_files(item):
            hydrated = populate_raw_volume_metadata(item)
            hydrated_items[item_key] = hydrated
            return hydrated
        raw_volume_item = raw_volume_day_catalog_item(item)
        if raw_volume_item is not None and _raw_volume_item_has_files(raw_volume_item):
            hydrated = populate_raw_volume_metadata(raw_volume_item)
            hydrated_items[item_key] = hydrated
            return hydrated
        if item.source_type == "raw_volume_day":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{item.radar} {item.date} is listed in the raw-volume catalog, but the detailed per-day "
                    "catalog with object URLs has not been published or could not be loaded. Press Refresh later "
                    "or choose a day marked plot-ready after the object-store backfill publishes its detailed catalog."
                ),
            )
        if item.file_size > PLOT_METADATA_DOWNLOAD_LIMIT_BYTES:
            size_gb = item.file_size / (1024 ** 3)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{item.radar} {item.date} is in the day catalog, but its plot-ready raw-volume index "
                    f"is not published yet. The fallback aggregate is {size_gb:.1f} GB, so the app will not "
                    "download it just to discover times. Choose an earlier plot-ready day or press Refresh later."
                ),
            )
        try:
            hydrated = hydrate_item_from_raw_aggregate(
                item,
                settings.remote_aggregate_cache_dir,
                settings.object_store_external_base,
                max_age_seconds=settings.remote_cache_ttl_seconds,
                max_bytes=settings.remote_cache_max_bytes,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"raw aggregate unavailable: {type(exc).__name__}: {exc}") from exc
        hydrated_items[item_key] = hydrated
        return hydrated

    def prune_cache() -> dict[str, object]:
        removed = prune_raw_cache(
            settings.remote_aggregate_cache_dir,
            max_age_seconds=settings.remote_cache_ttl_seconds,
            max_bytes=settings.remote_cache_max_bytes,
        )
        for key, hydrated in list(hydrated_items.items()):
            if not Path(hydrated.path).exists():
                hydrated_items.pop(key, None)
        return removed

    def raw_volume_cached(item: CatalogItem, volume: RawVolumeRecord | None) -> bool:
        if volume is None:
            return False
        try:
            path = cached_raw_volume_path(item, volume, settings.remote_aggregate_cache_dir)
            return path.exists() and (volume.file_size <= 0 or path.stat().st_size == volume.file_size)
        except Exception:
            return False

    def queue_raw_volume_prefetch(item: CatalogItem, pulse: str, time: str) -> dict[str, object]:
        volume = item.raw_volume_for(pulse, time)
        if volume is None:
            raise HTTPException(status_code=404, detail=f"no raw-volume file for pulse={pulse} time={time}")
        cache_path = cached_raw_volume_path(item, volume, settings.remote_aggregate_cache_dir)
        if raw_volume_cached(item, volume):
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "raw cache prefetch worker",
                    "radar": item.radar,
                    "date": item.date,
                    "pulse": pulse,
                    "time": time,
                    "status": "already cached",
                    "elapsed_ms": 0.0,
                    "file_size": volume.file_size,
                }
            )
            return {
                "status": "cached",
                "pulse": pulse,
                "time": time,
                "cache_path": str(cache_path),
            }
        key = f"{item.radar}:{item.date}:{pulse}:{time}"
        existing = raw_prefetch_jobs.get(key)
        if existing is not None and hasattr(existing, "done") and not existing.done():  # type: ignore[attr-defined]
            return {"status": "queued", "pulse": pulse, "time": time, "cache_path": str(cache_path)}

        def download() -> str:
            start = time_module.perf_counter()
            try:
                path = ensure_raw_volume_cached(
                    item,
                    volume,
                    settings.remote_aggregate_cache_dir,
                    settings.object_store_external_base,
                    max_age_seconds=settings.remote_cache_ttl_seconds,
                    max_bytes=settings.remote_cache_max_bytes,
                )
                record_performance_event(
                    {
                        "kind": "operation",
                        "operation": "raw cache prefetch worker",
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": pulse,
                        "time": time,
                        "status": "complete",
                        "elapsed_ms": _elapsed_ms(start),
                        "file_size": volume.file_size,
                        "cache_path": str(path),
                    }
                )
                return str(path)
            except Exception as exc:
                record_performance_event(
                    {
                        "kind": "operation",
                        "operation": "raw cache prefetch worker",
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": pulse,
                        "time": time,
                        "status": "failed",
                        "elapsed_ms": _elapsed_ms(start),
                        "file_size": volume.file_size,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                raise

        raw_prefetch_jobs[key] = raw_prefetch_pool.submit(download)
        return {"status": "queued", "pulse": pulse, "time": time, "cache_path": str(cache_path)}

    def cached_ppi_response(key: str) -> dict[str, object] | None:
        if key not in ppi_response_cache:
            return None
        if key in ppi_response_cache_order:
            ppi_response_cache_order.remove(key)
        ppi_response_cache_order.append(key)
        return ppi_response_cache[key]

    def store_ppi_response(key: str, payload: dict[str, object]) -> None:
        ppi_response_cache[key] = payload
        if key in ppi_response_cache_order:
            ppi_response_cache_order.remove(key)
        ppi_response_cache_order.append(key)
        while len(ppi_response_cache_order) > max_ppi_response_cache_entries:
            old_key = ppi_response_cache_order.pop(0)
            ppi_response_cache.pop(old_key, None)

    def local_dataset_payload() -> dict[str, object]:
        manifest_path = settings.object_store_manifest_path
        if manifest_path.exists():
            manifest = load_plan(manifest_path)
            metadata_objects = [obj for obj in manifest.objects if obj.kind == "dataset_metadata" and Path(obj.source_path).exists()]
            if metadata_objects:
                import json

                return json.loads(Path(metadata_objects[0].source_path).read_text(encoding="utf-8"))
        return public_dataset_metadata_payload(
            catalog(),
            settings.object_store_external_base,
            "uk-radar",
            {
                "title": "UK WSR aggregate HDF5",
                "description": "Public metadata fallback generated from the local UK WSR Visualizer catalog.",
                "license": "proprietary",
                "citation": "",
                "provider_name": "NCAS Radar Science Group",
                "provider_url": "",
                "contact_email": "",
                "terms_url": "",
            },
            {"report_count": 0, "by_parity_status": {}, "reports": []},
        )

    def catalog_radar_records() -> list[dict[str, object]]:
        if using_pvol_catalog():
            return pvol_radar_records(pvol_root())
        records = {str(record["slug"]): dict(record) for record in radar_records()}
        for item in catalog():
            spatial = item.root_attrs.get("uk_wsr:spatial") if isinstance(item.root_attrs, dict) else None
            if not isinstance(spatial, dict):
                continue
            try:
                lat = float(spatial["latitude"])
                lon = float(spatial["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue
            record = records.setdefault(
                item.radar,
                {
                    "slug": item.radar,
                    "radar_num": item.radar_num,
                    "label": item.radar.replace("-", " ").title(),
                    "latitude": None,
                    "longitude": None,
                },
            )
            record["latitude"] = lat
            record["longitude"] = lon
            if spatial.get("height_m") is not None:
                record["height_m"] = spatial.get("height_m")
            if spatial.get("source"):
                record["spatial_source"] = spatial.get("source")
        return sorted(records.values(), key=lambda record: str(record.get("label", "")))

    def radar_filters(
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ) -> dict[str, object]:
        pairs = {
            "min_range_km": min_range_km,
            "max_range_km": max_range_km,
            "min_azimuth_deg": min_azimuth_deg,
            "max_azimuth_deg": max_azimuth_deg,
            "min_value": min_value,
            "max_value": max_value,
            "cappi_height_m": cappi_height_m,
            "palette_stops": palette_stops,
            "noise_floor_enabled": noise_floor_enabled,
            "noise_floor_method": noise_floor_method,
            "noise_floor_margin_db": noise_floor_margin_db,
            "noise_floor_operation": noise_floor_operation,
            "qc_mode": qc_mode,
            "noise_floor_percentile": noise_floor_percentile,
            "noise_floor_window_bins": noise_floor_window_bins,
            "noise_floor_texture_enabled": noise_floor_texture_enabled,
            "noise_floor_texture_db": noise_floor_texture_db,
            "noise_floor_texture_near_margin_db": noise_floor_texture_near_margin_db,
            "noise_floor_texture_support_db": noise_floor_texture_support_db,
            "noise_floor_texture_max_db": noise_floor_texture_max_db,
            "noise_floor_texture_min_similar_neighbors": noise_floor_texture_min_similar_neighbors,
            "qc_companion_enabled": qc_companion_enabled,
            "qc_static_clutter_enabled": qc_static_clutter_enabled,
            "qc_background_model_enabled": qc_background_model_enabled,
            "qc_background_model_path": qc_background_model_path,
            "qc_background_persistent_frequency_min": qc_background_persistent_frequency_min,
            "qc_background_min_samples": qc_background_min_samples,
            "qc_background_static_vrad_frequency_min": qc_background_static_vrad_frequency_min,
            "qc_background_low_sqi_frequency_min": qc_background_low_sqi_frequency_min,
            "qc_background_dbzh_excess_max_db": qc_background_dbzh_excess_max_db,
            "qc_background_evidence_score_threshold": qc_background_evidence_score_threshold,
        }
        return {key: value for key, value in pairs.items() if value is not None}

    def sampled_gate_edges(metadata, row_stride: int, column_stride: int, rows: int, columns: int) -> dict[str, list[float]]:
        azimuth_edges = [
            (min(index * row_stride, metadata.nrays) / max(metadata.nrays, 1)) * 360.0
            for index in range(rows + 1)
        ]
        range_edges = [
            metadata.rstart_km * 1000.0 + min(index * column_stride, metadata.nbins) * metadata.rscale_m
            for index in range(columns + 1)
        ]
        return {
            "azimuth_deg": [float(value) for value in azimuth_edges],
            "range_m": [float(value) for value in range_edges],
        }

    @app.get("/")
    def index():
        return FileResponse(
            static_dir / "index.html",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @app.get("/api/ready")
    def ready():
        return {
            "ok": True,
            "catalog_source": catalog_source_label(),
        }

    @app.get("/api/status")
    def status():
        catalog_error = ""
        item_count = 0
        try:
            if using_pvol_catalog():
                item_count = int(pvol_catalog_summary(pvol_root())["item_count"])
            else:
                item_count = len(catalog())
        except HTTPException as exc:
            catalog_error = str(exc.detail)
        except Exception as exc:
            catalog_error = str(exc)
        return {
            "ok": not catalog_error,
            "catalog_path": str(settings.catalog_path),
            "catalog_source": catalog_source_label(),
            "remote_catalog": using_remote_catalog(),
            "catalog_type": "pvol" if using_pvol_catalog() else "inventory",
            "item_count": item_count,
            "catalog_error": catalog_error,
            "raw_cache_dir": str(settings.remote_aggregate_cache_dir),
            "raw_cache_ttl_seconds": settings.remote_cache_ttl_seconds,
            "raw_cache_max_bytes": settings.remote_cache_max_bytes,
            "deployment_target": "configured deployment target",
        }

    @app.get("/api/performance")
    def performance_report(limit: int = 120):
        """Return recent server-side timing events for local diagnostics."""

        bounded_limit = max(1, min(int(limit), 400))
        return {
            "ok": True,
            "event_count": len(performance_events),
            "events": list(performance_events)[-bounded_limit:],
            "cache": {
                "hydrated_items": len(hydrated_items),
                "pvol_coverages": len(pvol_coverage_cache),
                "pvol_day_catalogs": len(pvol_day_cache),
                "pvol_field_indexes": len(pvol_field_index_cache),
                "ppi_frames": len(ppi_response_cache),
                "raw_prefetch_jobs": len(raw_prefetch_jobs),
            },
        }

    @app.post("/api/performance/clear")
    def clear_performance_report():
        performance_events.clear()
        return {"ok": True, "event_count": 0}

    @app.get("/api/citation")
    def citation():
        return citation_payload()

    @app.get("/api/radars")
    def radars():
        return {"radars": catalog_radar_records()}

    @app.get("/api/catalog")
    def search_catalog(
        radar: str | None = None,
        start: str | None = None,
        end: str | None = None,
        pulse: str | None = None,
        quantity: str | None = None,
    ):
        matches = pvol_search_items(radar, start, end, pulse, quantity) if using_pvol_catalog() else filter_catalog(catalog(), radar, start, end, pulse, quantity)
        return {"items": [_item_payload(item) for item in matches]}

    @app.get("/api/catalog/summary")
    def summary():
        return pvol_catalog_summary(pvol_root()) if using_pvol_catalog() else catalog_summary(catalog())

    @app.get("/api/catalog/availability")
    def catalog_availability(radar: str | None = None):
        if using_pvol_catalog():
            summary_payload = pvol_catalog_summary(pvol_root())
            coverage = summary_payload["by_radar"].get(radar) if radar else None
            if radar and isinstance(coverage, dict):
                return {
                    "radar": radar,
                    "item_count": coverage.get("item_count", 0),
                    "start_date": coverage.get("start_date"),
                    "end_date": coverage.get("end_date"),
                    "first_plot_ready_date": coverage.get("first_plot_ready_date"),
                    "latest_plot_ready_date": coverage.get("latest_plot_ready_date"),
                    "plot_ready_probe": False,
                }
            return {
                "radar": radar or "",
                "item_count": summary_payload["item_count"],
                "start_date": summary_payload["start_date"],
                "end_date": summary_payload["end_date"],
                "first_plot_ready_date": summary_payload["start_date"],
                "latest_plot_ready_date": summary_payload["end_date"],
                "plot_ready_probe": False,
            }
        items = filter_catalog(catalog(), radar=radar)
        dates = sorted({item.date for item in items})
        payload = {
            "radar": radar or "",
            "item_count": len(items),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "first_plot_ready_date": None,
            "latest_plot_ready_date": None,
            "plot_ready_probe": bool(radar),
        }
        if radar:
            payload["first_plot_ready_date"] = first_plot_ready_date(items)
            payload["latest_plot_ready_date"] = latest_plot_ready_date(items)
        return payload

    @app.get("/api/catalog/public")
    def public_catalog():
        if using_pvol_catalog():
            key = "ukmo-nimrod/catalog/pvol/catalog.json"
            return {
                "catalog_key": key,
                "catalog_url": join_object_url(settings.object_store_external_base, key),
                "catalog_type": "pvol",
                "summary": pvol_catalog_summary(pvol_root()),
                "radars": pvol_radar_records(pvol_root()),
            }
        return {
            "catalog_key": "uk-radar/catalog/inventory/catalog.json",
            "catalog_url": join_object_url(settings.object_store_external_base, "uk-radar/catalog/inventory/catalog.json"),
            "items": [_item_payload(item) for item in catalog()],
        }

    @app.get("/api/public/dataset")
    def public_dataset_metadata():
        return local_dataset_payload()

    @app.get("/public", response_class=HTMLResponse)
    def public_landing():
        return public_landing_html(local_dataset_payload())

    @app.get("/api/stac/catalog")
    def stac_catalog():
        return root_catalog_to_stac(catalog(), public_base_url=settings.object_store_external_base)

    @app.get("/api/stac/collections/{collection_id}")
    def stac_collection(collection_id: str):
        if collection_id != AGGREGATE_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="STAC collection not found")
        return collection_to_stac(catalog(), public_base_url=settings.object_store_external_base)

    @app.get("/api/stac/collections/{collection_id}/items/{item_id}")
    def stac_item(collection_id: str, item_id: str):
        if collection_id != AGGREGATE_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="STAC collection not found")
        for entry in catalog():
            if entry.item_id == item_id:
                return item_to_stac(entry, public_base_url=settings.object_store_external_base)
        raise HTTPException(status_code=404, detail="STAC item not found")

    @app.get("/api/object-store/status")
    def object_store_status():
        manifest_path = settings.object_store_manifest_path
        if not manifest_path.exists():
            return {
                "ok": False,
                "manifest_path": str(manifest_path),
                "message": "no local object-store manifest has been published yet",
            }
        manifest = load_plan(manifest_path)
        return {
            "ok": all(obj.status == "verified" for obj in manifest.objects),
            "manifest_path": str(manifest_path),
            **manifest.summary(),
        }

    @app.get("/api/object-store/manifest/latest")
    def latest_object_store_manifest():
        manifest_path = settings.object_store_manifest_path
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="object-store manifest not found")
        return load_plan(manifest_path).to_dict()

    @app.get("/api/cache/raw")
    def raw_cache():
        prune_cache()
        return raw_cache_status(settings.remote_aggregate_cache_dir)

    @app.post("/api/cache/raw/clear")
    def clear_cache():
        hydrated_items.clear()
        return clear_raw_cache(settings.remote_aggregate_cache_dir)

    @app.get("/api/recent-selections")
    def recent_selections():
        return {"items": load_recent_selections(settings.recent_selections_path)}

    @app.post("/api/recent-selections")
    def save_recent_selection(request: dict[str, object]):
        try:
            items = record_recent_selection(settings.recent_selections_path, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"items": items}

    @app.delete("/api/recent-selections")
    def delete_recent_selections():
        clear_recent_selections(settings.recent_selections_path)
        return {"items": []}

    @app.get("/api/freshness")
    def freshness(
        max_catalog_age_hours: float = 24.0,
        max_data_latency_days: float = 3.0,
        max_manifest_age_hours: float = 30.0,
        require_object_store: bool = False,
        require_wct_validation: bool = False,
    ):
        if using_pvol_catalog():
            checks = []
            try:
                root = pvol_root()
                summary_payload = pvol_catalog_summary(root)
                checks.append(
                    {
                        "name": "remote_catalog_loaded",
                        "ok": True,
                        "severity": "critical",
                        "message": "remote PVOL catalog loaded",
                        "details": {
                            "catalog_source": settings.remote_catalog_url,
                            "catalog_type": "pvol",
                            "item_count": summary_payload["item_count"],
                            "radar_count": len(summary_payload["radars"]),
                            "interim": root.get("interim", False),
                            "upload_complete": root.get("upload_complete", True),
                        },
                    }
                )
                checks.append(
                    {
                        "name": "remote_catalog_not_empty",
                        "ok": bool(summary_payload["item_count"]),
                        "severity": "critical",
                        "message": f"remote PVOL catalog contains {summary_payload['item_count']} day(s)",
                        "details": {
                            "item_count": summary_payload["item_count"],
                            "start_date": summary_payload["start_date"],
                            "end_date": summary_payload["end_date"],
                        },
                    }
                )
                return {
                    "ok": all(check["ok"] or check["severity"] == "warning" for check in checks),
                    "created_at": build_freshness_report(
                        catalog_path=settings.catalog_path,
                        object_store_manifest_path=settings.object_store_manifest_path,
                    ).created_at,
                    "catalog_path": str(settings.catalog_path),
                    "catalog_source": settings.remote_catalog_url,
                    "remote_catalog": True,
                    "object_store_manifest_path": str(settings.object_store_manifest_path),
                    "checks": checks,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "catalog_path": str(settings.catalog_path),
                    "catalog_source": settings.remote_catalog_url,
                    "remote_catalog": True,
                    "object_store_manifest_path": str(settings.object_store_manifest_path),
                    "checks": [
                        {
                            "name": "remote_catalog_loaded",
                            "ok": False,
                            "severity": "critical",
                            "message": f"remote PVOL catalog unavailable: {type(exc).__name__}: {exc}",
                            "details": {"catalog_source": settings.remote_catalog_url},
                        }
                    ],
                }
        return build_freshness_report(
            catalog_path=settings.catalog_path,
            object_store_manifest_path=settings.object_store_manifest_path,
            max_catalog_age_hours=max_catalog_age_hours,
            max_data_latency_days=max_data_latency_days,
            max_manifest_age_hours=max_manifest_age_hours,
            require_object_store=require_object_store,
            require_wct_validation=require_wct_validation,
        ).to_dict()

    @app.get("/api/item/{radar}/{date}")
    def item(radar: str, date: str):
        return _item_payload(find_item(radar, date))

    @app.get("/api/item/{radar}/{date}/hydrate")
    def hydrate_catalog_item(radar: str, date: str):
        steps: list[dict[str, object]] = []
        start = time_module.perf_counter()
        with _timed_step(steps, "find catalog item"):
            base_item = find_item(radar, date)
        with _timed_step(steps, "hydrate item metadata"):
            hydrated = hydrate_item(base_item)
        elapsed = _elapsed_ms(start)
        record_performance_event(
            {
                "kind": "operation",
                "operation": "hydrate item",
                "radar": radar,
                "date": date,
                "elapsed_ms": elapsed,
                "steps": steps,
                "source_type": hydrated.source_type,
                "raw_volume_count": len(hydrated.raw_volumes),
                "quantity_count": len(hydrated.quantities),
                "field_index_loaded": bool(hydrated.root_attrs.get("field_index_loaded")),
            }
        )
        payload = _item_payload(hydrated)
        payload["_performance"] = {"elapsed_ms": elapsed, "steps": steps}
        return payload

    @app.get("/api/object-url/{radar}/{date}")
    def object_url(radar: str, date: str):
        item = hydrate_item(find_item(radar, date))
        return {
            "radar": item.radar,
            "date": item.date,
            "object_key": item.object_key,
            "object_url": item.object_url,
            "external_url": item.object_url or join_object_url(settings.object_store_external_base, item.object_key),
        }

    @app.get("/api/raw-cache/day/{radar}/{date}")
    def raw_cache_day_status(radar: str, date: str):
        start = time_module.perf_counter()
        item = hydrate_item(find_item(radar, date))
        files = [
            {
                "pulse": volume.pulse,
                "time": volume.time,
                "filename": volume.filename,
                "size_bytes": volume.file_size,
                "cached": raw_volume_cached(item, volume),
            }
            for volume in item.raw_volumes
        ]
        elapsed = _elapsed_ms(start)
        record_performance_event(
            {
                "kind": "operation",
                "operation": "raw cache status",
                "radar": item.radar,
                "date": item.date,
                "elapsed_ms": elapsed,
                "raw_volume_count": len(files),
                "cached_count": sum(1 for file in files if file["cached"]),
            }
        )
        return {
            "radar": item.radar,
            "date": item.date,
            "files": files,
            "_performance": {"elapsed_ms": elapsed},
        }

    @app.post("/api/raw-cache/prefetch/{radar}/{date}/{pulse}/{time}")
    def raw_cache_prefetch(radar: str, date: str, pulse: str, time: str):
        start = time_module.perf_counter()
        item = hydrate_item(find_item(radar, date))
        payload = queue_raw_volume_prefetch(item, pulse, time)
        elapsed = _elapsed_ms(start)
        record_performance_event(
            {
                "kind": "operation",
                "operation": "raw cache prefetch enqueue",
                "radar": item.radar,
                "date": item.date,
                "pulse": pulse,
                "time": time,
                "elapsed_ms": elapsed,
                "prefetch_status": payload.get("status"),
            }
        )
        payload["_performance"] = {"elapsed_ms": elapsed}
        return payload

    def preview_request(
        item: CatalogItem,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        palette: str = "gray",
        filters: dict[str, object] | None = None,
    ) -> PreviewRequest:
        source_path: Path
        if item.source_type == "raw_volume_day":
            volume = item.raw_volume_for(pulse, time)
            if volume is None:
                available = sorted({f"{candidate.pulse} {candidate.time}" for candidate in item.raw_volumes})
                hint = ", ".join(available[:8])
                if len(available) > 8:
                    hint += f", plus {len(available) - 8} more"
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"The catalog entry for {item.radar} {item.date} does not include a raw-volume file for "
                        f"pulse={pulse} time={time}. Available raw-volume selections: {hint or 'none'}. "
                        "Refresh the catalog or choose a listed time."
                    ),
                )
            try:
                source_path = ensure_raw_volume_cached(
                    item,
                    volume,
                    settings.remote_aggregate_cache_dir,
                    settings.object_store_external_base,
                    max_age_seconds=settings.remote_cache_ttl_seconds,
                    max_bytes=settings.remote_cache_max_bytes,
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"raw-volume unavailable: {type(exc).__name__}: {exc}") from exc
        else:
            local_path = Path(item.path)
            if item.path and local_path.exists() and local_path.is_file():
                source_path = local_path
            else:
                item = hydrate_item(item)
                source_path = Path(item.path)
        return PreviewRequest(
            aggregate_path=source_path,
            radar=item.radar,
            date=item.date,
            pulse=pulse,
            time=time,
            quantity=quantity,
            dataset=dataset,
            palette=palette,
            filters=filters or {},
            output_dir=settings.preview_dir / item.radar / item.date,
        )

    def export_source_for_time(item: CatalogItem, request: ExportRequest, time: str) -> Path:
        if item.source_type != "raw_volume_day":
            return Path(item.path)
        volume = item.raw_volume_for(request.pulse or "", time)
        if volume is None:
            available = sorted({f"{candidate.pulse} {candidate.time}" for candidate in item.raw_volumes})
            hint = ", ".join(available[:8])
            if len(available) > 8:
                hint += f", plus {len(available) - 8} more"
            raise ValueError(
                f"raw-volume file not found for pulse={request.pulse} time={time}; "
                f"available raw-volume selections: {hint or 'none'}"
            )
        return ensure_raw_volume_cached(
            item,
            volume,
            settings.remote_aggregate_cache_dir,
            settings.object_store_external_base,
            max_age_seconds=settings.remote_cache_ttl_seconds,
            max_bytes=settings.remote_cache_max_bytes,
        )

    @app.get("/api/preview/{radar}/{date}/{pulse}/{time}/{quantity}")
    def preview(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        palette: str = "gray",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        output = generate_preview(
            preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    noise_floor_percentile,
                    noise_floor_window_bins,
                    noise_floor_texture_enabled,
                    noise_floor_texture_db,
                    noise_floor_texture_near_margin_db,
                    noise_floor_texture_support_db,
                    noise_floor_texture_max_db,
                    noise_floor_texture_min_similar_neighbors,
                    qc_companion_enabled,
                    qc_static_clutter_enabled,
                    qc_background_model_enabled,
                    qc_background_model_path,
                    qc_background_persistent_frequency_min,
                    qc_background_min_samples,
                    qc_background_static_vrad_frequency_min,
                    qc_background_low_sqi_frequency_min,
                    qc_background_dbzh_excess_max_db,
                    qc_background_evidence_score_threshold,
                ),
            )
        )
        return FileResponse(output)

    @app.get("/api/preview-meta/{radar}/{date}/{pulse}/{time}/{quantity}")
    def preview_meta(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        palette: str = "gray",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        return asdict(
            preview_metadata(
                preview_request(
                    item,
                    pulse,
                    time,
                    quantity,
                    dataset,
                    palette,
                    radar_filters(
                        min_range_km,
                        max_range_km,
                        min_azimuth_deg,
                        max_azimuth_deg,
                        min_value,
                        max_value,
                        cappi_height_m,
                        palette_stops,
                        noise_floor_enabled,
                        noise_floor_method,
                        noise_floor_margin_db,
                        noise_floor_operation,
                        qc_mode,
                        noise_floor_percentile,
                        noise_floor_window_bins,
                        noise_floor_texture_enabled,
                        noise_floor_texture_db,
                        noise_floor_texture_near_margin_db,
                        noise_floor_texture_support_db,
                        noise_floor_texture_max_db,
                        noise_floor_texture_min_similar_neighbors,
                        qc_companion_enabled,
                        qc_static_clutter_enabled,
                        qc_background_model_enabled,
                        qc_background_model_path,
                        qc_background_persistent_frequency_min,
                        qc_background_min_samples,
                        qc_background_static_vrad_frequency_min,
                        qc_background_low_sqi_frequency_min,
                        qc_background_dbzh_excess_max_db,
                        qc_background_evidence_score_threshold,
                    ),
                )
            )
        )

    @app.get("/api/ppi-image/{radar}/{date}/{pulse}/{time}/{quantity}")
    def ppi_image(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        palette: str = "auto",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
    ):
        steps: list[dict[str, object]] = []
        start = time_module.perf_counter()
        with _timed_step(steps, "find and hydrate item"):
            item = hydrate_item(find_item(radar, date))
        with _timed_step(steps, "resolve raw file and request"):
            request = preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                ),
            )
        with _timed_step(steps, "render PNG preview"):
            output = generate_preview(request)
        elapsed = _elapsed_ms(start)
        record_performance_event(
            {
                "kind": "operation",
                "operation": "ppi image",
                "radar": radar,
                "date": date,
                "pulse": pulse,
                "time": time,
                "quantity": quantity,
                "dataset": dataset,
                "elapsed_ms": elapsed,
                "source_path": str(request.aggregate_path),
                "output": str(output),
                "steps": steps,
            }
        )
        return FileResponse(
            output,
            media_type="image/png",
            headers={
                "X-UK-WSR-Coordinate-Mode": "polar-ppi",
                "X-UK-WSR-Frame": f"{radar}/{date}/{pulse}/{time}/{quantity}",
                "X-UK-WSR-Operation-Elapsed-Ms": str(elapsed),
            },
        )

    @app.get("/api/ppi/{radar}/{date}/{pulse}/{time}/{quantity}")
    def ppi(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        palette: str = "auto",
        max_rays: int = 360,
        max_bins: int = 320,
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        display_min: float | None = None,
        display_max: float | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        operation_start = time_module.perf_counter()
        steps: list[dict[str, object]] = []
        with _timed_step(steps, "find and hydrate item"):
            item = hydrate_item(find_item(radar, date))
        with _timed_step(steps, "resolve raw file and request"):
            request = preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    noise_floor_percentile,
                    noise_floor_window_bins,
                    noise_floor_texture_enabled,
                    noise_floor_texture_db,
                    noise_floor_texture_near_margin_db,
                    noise_floor_texture_support_db,
                    noise_floor_texture_max_db,
                    noise_floor_texture_min_similar_neighbors,
                    qc_companion_enabled,
                    qc_static_clutter_enabled,
                    qc_background_model_enabled,
                    qc_background_model_path,
                    qc_background_persistent_frequency_min,
                    qc_background_min_samples,
                    qc_background_static_vrad_frequency_min,
                    qc_background_low_sqi_frequency_min,
                    qc_background_dbzh_excess_max_db,
                    qc_background_evidence_score_threshold,
                ),
            )
        cache_key = json.dumps(
            {
                "radar": radar,
                "date": date,
                "pulse": pulse,
                "time": time,
                "quantity": quantity,
                "dataset": dataset,
                "palette": palette,
                "max_rays": max_rays,
                "max_bins": max_bins,
                "display_min": display_min,
                "display_max": display_max,
                "filters": request.filters,
            },
            sort_keys=True,
            default=str,
        )
        cached = cached_ppi_response(cache_key)
        if cached is not None:
            elapsed = _elapsed_ms(operation_start)
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "ppi",
                    "radar": radar,
                    "date": date,
                    "pulse": pulse,
                    "time": time,
                    "quantity": quantity,
                    "dataset": dataset,
                    "cache_hit": True,
                    "elapsed_ms": elapsed,
                    "steps": steps,
                }
            )
            payload = dict(cached)
            payload["_performance"] = {"elapsed_ms": elapsed, "cache_hit": True, "steps": steps}
            return payload
        try:
            with _timed_step(steps, "read HDF5 field and companions"):
                data, metadata, companion_fields = read_polar_field_with_companions(
                    request.aggregate_path,
                    request.radar,
                    request.date,
                    field_selection_from_request(request),
                )
            with _timed_step(steps, "apply filters and QC"):
                filter_result = apply_polar_filters(
                    data,
                    metadata,
                    request.filters,
                    return_metadata=True,
                    companion_fields=companion_fields,
                )
                data = filter_result.values
            with _timed_step(steps, "sample and scale field"):
                np = require_numpy()
                max_rays = max(24, min(int(max_rays), 1440))
                max_bins = max(24, min(int(max_bins), 1200))
                row_stride = max(1, int((data.shape[0] + max_rays - 1) // max_rays))
                column_stride = max(1, int((data.shape[1] + max_bins - 1) // max_bins))
                sampled = data[::row_stride, ::column_stride]
                display = _quantity_display_config(quantity, palette)
                resolved_palette = str(display["palette"])
                display_scale_min = display_min if display_min is not None else display["scale_min"]
                display_scale_max = display_max if display_max is not None else display["scale_max"]
                scaled, stats = _scale_to_uint8_with_limits(
                    sampled,
                    display_scale_min if isinstance(display_scale_min, float) else None,
                    display_scale_max if isinstance(display_scale_max, float) else None,
                )
                valid = np.isfinite(sampled)
                if display["mask_below_min"] and isinstance(display_scale_min, float):
                    valid &= sampled >= display_scale_min
                rows = int(sampled.shape[0])
                columns = int(sampled.shape[1])
            elapsed = _elapsed_ms(operation_start)
            payload = {
                "metadata": metadata.to_dict(),
                "source_shape": [int(data.shape[0]), int(data.shape[1])],
                "rows": rows,
                "columns": columns,
                "row_stride": row_stride,
                "column_stride": column_stride,
                "gate_edges": sampled_gate_edges(metadata, row_stride, column_stride, rows, columns),
                "scaled": scaled.tolist(),
                "valid": valid.astype("uint8").tolist(),
                "stats": stats,
                "palette": resolved_palette,
                "requested_palette": palette,
                "mask_below_min": bool(display["mask_below_min"]),
                "palette_stops": palette_stops,
                "filters": request.filters or {},
                "noise_floor": filter_result.noise_floor.to_dict(),
                "qc": filter_result.qc.to_dict() if filter_result.qc is not None else {"enabled": False},
                "_performance": {
                    "elapsed_ms": elapsed,
                    "cache_hit": False,
                    "steps": steps,
                    "source_path": str(request.aggregate_path),
                },
            }
            store_ppi_response(cache_key, payload)
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "ppi",
                    "radar": radar,
                    "date": date,
                    "pulse": pulse,
                    "time": time,
                    "quantity": quantity,
                    "dataset": dataset,
                    "cache_hit": False,
                    "elapsed_ms": elapsed,
                    "source_shape": [int(data.shape[0]), int(data.shape[1])],
                    "sampled_shape": [rows, columns],
                    "source_path": str(request.aggregate_path),
                    "steps": steps,
                }
            )
            return payload
        except Exception as exc:
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "ppi",
                    "radar": radar,
                    "date": date,
                    "pulse": pulse,
                    "time": time,
                    "quantity": quantity,
                    "dataset": dataset,
                    "cache_hit": False,
                    "elapsed_ms": _elapsed_ms(operation_start),
                    "steps": steps,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

    @app.get("/api/identify/{radar}/{date}/{pulse}/{time}/{quantity}")
    def identify(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        row: int,
        column: int,
        dataset: str | None = None,
        palette: str = "gray",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        return identify_value(
            preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    noise_floor_percentile,
                    noise_floor_window_bins,
                    noise_floor_texture_enabled,
                    noise_floor_texture_db,
                    noise_floor_texture_near_margin_db,
                    noise_floor_texture_support_db,
                    noise_floor_texture_max_db,
                    noise_floor_texture_min_similar_neighbors,
                    qc_companion_enabled,
                    qc_static_clutter_enabled,
                    qc_background_model_enabled,
                    qc_background_model_path,
                    qc_background_persistent_frequency_min,
                    qc_background_min_samples,
                    qc_background_static_vrad_frequency_min,
                    qc_background_low_sqi_frequency_min,
                    qc_background_dbzh_excess_max_db,
                    qc_background_evidence_score_threshold,
                ),
            ),
            row,
            column,
        )

    @app.get("/api/contours/{radar}/{date}/{pulse}/{time}/{quantity}")
    def contours(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        levels: str | None = None,
        max_segments: int = 50_000,
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        filters = radar_filters(
            min_range_km,
            max_range_km,
            min_azimuth_deg,
            max_azimuth_deg,
            min_value,
            max_value,
            cappi_height_m,
            None,
        )
        filters["max_segments"] = float(max_segments)
        if levels:
            try:
                filters["levels"] = [float(value.strip()) for value in levels.split(",") if value.strip()]
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="levels must be a comma-separated list of numbers") from exc
        request = ExportRequest(
            radar=radar,
            date=date,
            format="geojson",
            pulse=pulse,
            time=time,
            quantity=quantity,
            dataset=dataset,
            filters=filters,
        )
        try:
            source_path = export_source_for_time(item, request, time)
            cartesian = read_cartesian_field(source_path, item.radar, item.date, field_selection_from_request(request), filters=filters)
            return contour_feature_collection(cartesian, request)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

    @app.post("/api/export")
    def export(request: dict[str, object]):
        try:
            export_request = ExportRequest(**request)
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = hydrate_item(find_item(export_request.radar, export_request.date))
        source_resolver = (
            (lambda time: export_source_for_time(item, export_request, time))
            if item.source_type == "raw_volume_day"
            else None
        )
        job = run_export(export_request, item, settings.export_dir, source_for_time=source_resolver)
        return asdict(job)

    @app.post("/api/math")
    def math_product(request: dict[str, object]):
        try:
            left = MathOperand(**request["left"])  # type: ignore[arg-type]
            right = MathOperand(**request["right"])  # type: ignore[arg-type]
            math_request = MathRequest(
                radar=str(request["radar"]),
                date=str(request["date"]),
                operation=str(request["operation"]),
                left=left,
                right=right,
                format=str(request.get("format", "png")),
                filters=request.get("filters", {}) if isinstance(request.get("filters", {}), dict) else {},
                palette=str(request.get("palette", "thermal")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = hydrate_item(find_item(math_request.radar, math_request.date))
        try:
            product = run_math(math_request, item, settings.export_dir / "math")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
        return asdict(product)

    @app.post("/api/animation")
    def animation_product(request: dict[str, object]):
        try:
            times_raw = request.get("times", [])
            times = [str(value) for value in times_raw] if isinstance(times_raw, list) else []
            animation_request = AnimationRequest(
                radar=str(request["radar"]),
                date=str(request["date"]),
                pulse=str(request["pulse"]),
                quantity=str(request["quantity"]),
                times=times,
                dataset=str(request["dataset"]) if request.get("dataset") else None,
                palette=str(request.get("palette", "gray")),
                filters=request.get("filters", {}) if isinstance(request.get("filters", {}), dict) else {},
                frame_delay_ms=int(request.get("frame_delay_ms", 600)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = hydrate_item(find_item(animation_request.radar, animation_request.date))
        try:
            product = run_animation(
                animation_request,
                item,
                settings.export_dir / "animations",
                settings.preview_dir,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc
        return asdict(product)

    @app.post("/api/tiles")
    def tile_product(request: dict[str, object]):
        try:
            filters = request.get("filters", {}) if isinstance(request.get("filters", {}), dict) else {}
            item = hydrate_item(find_item(str(request["radar"]), str(request["date"])))
            source_request = ExportRequest(
                radar=str(request["radar"]),
                date=str(request["date"]),
                format="png",
                pulse=str(request["pulse"]),
                time=str(request["time"]),
                quantity=str(request["quantity"]),
                dataset=str(request["dataset"]) if request.get("dataset") else None,
                filters=filters,
            )
            tile_request = TileRequest(
                aggregate_path=export_source_for_time(item, source_request, str(request["time"])),
                radar=str(request["radar"]),
                date=str(request["date"]),
                pulse=str(request["pulse"]),
                time=str(request["time"]),
                quantity=str(request["quantity"]),
                dataset=str(request["dataset"]) if request.get("dataset") else None,
                palette=str(request.get("palette", "gray")),
                filters=filters,
                tile_size=int(request.get("tile_size", 256)),
                min_zoom=int(request.get("min_zoom", 0)),
                max_zoom=int(request.get("max_zoom", 2)),
                output_dir=settings.tile_dir,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return tile_manifest(generate_tile_pyramid(tile_request))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}") from exc

    @app.get("/api/tiles/{tile_path:path}")
    def tile_file(tile_path: str):
        if ".." in Path(tile_path).parts:
            raise HTTPException(status_code=400, detail="invalid tile path")
        path = (settings.tile_dir / tile_path).resolve()
        try:
            path.relative_to(settings.tile_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid tile path") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="tile not found")
        return FileResponse(path)

    @app.get("/api/export/{job_id}")
    def export_status(job_id: str):
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        return asdict(job)

    @app.get("/api/export/{job_id}/download")
    def export_download(job_id: str):
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        if job.status != "complete":
            raise HTTPException(status_code=400, detail="export job is not complete")
        path = export_download_path(settings.export_dir, job)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="export artifact not found")
        try:
            path.resolve().relative_to(settings.export_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid export artifact path") from exc
        return FileResponse(path, filename=path.name)

    @app.get("/api/export/{job_id}/manifest")
    def export_manifest(job_id: str):
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        if job.status != "complete" or not job.artifact_manifest_path:
            raise HTTPException(status_code=400, detail="export manifest is not available")
        path = Path(job.artifact_manifest_path).resolve()
        try:
            path.relative_to(settings.export_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid export manifest path") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="export manifest not found")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/session")
    def sessions():
        return {"sessions": [asdict(session) for session in list_sessions(settings.session_dir)]}

    @app.post("/api/session/{session_id}")
    def save_viewer_session(session_id: str, request: dict[str, object]):
        state = request.get("state")
        if not isinstance(state, dict):
            raise HTTPException(status_code=400, detail="session request requires an object-valued 'state'")
        title = request.get("title")
        try:
            session = save_session(settings.session_dir, session_id, state, title=title if isinstance(title, str) else "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(session)

    @app.get("/api/session/{session_id}")
    def session(session_id: str):
        try:
            saved = load_session(settings.session_dir, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if saved is None:
            raise HTTPException(status_code=404, detail="session not found")
        return asdict(saved)

    @app.get("/api/session/{session_id}/project")
    def session_project(session_id: str):
        try:
            saved = load_session(settings.session_dir, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if saved is None:
            raise HTTPException(status_code=404, detail="session not found")
        return project_to_dict(session_to_project(saved))

    @app.post("/api/session/{session_id}/project")
    def import_viewer_project(session_id: str, request: dict[str, object]):
        payload = request.get("project", request)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="project import requires an object payload")
        try:
            project = project_from_dict(payload)
            saved = import_project(settings.session_dir, project, session_id=session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(saved)

    return app


app = create_app()
