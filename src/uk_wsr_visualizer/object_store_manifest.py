"""Publication plan and manifest records for object-store distribution."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .catalog import CatalogItem
from .compat import UTC
from .object_store import (
    aggregate_object_key,
    catalog_inventory_object_key,
    checksum_object_key,
    export_product_object_key,
    join_object_url,
    public_status_object_key,
    public_dataset_metadata_object_key,
    public_landing_object_key,
    raw_volume_object_key,
    stac_catalog_object_key,
    stac_collection_object_key,
    stac_object_key,
    validation_report_object_key,
)
from .object_store_config import ObjectStoreConfig
from .stac import AGGREGATE_COLLECTION_ID, collection_to_stac, item_to_stac, root_catalog_to_stac


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_sha256_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = payload.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def _write_sha256_cache(path: Path | None, entries: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "entries": entries}, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sha256_file_cached(path: Path, cache: dict[str, Any] | None = None, cache_path: Path | None = None) -> str:
    if cache is None:
        return sha256_file(path)
    stat = path.stat()
    key = str(path.resolve())
    entry = cache.get(key)
    if (
        isinstance(entry, dict)
        and entry.get("size") == stat.st_size
        and entry.get("mtime_ns") == stat.st_mtime_ns
        and isinstance(entry.get("sha256"), str)
    ):
        return str(entry["sha256"])
    digest = sha256_file(path)
    cache[key] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
    _write_sha256_cache(cache_path, cache)
    return digest


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass
class PublicationObject:
    kind: str
    bucket: str
    key: str
    source_path: str
    size: int
    sha256: str
    content_type: str
    public_url: str
    status: str = "planned"
    message: str = ""
    uploaded_at: str = ""
    verified_at: str = ""


@dataclass
class PublicationPlan:
    version: int
    run_id: str
    created_at: str
    bucket: str
    staging_bucket: str
    object_prefix: str
    public_base_url: str
    objects: list[PublicationObject] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PublicationPlan":
        objects = [PublicationObject(**entry) for entry in payload.get("objects", [])]
        return cls(
            version=int(payload.get("version", 1)),
            run_id=str(payload["run_id"]),
            created_at=str(payload["created_at"]),
            bucket=str(payload["bucket"]),
            staging_bucket=str(payload.get("staging_bucket", "")),
            object_prefix=str(payload["object_prefix"]),
            public_base_url=str(payload.get("public_base_url", "")),
            objects=objects,
        )

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for obj in self.objects:
            by_status[obj.status] = by_status.get(obj.status, 0) + 1
            by_kind[obj.kind] = by_kind.get(obj.kind, 0) + 1
        return {
            "run_id": self.run_id,
            "object_count": len(self.objects),
            "byte_count": sum(obj.size for obj in self.objects),
            "by_status": by_status,
            "by_kind": by_kind,
        }


def write_plan(path: Path, plan: PublicationPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def load_plan(path: Path) -> PublicationPlan:
    return PublicationPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _content_type(path: Path, kind: str) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".png":
        return "image/png"
    if suffix in {".h5", ".hdf5"}:
        return "application/x-hdf5"
    if suffix == ".tif" or suffix == ".tiff":
        return "image/tiff"
    if suffix == ".kmz":
        return "application/vnd.google-earth.kmz"
    if suffix == ".zip":
        return "application/zip"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".nc":
        return "application/x-netcdf"
    if suffix == ".geojson":
        return "application/geo+json"
    if suffix == ".xml":
        return "application/xml"
    if kind == "catalog":
        return "application/json"
    return "application/octet-stream"


def _object_from_file(
    kind: str,
    bucket: str,
    key: str,
    source_path: Path,
    public_base_url: str,
    sha256_cache: dict[str, Any] | None = None,
    sha256_cache_path: Path | None = None,
) -> PublicationObject:
    return PublicationObject(
        kind=kind,
        bucket=bucket,
        key=key,
        source_path=str(source_path),
        size=source_path.stat().st_size,
        sha256=sha256_file_cached(source_path, sha256_cache, sha256_cache_path),
        content_type=_content_type(source_path, kind),
        public_url=join_object_url(public_base_url, key),
    )


def _write_generated_json(staging_dir: Path, relative_path: Path, payload: dict[str, Any]) -> Path:
    path = staging_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(payload))
    return path


def _write_generated_text(staging_dir: Path, relative_path: Path, text: str) -> Path:
    path = staging_dir / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def public_catalog_inventory_payload(items: list[CatalogItem], public_base_url: str, object_prefix: str) -> dict[str, Any]:
    public_items: list[dict[str, Any]] = []
    for item in items:
        object_key = aggregate_object_key(item.radar, item.date, object_prefix)
        public_url = item.object_url or join_object_url(public_base_url, object_key)
        public_items.append(
            {
                **asdict(item),
                "path": public_url,
                "object_key": object_key,
                "object_url": public_url,
                "private_path_redacted": True,
                "quantity_records": [asdict(record) for record in item.quantity_records],
            }
        )
    return {
        "version": 1,
        "generated_for": "public-object-store",
        "private_paths_redacted": True,
        "items": public_items,
    }


def public_dataset_metadata_payload(
    items: list[CatalogItem],
    public_base_url: str,
    object_prefix: str,
    metadata: dict[str, str],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "visualizer_uk_radar_dataset",
        "generated_at": utc_now(),
        "dataset": metadata,
        "catalog": {
            "item_count": len(items),
            "radars": sorted({item.radar for item in items}),
            "date_start": min((item.date for item in items), default=""),
            "date_end": max((item.date for item in items), default=""),
            "quantities": sorted({quantity for item in items for quantity in item.quantities}),
        },
        "links": {
            "landing": join_object_url(public_base_url, public_landing_object_key(object_prefix)),
            "status": join_object_url(public_base_url, public_status_object_key(object_prefix)),
            "inventory": join_object_url(public_base_url, catalog_inventory_object_key("catalog.json", object_prefix)),
            "stac_catalog": join_object_url(public_base_url, stac_catalog_object_key(object_prefix)),
            "stac_collection": join_object_url(
                public_base_url,
                stac_collection_object_key(AGGREGATE_COLLECTION_ID, object_prefix),
            ),
            "validation_prefix": join_object_url(public_base_url, f"{object_prefix}/validation/wct"),
        },
        "validation": validation_summary,
    }


def public_landing_html(payload: dict[str, Any]) -> str:
    dataset = payload.get("dataset", {})
    catalog = payload.get("catalog", {})
    links = payload.get("links", {})
    validation = payload.get("validation", {})

    def value(source: dict[str, Any], key: str, default: str = "") -> str:
        return html.escape(str(source.get(key, default)))

    title = value(dataset, "title", "UK WSR aggregate HDF5")
    description = value(dataset, "description")
    citation = value(dataset, "citation")
    contact = value(dataset, "contact_email")
    terms_url = value(dataset, "terms_url")
    provider = value(dataset, "provider_name")
    provider_url = value(dataset, "provider_url")
    license_value = value(dataset, "license", "proprietary")
    validation_counts = validation.get("by_parity_status", {}) if isinstance(validation, dict) else {}
    validation_text = ", ".join(f"{html.escape(str(k))}: {html.escape(str(v))}" for k, v in sorted(validation_counts.items())) or "not available"
    rows = [
        ("Item count", value(catalog, "item_count", "0")),
        ("Date range", f"{value(catalog, 'date_start')} to {value(catalog, 'date_end')}"),
        ("Radars", html.escape(", ".join(str(radar) for radar in catalog.get("radars", [])))),
        ("Quantities", html.escape(", ".join(str(quantity) for quantity in catalog.get("quantities", [])))),
        ("Licence", license_value),
        ("Provider", f'<a href="{provider_url}">{provider}</a>' if provider_url else provider),
        ("Contact", f'<a href="mailto:{contact}">{contact}</a>' if contact else ""),
        ("Citation", citation),
        ("WCT validation", validation_text),
    ]
    row_html = "\n".join(f"<tr><th>{label}</th><td>{content}</td></tr>" for label, content in rows if content)
    link_html = "\n".join(
        f'<li><a href="{html.escape(str(href))}">{html.escape(label.replace("_", " ").title())}</a></li>'
        for label, href in sorted(links.items())
        if href
    )
    terms_html = f'<p><a href="{terms_url}">Dataset terms and licence</a></p>' if terms_url else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 72rem; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #d0d7de; padding: 0.5rem; text-align: left; vertical-align: top; }}
    th {{ width: 12rem; background: #f6f8fa; }}
    code {{ background: #f6f8fa; padding: 0.1rem 0.25rem; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p>{description}</p>
  {terms_html}
  <h2>Dataset Summary</h2>
  <table>{row_html}</table>
  <h2>Public Links</h2>
  <ul>{link_html}</ul>
  <p>This page is generated by the UK WSR Visualizer publication workflow.</p>
</body>
</html>
"""


