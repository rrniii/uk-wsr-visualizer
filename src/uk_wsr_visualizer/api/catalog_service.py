"""Lazy catalogue discovery and local source-file caching."""

from __future__ import annotations

import time as time_module
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

from fastapi import HTTPException

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
    pvol_coverage_keys,
    pvol_item_from_day_catalog,
    pvol_items_from_coverage,
    pvol_radar_records,
    scan_raw_volume,
)
from ..config import Settings
from ..http_cache import load_json_cached
from ..object_store import join_object_url
from ..object_store_manifest import load_plan, public_dataset_metadata_payload
from ..radars import radar_records
from ..remote_cache import (
    cached_raw_volume_path,
    ensure_raw_volume_cached,
    hydrate_item_from_raw_aggregate,
    prune_raw_cache,
)
from .support import (
    PLOT_METADATA_DOWNLOAD_LIMIT_BYTES,
    _elapsed_ms,
    _raw_volume_item_has_files,
)


class CatalogService:
    """Keep archive-era metadata and hydration state together."""

    def __init__(
        self,
        settings: Settings,
        record_performance_event: Callable[[dict[str, object]], None],
    ):
        self.settings = settings
        self.record_performance_event = record_performance_event
        self.hydrated_items: dict[str, CatalogItem] = {}
        self.raw_volume_catalog_exists_cache: dict[tuple[str, str], bool] = {}
        self.pvol_root_cache: dict[str, object] | None = None
        self.pvol_coverage_cache: dict[str, dict[str, object]] = {}
        self.pvol_day_cache: dict[str, dict[str, object]] = {}
        self.pvol_field_index_cache: dict[str, dict[str, object] | None] = {}
        self.http_json_cache_dir = settings.data_dir / "http-json-cache"
        self.raw_prefetch_pool = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="uk-wsr-raw-prefetch"
        )
        self.raw_prefetch_jobs: dict[str, Future[str]] = {}
        self.catalog_sources = {
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
        self.active_catalog_source_id = "dual-pol"

    def close(self) -> None:
        self.raw_prefetch_pool.shutdown(wait=False, cancel_futures=True)

    def active_catalog_source(self) -> dict[str, str]:
        return self.catalog_sources[self.active_catalog_source_id]

    def active_remote_catalog_url(self) -> str:
        return self.active_catalog_source()["catalog_url"]

    def reset_catalog_caches(self) -> None:
        """Discard source-specific metadata when the user switches archive era."""

        self.hydrated_items.clear()
        self.raw_volume_catalog_exists_cache.clear()
        self.pvol_root_cache = None
        self.pvol_coverage_cache.clear()
        self.pvol_day_cache.clear()
        self.pvol_field_index_cache.clear()

    def catalog(self) -> list[CatalogItem]:
        try:
            return load_catalog_source(
                self.settings.catalog_path, self.active_remote_catalog_url()
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail=f"catalog unavailable: {exc}"
            ) from exc

    def using_remote_catalog(self) -> bool:
        # The configured local catalog remains a compatibility override for the
        # default source only. A selected pre-dual archive must never silently
        # fall back to a local dual-pol catalog with the same radar/date keys.
        return bool(self.active_remote_catalog_url()) and (
            self.active_catalog_source_id != "dual-pol"
            or not self.settings.catalog_path.exists()
        )

    def using_pvol_catalog(self) -> bool:
        return self.using_remote_catalog() and catalog_url_is_pvol_root(
            self.active_remote_catalog_url()
        )

    def catalog_source_label(self) -> str:
        return (
            self.active_remote_catalog_url()
            if self.using_remote_catalog()
            else str(self.settings.catalog_path)
        )

    def load_json_url(self, url: str, timeout_s: float = 30.0) -> dict[str, object]:
        return load_json_cached(url, self.http_json_cache_dir, timeout_s=timeout_s)

    def pvol_public_base(self) -> str:
        return (
            self.settings.object_store_external_base
            or catalog_public_base_from_root_url(self.active_remote_catalog_url())
        )

    def pvol_root(self) -> dict[str, object]:
        if self.pvol_root_cache is None:
            self.pvol_root_cache = self.load_json_url(self.active_remote_catalog_url())
        return self.pvol_root_cache

    def pvol_coverage(self, key: str) -> dict[str, object]:
        if key not in self.pvol_coverage_cache:
            self.pvol_coverage_cache[key] = self.load_json_url(
                join_catalog_url(self.pvol_public_base(), key), timeout_s=30.0
            )
        return self.pvol_coverage_cache[key]

    def pvol_day_catalog(self, key: str) -> dict[str, object]:
        if key not in self.pvol_day_cache:
            self.pvol_day_cache[key] = self.load_json_url(
                join_catalog_url(self.pvol_public_base(), key), timeout_s=30.0
            )
        return self.pvol_day_cache[key]

    def pvol_field_index(
        self, key: str, day: dict[str, object]
    ) -> dict[str, object] | None:
        candidates: list[str] = []
        explicit_url = str(day.get("field_index_url") or "")
        explicit_key = str(
            day.get("field_index_key") or day.get("field-index_key") or ""
        )
        if explicit_url:
            candidates.append(explicit_url)
        if explicit_key:
            candidates.append(join_catalog_url(self.pvol_public_base(), explicit_key))
        if key.endswith("/catalog.json"):
            base = key[: -len("catalog.json")]
            candidates.extend(
                [
                    join_catalog_url(
                        self.pvol_public_base(), f"{base}field-index.json"
                    ),
                    join_catalog_url(
                        self.pvol_public_base(), f"{base}field_index.json"
                    ),
                ]
            )
        for url in dict.fromkeys(candidates):
            if url not in self.pvol_field_index_cache:
                try:
                    self.pvol_field_index_cache[url] = self.load_json_url(
                        url, timeout_s=12.0
                    )
                except Exception:
                    self.pvol_field_index_cache[url] = None
            cached = self.pvol_field_index_cache[url]
            if isinstance(cached, dict) and isinstance(cached.get("files"), list):
                return cached
        return None

    def pvol_latest_items_from_root(self) -> list[CatalogItem]:
        root = self.pvol_root()
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
                    root, radar_entry, {"days": [day]}, self.pvol_public_base()
                )[0]
            )
        return sorted(items, key=lambda item: (item.radar, item.date))

    def pvol_search_items(
        self,
        radar: str | None = None,
        start: str | None = None,
        end: str | None = None,
        pulse: str | None = None,
        quantity: str | None = None,
    ) -> list[CatalogItem]:
        root = self.pvol_root()
        if not radar and not start and not end:
            items = self.pvol_latest_items_from_root()
        else:
            items = []
            for radar_entry, key in pvol_coverage_keys(
                root, radar=radar, start=start, end=end
            ):
                items.extend(
                    pvol_items_from_coverage(
                        root,
                        radar_entry,
                        self.pvol_coverage(key),
                        self.pvol_public_base(),
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

    def find_item(self, radar: str, date: str) -> CatalogItem:
        item_key = f"{radar}:{date}"
        if item_key in self.hydrated_items:
            return self.hydrated_items[item_key]
        if self.using_pvol_catalog():
            for item in self.pvol_search_items(radar=radar, start=date, end=date):
                if item.radar == radar and item.date == date:
                    return item
            raise HTTPException(status_code=404, detail="catalog item not found")
        for item in self.catalog():
            if item.radar == radar and item.date == date:
                return item
        raise HTTPException(status_code=404, detail="catalog item not found")

    def raw_volume_day_catalog_item(self, item: CatalogItem) -> CatalogItem | None:
        if self.using_pvol_catalog():
            key = str(
                item.root_attrs.get("catalog_key")
                or item.root_attrs.get("uk_wsr:pvol_day_catalog_key")
                or ""
            )
            if not key:
                return None
            try:
                day = self.pvol_day_catalog(key)
                return pvol_item_from_day_catalog(
                    self.pvol_root(),
                    item,
                    day,
                    self.pvol_public_base(),
                    self.pvol_field_index(key, day),
                )
            except Exception:
                return None
        if not self.settings.object_store_external_base:
            return None
        url = self.raw_volume_day_catalog_url(item.radar, item.date)
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

    def raw_volume_day_catalog_url(self, radar: str, date: str) -> str:
        key = f"uk-radar/catalog/inventory/raw-volume/{radar}/{date[:4]}/{date}/catalog.json"
        return join_object_url(self.settings.object_store_external_base, key)

    def raw_volume_day_catalog_exists(self, radar: str, date: str) -> bool:
        if not self.settings.object_store_external_base:
            return False
        cache_key = (radar, date)
        if cache_key in self.raw_volume_catalog_exists_cache:
            return self.raw_volume_catalog_exists_cache[cache_key]
        try:
            request = Request(
                self.raw_volume_day_catalog_url(radar, date), method="HEAD"
            )
            with urlopen(request, timeout=0.75) as response:
                exists = 200 <= response.status < 300
        except Exception:
            exists = False
        self.raw_volume_catalog_exists_cache[cache_key] = exists
        return exists

    def item_has_time_metadata(self, item: CatalogItem) -> bool:
        if item.source_type == "raw_volume_day":
            return _raw_volume_item_has_files(item)
        if item.quantity_records:
            return True
        if item.times:
            return True
        return any(times for times in item.times_by_pulse.values())

    def first_plot_ready_date(self, items: list[CatalogItem]) -> str | None:
        for item in sorted(items, key=lambda candidate: candidate.date):
            if (
                _raw_volume_item_has_files(item)
                or (
                    item.source_type != "raw_volume_day"
                    and self.item_has_time_metadata(item)
                )
                or self.raw_volume_day_catalog_exists(item.radar, item.date)
            ):
                return item.date
        return None

    def latest_plot_ready_date(self, items: list[CatalogItem]) -> str | None:
        for item in sorted(items, key=lambda candidate: candidate.date, reverse=True):
            if (
                _raw_volume_item_has_files(item)
                or (
                    item.source_type != "raw_volume_day"
                    and self.item_has_time_metadata(item)
                )
                or self.raw_volume_day_catalog_exists(item.radar, item.date)
            ):
                return item.date
        return None

    def populate_raw_volume_metadata(self, item: CatalogItem) -> CatalogItem:
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
                        self.settings.remote_aggregate_cache_dir,
                        self.settings.object_store_external_base,
                        max_age_seconds=self.settings.remote_cache_ttl_seconds,
                        max_bytes=self.settings.remote_cache_max_bytes,
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
                        self.settings.remote_aggregate_cache_dir,
                        self.settings.object_store_external_base,
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

    def hydrate_item(self, item: CatalogItem) -> CatalogItem:
        """Resolve a catalog day to a plot-ready raw-volume source when possible."""

        item_key = f"{item.radar}:{item.date}"
        cached_item = self.hydrated_items.get(item_key)
        if cached_item is not None and _raw_volume_item_has_files(cached_item):
            if cached_item.quantity_records:
                return cached_item
            hydrated_item = self.populate_raw_volume_metadata(cached_item)
            self.hydrated_items[item_key] = hydrated_item
            return hydrated_item
        if _raw_volume_item_has_files(item):
            hydrated = self.populate_raw_volume_metadata(item)
            self.hydrated_items[item_key] = hydrated
            return hydrated
        raw_volume_item = self.raw_volume_day_catalog_item(item)
        if raw_volume_item is not None and _raw_volume_item_has_files(raw_volume_item):
            hydrated = self.populate_raw_volume_metadata(raw_volume_item)
            self.hydrated_items[item_key] = hydrated
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
                self.settings.remote_aggregate_cache_dir,
                self.settings.object_store_external_base,
                max_age_seconds=self.settings.remote_cache_ttl_seconds,
                max_bytes=self.settings.remote_cache_max_bytes,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"raw aggregate unavailable: {type(exc).__name__}: {exc}",
            ) from exc
        self.hydrated_items[item_key] = hydrated
        return hydrated

    def prune_cache(self) -> dict[str, object]:
        removed = prune_raw_cache(
            self.settings.remote_aggregate_cache_dir,
            max_age_seconds=self.settings.remote_cache_ttl_seconds,
            max_bytes=self.settings.remote_cache_max_bytes,
        )
        for key, hydrated in list(self.hydrated_items.items()):
            if not Path(hydrated.path).exists():
                self.hydrated_items.pop(key, None)
        return removed

    def raw_volume_cached(
        self, item: CatalogItem, volume: RawVolumeRecord | None
    ) -> bool:
        if volume is None:
            return False
        try:
            path = cached_raw_volume_path(
                item, volume, self.settings.remote_aggregate_cache_dir
            )
            return path.exists() and (
                volume.file_size <= 0 or path.stat().st_size == volume.file_size
            )
        except Exception:
            return False

    def queue_raw_volume_prefetch(
        self, item: CatalogItem, pulse: str, time: str
    ) -> dict[str, object]:
        volume = item.raw_volume_for(pulse, time)
        if volume is None:
            raise HTTPException(
                status_code=404,
                detail=f"no raw-volume file for pulse={pulse} time={time}",
            )
        cache_path = cached_raw_volume_path(
            item, volume, self.settings.remote_aggregate_cache_dir
        )
        if self.raw_volume_cached(item, volume):
            self.record_performance_event(
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
        existing = self.raw_prefetch_jobs.get(key)
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
                    self.settings.remote_aggregate_cache_dir,
                    self.settings.object_store_external_base,
                    max_age_seconds=self.settings.remote_cache_ttl_seconds,
                    max_bytes=self.settings.remote_cache_max_bytes,
                )
                self.record_performance_event(
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
                self.record_performance_event(
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

        self.raw_prefetch_jobs[key] = self.raw_prefetch_pool.submit(download)
        return {
            "status": "queued",
            "pulse": pulse,
            "time": time,
            "cache_path": str(cache_path),
        }

    def local_dataset_payload(self) -> dict[str, object]:
        manifest_path = self.settings.object_store_manifest_path
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
            self.catalog(),
            self.settings.object_store_external_base,
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

    def catalog_radar_records(self) -> list[dict[str, object]]:
        if self.using_pvol_catalog():
            return pvol_radar_records(self.pvol_root())
        records = {str(record["slug"]): dict(record) for record in radar_records()}
        for item in self.catalog():
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
