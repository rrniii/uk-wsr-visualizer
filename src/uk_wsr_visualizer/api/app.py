"""FastAPI app for the UK WSR Visualizer."""

from __future__ import annotations

import time as time_module
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except (
    ImportError
) as exc:  # pragma: no cover - exercised when dependencies are missing.
    raise RuntimeError(
        "FastAPI dependencies are missing. Install with: pip install -e ."
    ) from exc

from ..catalog import (
    CatalogItem,
    QuantityRecord,
    RawVolumeRecord,
    catalog_public_base_from_root_url,
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
from ..export import ExportRequest
from ..http_cache import load_json_cached
from ..object_store import join_object_url
from ..object_store_manifest import load_plan, public_dataset_metadata_payload
from ..preview import PreviewRequest
from ..radars import radar_records
from ..remote_cache import (
    cached_raw_volume_path,
    ensure_raw_volume_cached,
    hydrate_item_from_raw_aggregate,
    prune_raw_cache,
)


from .catalog_routes import register_catalog_routes
from .export_routes import register_export_routes
from .render_routes import register_render_routes
from .session_routes import register_session_routes
from .support import LOCAL_DOWNLOAD_LIMIT_BYTES as LOCAL_DOWNLOAD_LIMIT_BYTES
from .support import (
    PLOT_METADATA_DOWNLOAD_LIMIT_BYTES,
    _elapsed_ms,
    _raw_volume_item_has_files,
)
from .support import QCQueryParameters as QCQueryParameters


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local API and static viewer application."""

    settings = settings or Settings.from_env()
    app = FastAPI(title="UK WSR Visualizer", version="0.2.2")
    server_started_at = time_module.strftime("%Y-%m-%dT%H:%M:%SZ", time_module.gmtime())
    static_dir = Path(__file__).resolve().parents[1] / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    hydrated_items: dict[str, CatalogItem] = {}
    raw_volume_catalog_exists_cache: dict[tuple[str, str], bool] = {}
    pvol_root_cache: dict[str, object] | None = None
    pvol_coverage_cache: dict[str, dict[str, object]] = {}
    pvol_day_cache: dict[str, dict[str, object]] = {}
    pvol_field_index_cache: dict[str, dict[str, object] | None] = {}
    http_json_cache_dir = settings.data_dir / "http-json-cache"
    raw_prefetch_pool = ThreadPoolExecutor(
        max_workers=3, thread_name_prefix="uk-wsr-raw-prefetch"
    )
    raw_prefetch_jobs: dict[str, object] = {}
    ppi_response_cache: dict[str, dict[str, object]] = {}
    ppi_response_cache_order: list[str] = []
    max_ppi_response_cache_entries = 32
    performance_events: deque[dict[str, object]] = deque(maxlen=400)
    catalog_sources = {
        "dual-pol": {
            "id": "dual-pol",
            "label": "Dual-polarisation era",
            "description": "PVOL files with the available dual-polarisation radar moments.",
            "catalog_url": settings.remote_catalog_url,
        },
        "pre-dual-pol": {
            "id": "pre-dual-pol",
            "label": "Pre-dual-polarisation era",
            "description": "Single-polarisation REF/DOP PVOL archive. It is separate from the dual-polarisation source archive.",
            "catalog_url": settings.pre_dual_pol_remote_catalog_url,
        },
    }
    active_catalog_source_id = "dual-pol"

    def record_performance_event(event: dict[str, object]) -> None:
        payload = {
            "created_at": time_module.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time_module.gmtime()
            ),
            **event,
        }
        performance_events.append(payload)

    def cache_state() -> dict[str, int]:
        return {
            "hydrated_items": len(hydrated_items),
            "pvol_coverages": len(pvol_coverage_cache),
            "pvol_day_catalogs": len(pvol_day_cache),
            "pvol_field_indexes": len(pvol_field_index_cache),
            "ppi_frames": len(ppi_response_cache),
            "raw_prefetch_jobs": len(raw_prefetch_jobs),
        }

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

    def active_catalog_source() -> dict[str, str]:
        return catalog_sources[active_catalog_source_id]

    def active_remote_catalog_url() -> str:
        return active_catalog_source()["catalog_url"]

    def reset_catalog_caches() -> None:
        """Discard source-specific metadata when the user switches archive era."""

        nonlocal pvol_root_cache
        hydrated_items.clear()
        raw_volume_catalog_exists_cache.clear()
        pvol_root_cache = None
        pvol_coverage_cache.clear()
        pvol_day_cache.clear()
        pvol_field_index_cache.clear()
        ppi_response_cache.clear()
        ppi_response_cache_order.clear()

    def catalog() -> list[CatalogItem]:
        try:
            return load_catalog_source(
                settings.catalog_path, active_remote_catalog_url()
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail=f"catalog unavailable: {exc}"
            ) from exc

    def using_remote_catalog() -> bool:
        # The configured local catalog remains a compatibility override for the
        # default source only. A selected pre-dual archive must never silently
        # fall back to a local dual-pol catalog with the same radar/date keys.
        return bool(active_remote_catalog_url()) and (
            active_catalog_source_id != "dual-pol" or not settings.catalog_path.exists()
        )

    def using_pvol_catalog() -> bool:
        return using_remote_catalog() and catalog_url_is_pvol_root(
            active_remote_catalog_url()
        )

    def catalog_source_label() -> str:
        return (
            active_remote_catalog_url()
            if using_remote_catalog()
            else str(settings.catalog_path)
        )

    record_performance_event(
        {
            "kind": "startup",
            "operation": "api create_app",
            "server_started_at": server_started_at,
            "catalog_source": catalog_source_label(),
            "remote_catalog": using_remote_catalog(),
        }
    )

    def load_json_url(url: str, timeout_s: float = 30.0) -> dict[str, object]:
        return load_json_cached(url, http_json_cache_dir, timeout_s=timeout_s)

    def pvol_public_base() -> str:
        return settings.object_store_external_base or catalog_public_base_from_root_url(
            active_remote_catalog_url()
        )

    def pvol_root() -> dict[str, object]:
        nonlocal pvol_root_cache
        if pvol_root_cache is None:
            pvol_root_cache = load_json_url(active_remote_catalog_url())
        return pvol_root_cache

    def pvol_coverage(key: str) -> dict[str, object]:
        if key not in pvol_coverage_cache:
            pvol_coverage_cache[key] = load_json_url(
                join_catalog_url(pvol_public_base(), key), timeout_s=30.0
            )
        return pvol_coverage_cache[key]

    def pvol_day_catalog(key: str) -> dict[str, object]:
        if key not in pvol_day_cache:
            pvol_day_cache[key] = load_json_url(
                join_catalog_url(pvol_public_base(), key), timeout_s=30.0
            )
        return pvol_day_cache[key]

    def pvol_field_index(key: str, day: dict[str, object]) -> dict[str, object] | None:
        candidates: list[str] = []
        explicit_url = str(day.get("field_index_url") or "")
        explicit_key = str(
            day.get("field_index_key") or day.get("field-index_key") or ""
        )
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
            items.append(
                pvol_items_from_coverage(
                    root, radar_entry, {"days": [day]}, pvol_public_base()
                )[0]
            )
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
            for radar_entry, key in pvol_coverage_keys(
                root, radar=radar, start=start, end=end
            ):
                items.extend(
                    pvol_items_from_coverage(
                        root, radar_entry, pvol_coverage(key), pvol_public_base()
                    )
                )
        items = filter_catalog(items, radar=radar, start=start, end=end, pulse=pulse)
        if quantity:
            # PVOL coverage records deliberately avoid per-file quantity scans; quantity filtering applies
            # after selected days are hydrated from their day catalog and one representative scan.
            items = [
                item
                for item in items
                if not item.quantities or quantity in item.quantities
            ]
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
            key = str(
                item.root_attrs.get("catalog_key")
                or item.root_attrs.get("uk_wsr:pvol_day_catalog_key")
                or ""
            )
            if not key:
                return None
            try:
                day = pvol_day_catalog(key)
                return pvol_item_from_day_catalog(
                    pvol_root(),
                    item,
                    day,
                    pvol_public_base(),
                    pvol_field_index(key, day),
                )
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
            if (
                candidate.radar == item.radar
                and candidate.date == item.date
                and candidate.source_type == "raw_volume_day"
            ):
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
            if (
                _raw_volume_item_has_files(item)
                or (
                    item.source_type != "raw_volume_day"
                    and item_has_time_metadata(item)
                )
                or raw_volume_day_catalog_exists(item.radar, item.date)
            ):
                return item.date
        return None

    def latest_plot_ready_date(items: list[CatalogItem]) -> str | None:
        for item in sorted(items, key=lambda candidate: candidate.date, reverse=True):
            if (
                _raw_volume_item_has_files(item)
                or (
                    item.source_type != "raw_volume_day"
                    and item_has_time_metadata(item)
                )
                or raw_volume_day_catalog_exists(item.radar, item.date)
            ):
                return item.date
        return None

    def populate_raw_volume_metadata(item: CatalogItem) -> CatalogItem:
        """Inspect one cached scan per pulse so the UI can list fields/elevations without parsing every file."""

        if (
            item.source_type != "raw_volume_day"
            or not item.raw_volumes
            or item.quantity_records
        ):
            return item
        records: list[QuantityRecord] = []
        root_attrs = dict(item.root_attrs)
        quantities_by_pulse: dict[str, list[str]] = {}
        by_pulse: dict[str, list[object]] = {}
        for volume in item.raw_volumes:
            by_pulse.setdefault(volume.pulse, []).append(volume)
        for pulse, volumes in by_pulse.items():
            first = min(volumes, key=lambda volume: volume.time)
            template_records = None
            scanned_attrs: dict[str, object] = {}
            for _attempt in range(2):
                try:
                    source = ensure_raw_volume_cached(
                        item,
                        first,
                        settings.remote_aggregate_cache_dir,
                        settings.object_store_external_base,
                        max_age_seconds=settings.remote_cache_ttl_seconds,
                        max_bytes=settings.remote_cache_max_bytes,
                    )
                    (
                        _radar,
                        _radar_num,
                        _date,
                        _scanned_volume,
                        template_records,
                        scanned_attrs,
                    ) = scan_raw_volume(
                        source,
                        settings.remote_aggregate_cache_dir,
                        settings.object_store_external_base,
                    )
                    break
                except Exception:
                    continue
            if template_records is None:
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
            if (
                scanned_attrs.get("uk_wsr:spatial")
                and "uk_wsr:spatial" not in root_attrs
            ):
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
        cached_item = hydrated_items.get(item_key)
        if cached_item is not None and _raw_volume_item_has_files(cached_item):
            if cached_item.quantity_records:
                return cached_item
            hydrated_item = populate_raw_volume_metadata(cached_item)
            hydrated_items[item_key] = hydrated_item
            return hydrated_item
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
            size_gb = item.file_size / (1024**3)
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
            raise HTTPException(
                status_code=400,
                detail=f"raw aggregate unavailable: {type(exc).__name__}: {exc}",
            ) from exc
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
            path = cached_raw_volume_path(
                item, volume, settings.remote_aggregate_cache_dir
            )
            return path.exists() and (
                volume.file_size <= 0 or path.stat().st_size == volume.file_size
            )
        except Exception:
            return False

    def queue_raw_volume_prefetch(
        item: CatalogItem, pulse: str, time: str
    ) -> dict[str, object]:
        volume = item.raw_volume_for(pulse, time)
        if volume is None:
            raise HTTPException(
                status_code=404,
                detail=f"no raw-volume file for pulse={pulse} time={time}",
            )
        cache_path = cached_raw_volume_path(
            item, volume, settings.remote_aggregate_cache_dir
        )
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
            return {
                "status": "queued",
                "pulse": pulse,
                "time": time,
                "cache_path": str(cache_path),
            }

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
        return {
            "status": "queued",
            "pulse": pulse,
            "time": time,
            "cache_path": str(cache_path),
        }

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
            metadata_objects = [
                obj
                for obj in manifest.objects
                if obj.kind == "dataset_metadata" and Path(obj.source_path).exists()
            ]
            if metadata_objects:
                import json

                return json.loads(
                    Path(metadata_objects[0].source_path).read_text(encoding="utf-8")
                )
        return public_dataset_metadata_payload(
            catalog(),
            settings.object_store_external_base,
            "uk-radar",
            {
                "title": "UK WSR per-volume PVOL HDF5",
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
            spatial = (
                item.root_attrs.get("uk_wsr:spatial")
                if isinstance(item.root_attrs, dict)
                else None
            )
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
        additional_qc: dict[str, object] | None = None,
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
        pairs.update(additional_qc or {})
        return {key: value for key, value in pairs.items() if value is not None}

    def sampled_gate_edges(
        metadata, row_stride: int, column_stride: int, rows: int, columns: int
    ) -> dict[str, list[float]]:
        azimuth_edges = [
            (min(index * row_stride, metadata.nrays) / max(metadata.nrays, 1)) * 360.0
            for index in range(rows + 1)
        ]
        range_edges = [
            metadata.rstart_km * 1000.0
            + min(index * column_stride, metadata.nbins) * metadata.rscale_m
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
            "server_started_at": server_started_at,
            "catalog_source_id": active_catalog_source_id,
            "catalog_source": catalog_source_label(),
            "catalog_type": "pvol" if using_pvol_catalog() else "inventory",
        }

    @app.get("/api/catalog-sources")
    def available_catalog_sources():
        """Describe the archive eras that the local desktop viewer can select."""

        return {
            "selected": active_catalog_source_id,
            "sources": [
                {
                    "id": source["id"],
                    "label": source["label"],
                    "description": source["description"],
                    "catalog_url": source["catalog_url"],
                    "configured": bool(source["catalog_url"]),
                }
                for source in catalog_sources.values()
            ],
        }

    @app.post("/api/catalog-sources/select")
    def select_catalog_source(request: dict[str, object]):
        """Switch the local desktop viewer to a separate source-era catalog."""

        nonlocal active_catalog_source_id
        source_id = str(request.get("source") or "")
        if source_id not in catalog_sources:
            raise HTTPException(status_code=400, detail="unknown catalog source")
        if not catalog_sources[source_id]["catalog_url"]:
            raise HTTPException(
                status_code=409,
                detail=f"{catalog_sources[source_id]['label']} has no configured catalog URL",
            )
        if source_id != active_catalog_source_id:
            active_catalog_source_id = source_id
            reset_catalog_caches()
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "select catalog source",
                    "catalog_source_id": source_id,
                    "catalog_source": catalog_source_label(),
                }
            )
        return {
            "ok": True,
            "selected": active_catalog_source_id,
            "source": active_catalog_source(),
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
            "startup_ready": True,
            "server_started_at": server_started_at,
            "catalog_path": str(settings.catalog_path),
            "catalog_source_id": active_catalog_source_id,
            "catalog_source": catalog_source_label(),
            "remote_catalog_url": active_remote_catalog_url(),
            "object_store_external_base": settings.object_store_external_base,
            "remote_catalog": using_remote_catalog(),
            "catalog_type": "pvol" if using_pvol_catalog() else "inventory",
            "item_count": item_count,
            "catalog_error": catalog_error,
            "last_catalog_error": catalog_error,
            "data_dir": str(settings.data_dir),
            "http_json_cache_dir": str(http_json_cache_dir),
            "cache": cache_state(),
            "raw_cache_dir": str(settings.remote_aggregate_cache_dir),
            "raw_cache_ttl_seconds": settings.remote_cache_ttl_seconds,
            "raw_cache_max_bytes": settings.remote_cache_max_bytes,
            "deployment_target": "configured deployment target",
        }

    @app.get("/api/startup-diagnostics")
    def startup_diagnostics():
        return {
            "ok": True,
            "ready": ready(),
            "status": status(),
            "performance_event_count": len(performance_events),
            "cache": cache_state(),
        }

    @app.get("/api/performance")
    def performance_report(limit: int = 120):
        """Return recent server-side timing events for local diagnostics."""

        bounded_limit = max(1, min(int(limit), 400))
        return {
            "ok": True,
            "event_count": len(performance_events),
            "events": list(performance_events)[-bounded_limit:],
            "cache": cache_state(),
        }

    @app.post("/api/performance/clear")
    def clear_performance_report():
        performance_events.clear()
        return {"ok": True, "event_count": 0}

    @app.get("/api/citation")
    def citation():
        return citation_payload()

    register_catalog_routes(
        app,
        active_remote_catalog_url=active_remote_catalog_url,
        catalog=catalog,
        catalog_radar_records=catalog_radar_records,
        find_item=find_item,
        first_plot_ready_date=first_plot_ready_date,
        hydrate_item=hydrate_item,
        hydrated_items=hydrated_items,
        latest_plot_ready_date=latest_plot_ready_date,
        local_dataset_payload=local_dataset_payload,
        prune_cache=prune_cache,
        pvol_root=pvol_root,
        pvol_search_items=pvol_search_items,
        queue_raw_volume_prefetch=queue_raw_volume_prefetch,
        raw_volume_cached=raw_volume_cached,
        record_performance_event=record_performance_event,
        settings=settings,
        using_pvol_catalog=using_pvol_catalog,
    )

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
                available = sorted(
                    {
                        f"{candidate.pulse} {candidate.time}"
                        for candidate in item.raw_volumes
                    }
                )
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
                raise HTTPException(
                    status_code=400,
                    detail=f"raw-volume unavailable: {type(exc).__name__}: {exc}",
                ) from exc
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

    def export_source_for_time(
        item: CatalogItem, request: ExportRequest, time: str
    ) -> Path:
        if item.source_type != "raw_volume_day":
            return Path(item.path)
        volume = item.raw_volume_for(request.pulse or "", time)
        if volume is None:
            available = sorted(
                {
                    f"{candidate.pulse} {candidate.time}"
                    for candidate in item.raw_volumes
                }
            )
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

    register_render_routes(
        app,
        cached_ppi_response=cached_ppi_response,
        export_source_for_time=export_source_for_time,
        find_item=find_item,
        hydrate_item=hydrate_item,
        preview_request=preview_request,
        radar_filters=radar_filters,
        record_performance_event=record_performance_event,
        sampled_gate_edges=sampled_gate_edges,
        store_ppi_response=store_ppi_response,
    )

    register_export_routes(
        app,
        export_source_for_time=export_source_for_time,
        find_item=find_item,
        hydrate_item=hydrate_item,
        settings=settings,
    )

    register_session_routes(app, settings=settings)

    return app


app = create_app()