def aggregate_checksum_payload(
    items: list[CatalogItem],
    public_base_url: str,
    object_prefix: str,
    radar: str,
    year: str,
    sha256_cache: dict[str, Any] | None = None,
    sha256_cache_path: Path | None = None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: value.date):
        if item.radar != radar or item.date[:4] != year:
            continue
        source = Path(item.path)
        object_key = aggregate_object_key(item.radar, item.date, object_prefix)
        entries.append(
            {
                "radar": item.radar,
                "date": item.date,
                "object_key": object_key,
                "public_url": join_object_url(public_base_url, object_key),
                "source_size": source.stat().st_size if source.exists() else 0,
                "sha256": sha256_file_cached(source, sha256_cache, sha256_cache_path) if source.exists() else "",
                "status": "ok" if source.exists() else "missing_source",
            }
        )
    return {
        "version": 1,
        "kind": "aggregate_sha256",
        "radar": radar,
        "year": year,
        "object_count": len(entries),
        "objects": entries,
    }


def _validation_summary(validation_dir: Path | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "report_count": 0,
        "by_parity_status": {},
        "reports": [],
    }
    if validation_dir is None or not validation_dir.exists():
        return summary
    for source in sorted(validation_dir.rglob("*.json")):
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        results = payload.get("results", [])
        if not isinstance(results, list):
            continue
        statuses = []
        for result in results:
            if not isinstance(result, dict):
                continue
            status = str(result.get("parity_status", "unknown"))
            statuses.append(status)
            by_status = summary["by_parity_status"]
            by_status[status] = by_status.get(status, 0) + 1
        summary["report_count"] += 1
        summary["reports"].append(
            {
                "path": str(source.relative_to(validation_dir)),
                "created_at": payload.get("created_at", ""),
                "execute_wct": bool(payload.get("execute_wct", False)),
                "require_comparison": bool(payload.get("require_comparison", False)),
                "result_count": len(results),
                "parity_statuses": statuses,
                "ok": bool(results) and all(status == "passed" for status in statuses),
            }
        )
    return summary


