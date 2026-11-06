"""FastAPI app for the UK WSR Visualizer."""

from __future__ import annotations

import time as time_module
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from .. import __version__
from .catalog_service import CatalogService

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
    pvol_catalog_summary,
)
from ..citations import citation_payload
from ..config import Settings
from ..export import ExportRequest
from ..preview import PreviewRequest
from ..remote_cache import (
    ensure_raw_volume_cached,
)
from .catalog_routes import register_catalog_routes
from .export_routes import register_export_routes
from .render_routes import register_render_routes
from .session_routes import register_session_routes
from .support import LOCAL_DOWNLOAD_LIMIT_BYTES as LOCAL_DOWNLOAD_LIMIT_BYTES
from .support import QCQueryParameters as QCQueryParameters
from .support import (
    _elapsed_ms,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local API and static viewer application."""

    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            catalogue.close()

    app = FastAPI(title="UK WSR Visualizer", version=__version__, lifespan=lifespan)
    server_started_at = time_module.strftime("%Y-%m-%dT%H:%M:%SZ", time_module.gmtime())
    static_dir = Path(__file__).resolve().parents[1] / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    ppi_response_cache: dict[str, dict[str, object]] = {}
    ppi_response_cache_order: list[str] = []
    max_ppi_response_cache_entries = 32
    performance_events: deque[dict[str, object]] = deque(maxlen=400)

    def record_performance_event(event: dict[str, object]) -> None:
        payload = {
            "created_at": time_module.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time_module.gmtime()
            ),
            **event,
        }
        performance_events.append(payload)

    catalogue = CatalogService(settings, record_performance_event)
    app.state.catalog_service = catalogue

    def cache_state() -> dict[str, int]:
        return {
            "hydrated_items": len(catalogue.hydrated_items),
            "pvol_coverages": len(catalogue.pvol_coverage_cache),
            "pvol_day_catalogs": len(catalogue.pvol_day_cache),
            "pvol_field_indexes": len(catalogue.pvol_field_index_cache),
            "ppi_frames": len(ppi_response_cache),
            "raw_prefetch_jobs": len(catalogue.raw_prefetch_jobs),
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

    record_performance_event(
        {
            "kind": "startup",
            "operation": "api create_app",
            "server_started_at": server_started_at,
            "catalog_source": catalogue.catalog_source_label(),
            "remote_catalog": catalogue.using_remote_catalog(),
        }
    )

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
            "catalog_source_id": catalogue.active_catalog_source_id,
            "catalog_source": catalogue.catalog_source_label(),
            "catalog_type": "pvol" if catalogue.using_pvol_catalog() else "inventory",
        }

    @app.get("/api/catalog-sources")
    def available_catalog_sources():
        """Describe the archive eras that the local desktop viewer can select."""

        return {
            "selected": catalogue.active_catalog_source_id,
            "sources": [
                {
                    "id": source["id"],
                    "label": source["label"],
                    "description": source["description"],
                    "catalog_url": source["catalog_url"],
                    "configured": bool(source["catalog_url"]),
                }
                for source in catalogue.catalog_sources.values()
            ],
        }

    @app.post("/api/catalog-sources/select")
    def select_catalog_source(request: dict[str, object]):
        """Switch the local desktop viewer to a separate source-era catalog."""

        source_id = str(request.get("source") or "")
        if source_id not in catalogue.catalog_sources:
            raise HTTPException(status_code=400, detail="unknown catalog source")
        if not catalogue.catalog_sources[source_id]["catalog_url"]:
            raise HTTPException(
                status_code=409,
                detail=f"{catalogue.catalog_sources[source_id]['label']} has no configured catalog URL",
            )
        if source_id != catalogue.active_catalog_source_id:
            catalogue.active_catalog_source_id = source_id
            catalogue.reset_catalog_caches()
            ppi_response_cache.clear()
            ppi_response_cache_order.clear()
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "select catalog source",
                    "catalog_source_id": source_id,
                    "catalog_source": catalogue.catalog_source_label(),
                }
            )
        return {
            "ok": True,
            "selected": catalogue.active_catalog_source_id,
            "source": catalogue.active_catalog_source(),
        }

    @app.get("/api/status")
    def status():
        catalog_error = ""
        item_count = 0
        try:
            if catalogue.using_pvol_catalog():
                item_count = int(
                    pvol_catalog_summary(catalogue.pvol_root())["item_count"]
                )
            else:
                item_count = len(catalogue.catalog())
        except HTTPException as exc:
            catalog_error = str(exc.detail)
        except Exception as exc:
            catalog_error = str(exc)
        return {
            "ok": not catalog_error,
            "startup_ready": True,
            "server_started_at": server_started_at,
            "catalog_path": str(settings.catalog_path),
            "catalog_source_id": catalogue.active_catalog_source_id,
            "catalog_source": catalogue.catalog_source_label(),
            "remote_catalog_url": catalogue.active_remote_catalog_url(),
            "object_store_external_base": settings.object_store_external_base,
            "remote_catalog": catalogue.using_remote_catalog(),
            "catalog_type": "pvol" if catalogue.using_pvol_catalog() else "inventory",
            "item_count": item_count,
            "catalog_error": catalog_error,
            "last_catalog_error": catalog_error,
            "data_dir": str(settings.data_dir),
            "http_json_cache_dir": str(catalogue.http_json_cache_dir),
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
        app, catalogue=catalogue, record_performance_event=record_performance_event
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
                item = catalogue.hydrate_item(item)
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
        find_item=catalogue.find_item,
        hydrate_item=catalogue.hydrate_item,
        preview_request=preview_request,
        radar_filters=radar_filters,
        record_performance_event=record_performance_event,
        sampled_gate_edges=sampled_gate_edges,
        store_ppi_response=store_ppi_response,
    )

    register_export_routes(
        app,
        export_source_for_time=export_source_for_time,
        find_item=catalogue.find_item,
        hydrate_item=catalogue.hydrate_item,
        settings=settings,
    )

    register_session_routes(app, settings=settings)

    return app


app = create_app()
