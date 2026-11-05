"""Catalogue, local-cache and source-object API routes."""

from __future__ import annotations

import time as time_module
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from ..catalog import (
    catalog_summary,
    filter_catalog,
    pvol_catalog_summary,
    pvol_radar_records,
)
from ..freshness import build_freshness_report
from ..object_store import join_object_url
from ..object_store_manifest import load_plan, public_landing_html
from ..recent import (
    clear_recent_selections,
    load_recent_selections,
    record_recent_selection,
)
from ..remote_cache import clear_raw_cache, raw_cache_status
from ..stac import (
    AGGREGATE_COLLECTION_ID,
    collection_to_stac,
    item_to_stac,
    root_catalog_to_stac,
)
from .support import _elapsed_ms, _item_payload, _timed_step


def register_catalog_routes(
    app,
    *,
    active_remote_catalog_url,
    catalog,
    catalog_radar_records,
    find_item,
    first_plot_ready_date,
    hydrate_item,
    hydrated_items,
    latest_plot_ready_date,
    local_dataset_payload,
    prune_cache,
    pvol_root,
    pvol_search_items,
    queue_raw_volume_prefetch,
    raw_volume_cached,
    record_performance_event,
    settings,
    using_pvol_catalog,
):
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
        matches = (
            pvol_search_items(radar, start, end, pulse, quantity)
            if using_pvol_catalog()
            else filter_catalog(catalog(), radar, start, end, pulse, quantity)
        )
        return {"items": [_item_payload(item) for item in matches]}

    @app.get("/api/catalog/summary")
    def summary():
        return (
            pvol_catalog_summary(pvol_root())
            if using_pvol_catalog()
            else catalog_summary(catalog())
        )

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
                "catalog_url": join_object_url(
                    settings.object_store_external_base, key
                ),
                "catalog_type": "pvol",
                "summary": pvol_catalog_summary(pvol_root()),
                "radars": pvol_radar_records(pvol_root()),
            }
        return {
            "catalog_key": "uk-radar/catalog/inventory/catalog.json",
            "catalog_url": join_object_url(
                settings.object_store_external_base,
                "uk-radar/catalog/inventory/catalog.json",
            ),
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
        return root_catalog_to_stac(
            catalog(), public_base_url=settings.object_store_external_base
        )

    @app.get("/api/stac/collections/{collection_id}")
    def stac_collection(collection_id: str):
        if collection_id != AGGREGATE_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="STAC collection not found")
        return collection_to_stac(
            catalog(), public_base_url=settings.object_store_external_base
        )

    @app.get("/api/stac/collections/{collection_id}/items/{item_id}")
    def stac_item(collection_id: str, item_id: str):
        if collection_id != AGGREGATE_COLLECTION_ID:
            raise HTTPException(status_code=404, detail="STAC collection not found")
        for entry in catalog():
            if entry.item_id == item_id:
                return item_to_stac(
                    entry, public_base_url=settings.object_store_external_base
                )
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
            raise HTTPException(
                status_code=404, detail="object-store manifest not found"
            )
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
                            "catalog_source": active_remote_catalog_url(),
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
                    "ok": all(
                        check["ok"] or check["severity"] == "warning"
                        for check in checks
                    ),
                    "created_at": build_freshness_report(
                        catalog_path=settings.catalog_path,
                        object_store_manifest_path=settings.object_store_manifest_path,
                    ).created_at,
                    "catalog_path": str(settings.catalog_path),
                    "catalog_source": active_remote_catalog_url(),
                    "remote_catalog": True,
                    "object_store_manifest_path": str(
                        settings.object_store_manifest_path
                    ),
                    "checks": checks,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "catalog_path": str(settings.catalog_path),
                    "catalog_source": active_remote_catalog_url(),
                    "remote_catalog": True,
                    "object_store_manifest_path": str(
                        settings.object_store_manifest_path
                    ),
                    "checks": [
                        {
                            "name": "remote_catalog_loaded",
                            "ok": False,
                            "severity": "critical",
                            "message": f"remote PVOL catalog unavailable: {type(exc).__name__}: {exc}",
                            "details": {"catalog_source": active_remote_catalog_url()},
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
                "field_index_loaded": bool(
                    hydrated.root_attrs.get("field_index_loaded")
                ),
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
            "external_url": item.object_url
            or join_object_url(settings.object_store_external_base, item.object_key),
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