def build_publication_plan(
    items: list[CatalogItem],
    catalog_path: Path,
    config: ObjectStoreConfig,
    staging_dir: Path,
    preview_dir: Path | None = None,
    tile_dir: Path | None = None,
    export_dir: Path | None = None,
    validation_dir: Path | None = None,
    run_id: str | None = None,
    sha256_cache_path: Path | None = None,
) -> PublicationPlan:
    run_id = run_id or new_run_id()
    sha256_cache = _load_sha256_cache(sha256_cache_path)
    plan = PublicationPlan(
        version=1,
        run_id=run_id,
        created_at=utc_now(),
        bucket=config.public_bucket,
        staging_bucket=config.staging_bucket,
        object_prefix=config.object_prefix,
        public_base_url=config.public_base_url,
    )

    public_base_url = config.public_base_url
    if config.publish_aggregate_h5:
        for item in items:
            if item.source_type == "raw_volume_day":
                for volume in item.raw_volumes:
                    source = Path(volume.path)
                    key = raw_volume_object_key(item.radar, item.date, volume.pulse, volume.filename, config.object_prefix)
                    if not source.exists():
                        plan.objects.append(
                            PublicationObject(
                                kind="raw_volume_h5",
                                bucket=config.public_bucket,
                                key=key,
                                source_path=str(source),
                                size=0,
                                sha256="",
                                content_type="application/x-hdf5",
                                public_url=join_object_url(public_base_url, key),
                                status="missing_source",
                                message="source file does not exist",
                            )
                        )
                        continue
                    plan.objects.append(
                        _object_from_file(
                            "raw_volume_h5",
                            config.public_bucket,
                            key,
                            source,
                            public_base_url,
                            sha256_cache,
                            sha256_cache_path,
                        )
                    )
                continue

            source = Path(item.path)
            if not source.exists():
                plan.objects.append(
                    PublicationObject(
                        kind="aggregate_h5",
                        bucket=config.public_bucket,
                        key=aggregate_object_key(item.radar, item.date, config.object_prefix),
                        source_path=str(source),
                        size=0,
                        sha256="",
                        content_type="application/x-hdf5",
                        public_url=join_object_url(public_base_url, aggregate_object_key(item.radar, item.date, config.object_prefix)),
                        status="missing_source",
                        message="source file does not exist",
                    )
                )
                continue
            plan.objects.append(
                _object_from_file(
                    "aggregate_h5",
                    config.public_bucket,
                    aggregate_object_key(item.radar, item.date, config.object_prefix),
                    source,
                    public_base_url,
                    sha256_cache,
                    sha256_cache_path,
                )
            )

        aggregate_items = [item for item in items if item.source_type != "raw_volume_day"]
        for radar, year in sorted({(item.radar, item.date[:4]) for item in aggregate_items}):
            checksum_payload = aggregate_checksum_payload(
                aggregate_items,
                public_base_url,
                config.object_prefix,
                radar,
                year,
                sha256_cache,
                sha256_cache_path,
            )
            checksum_source = _write_generated_json(
                staging_dir,
                Path("checksums") / "sha256" / year / f"{radar}.json",
                checksum_payload,
            )
            plan.objects.append(
                _object_from_file(
                    "checksum",
                    config.public_bucket,
                    checksum_object_key(year, radar, config.object_prefix),
                    checksum_source,
                    public_base_url,
                )
            )

    if catalog_path.exists():
        inventory_payload = public_catalog_inventory_payload(items, public_base_url, config.object_prefix)
        inventory_source = _write_generated_json(
            staging_dir,
            Path("catalog") / "inventory" / "catalog.json",
            inventory_payload,
        )
        plan.objects.append(
            _object_from_file(
                "catalog_inventory",
                config.public_bucket,
                catalog_inventory_object_key("catalog.json", config.object_prefix),
                inventory_source,
                public_base_url,
            )
        )

    if config.publish_stac:
        root_payload = root_catalog_to_stac(
            items,
            public_base_url=public_base_url,
            object_prefix=config.object_prefix,
            public_metadata=config.public_metadata(),
        )
        root_source = _write_generated_json(staging_dir, Path("catalog") / "stac" / "catalog.json", root_payload)
        plan.objects.append(
            _object_from_file(
                "stac_catalog",
                config.public_bucket,
                stac_catalog_object_key(config.object_prefix),
                root_source,
                public_base_url,
            )
        )
        collection_payload = collection_to_stac(
            items,
            public_base_url=public_base_url,
            object_prefix=config.object_prefix,
            public_metadata=config.public_metadata(),
        )
        collection_source = _write_generated_json(
            staging_dir,
            Path("catalog") / "stac" / AGGREGATE_COLLECTION_ID / "collection.json",
            collection_payload,
        )
        plan.objects.append(
            _object_from_file(
                "stac_collection",
                config.public_bucket,
                stac_collection_object_key(AGGREGATE_COLLECTION_ID, config.object_prefix),
                collection_source,
                public_base_url,
            )
        )
        for item in items:
            stac_payload = item_to_stac(
                item,
                public_base_url=public_base_url,
                object_prefix=config.object_prefix,
                public_metadata=config.public_metadata(),
            )
            relative = Path("catalog") / "stac" / "uk-wsr-aggregate-h5" / f"{item.item_id}.json"
            source = _write_generated_json(staging_dir, relative, stac_payload)
            plan.objects.append(
                _object_from_file(
                    "stac_item",
                    config.public_bucket,
                    stac_object_key("uk-wsr-aggregate-h5", item.item_id, config.object_prefix),
                    source,
                    public_base_url,
                )
            )

    if config.publish_previews and preview_dir and preview_dir.exists():
        for source in sorted(preview_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(preview_dir)
            key = "/".join([config.object_prefix, "previews", *relative.parts])
            plan.objects.append(_object_from_file("preview", config.public_bucket, key, source, public_base_url))

    if config.publish_tiles and tile_dir and tile_dir.exists():
        for source in sorted(tile_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(tile_dir)
            key = "/".join([config.object_prefix, "tiles", *relative.parts])
            plan.objects.append(_object_from_file("tile", config.public_bucket, key, source, public_base_url))

    if config.publish_exports and export_dir and export_dir.exists():
        for source in sorted(export_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(export_dir)
            key = export_product_object_key(relative, config.object_prefix)
            plan.objects.append(_object_from_file("export_product", config.public_bucket, key, source, public_base_url))

    validation_summary = _validation_summary(validation_dir)
    if config.publish_validation_reports and validation_dir and validation_dir.exists():
        for source in sorted(validation_dir.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(validation_dir)
            key = validation_report_object_key(relative, config.object_prefix)
            plan.objects.append(_object_from_file("validation_report", config.public_bucket, key, source, public_base_url))

    dataset_payload = public_dataset_metadata_payload(
        items,
        public_base_url,
        config.object_prefix,
        config.public_metadata(),
        validation_summary,
    )
    dataset_source = _write_generated_json(staging_dir, Path("dataset.json"), dataset_payload)
    plan.objects.append(
        _object_from_file(
            "dataset_metadata",
            config.public_bucket,
            public_dataset_metadata_object_key(config.object_prefix),
            dataset_source,
            public_base_url,
        )
    )
    landing_source = _write_generated_text(staging_dir, Path("index.html"), public_landing_html(dataset_payload))
    plan.objects.append(
        _object_from_file(
            "landing_page",
            config.public_bucket,
            public_landing_object_key(config.object_prefix),
            landing_source,
            public_base_url,
        )
    )

    status_payload = {
        "ok": True,
        "run_id": run_id,
        "created_at": plan.created_at,
        "object_count": len(plan.objects),
        "catalog_item_count": len(items),
        "catalog_url": join_object_url(public_base_url, catalog_inventory_object_key("catalog.json", config.object_prefix)),
        "landing_url": join_object_url(public_base_url, public_landing_object_key(config.object_prefix)),
        "dataset_metadata_url": join_object_url(public_base_url, public_dataset_metadata_object_key(config.object_prefix)),
        "validation": validation_summary,
        "dataset": config.public_metadata(),
    }
    status_source = _write_generated_json(staging_dir, Path("status.json"), status_payload)
    plan.objects.append(
        _object_from_file(
            "status",
            config.public_bucket,
            public_status_object_key(config.object_prefix),
            status_source,
            public_base_url,
        )
    )
    return plan


def reconcile_plan_with_manifest(expected: PublicationPlan, actual: PublicationPlan) -> dict[str, Any]:
    actual_by_key = {obj.key: obj for obj in actual.objects}
    missing: list[str] = []
    changed: list[str] = []
    unverified: list[str] = []
    extra = sorted(set(actual_by_key) - {obj.key for obj in expected.objects})

    for obj in expected.objects:
        actual_obj = actual_by_key.get(obj.key)
        if actual_obj is None:
            missing.append(obj.key)
            continue
        if actual_obj.sha256 != obj.sha256 or actual_obj.size != obj.size:
            changed.append(obj.key)
        if actual_obj.status != "verified":
            unverified.append(obj.key)

    return {
        "ok": not missing and not changed and not unverified,
        "missing": missing,
        "changed": changed,
        "unverified": unverified,
        "extra": extra,
    }
