"""Runtime configuration for the web app and CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_AGGREGATE_BASE = Path(
    "/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site"
)
DEFAULT_DATA_DIR = Path(os.environ.get("AVOCET_WCT_DATA_DIR", "data/avocet-wct"))
DEFAULT_OBJECT_STORE_EXTERNAL_BASE = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public"
DEFAULT_REMOTE_CATALOG_URL = f"{DEFAULT_OBJECT_STORE_EXTERNAL_BASE}/uk-radar/catalog/inventory/catalog.json"


def _env_text(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Settings:
    aggregate_base: Path = DEFAULT_AGGREGATE_BASE
    data_dir: Path = DEFAULT_DATA_DIR
    catalog_path: Path = DEFAULT_DATA_DIR / "catalog.json"
    preview_dir: Path = DEFAULT_DATA_DIR / "previews"
    tile_dir: Path = DEFAULT_DATA_DIR / "tiles"
    export_dir: Path = DEFAULT_DATA_DIR / "exports"
    session_dir: Path = DEFAULT_DATA_DIR / "sessions"
    remote_aggregate_cache_dir: Path = DEFAULT_DATA_DIR / "remote-aggregate-cache"
    remote_cache_ttl_seconds: int = int(os.environ.get("AVOCET_WCT_REMOTE_CACHE_TTL_SECONDS", "3600"))
    remote_cache_max_bytes: int = int(os.environ.get("AVOCET_WCT_REMOTE_CACHE_MAX_BYTES", str(25 * 1024 * 1024 * 1024)))
    object_store_manifest_path: Path = DEFAULT_DATA_DIR / "object-store" / "latest-manifest.json"
    object_store_external_base: str = _env_text("AVOCET_WCT_OBJECT_STORE_EXTERNAL_BASE", DEFAULT_OBJECT_STORE_EXTERNAL_BASE)
    object_store_internal_base: str = os.environ.get("AVOCET_WCT_OBJECT_STORE_INTERNAL_BASE", "")
    remote_catalog_url: str = _env_text("AVOCET_WCT_REMOTE_CATALOG_URL", DEFAULT_REMOTE_CATALOG_URL)

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("AVOCET_WCT_DATA_DIR", str(DEFAULT_DATA_DIR)))
        return cls(
            aggregate_base=Path(os.environ.get("AVOCET_WCT_AGGREGATE_BASE", str(DEFAULT_AGGREGATE_BASE))),
            data_dir=data_dir,
            catalog_path=Path(os.environ.get("AVOCET_WCT_CATALOG", str(data_dir / "catalog.json"))),
            preview_dir=Path(os.environ.get("AVOCET_WCT_PREVIEW_DIR", str(data_dir / "previews"))),
            tile_dir=Path(os.environ.get("AVOCET_WCT_TILE_DIR", str(data_dir / "tiles"))),
            export_dir=Path(os.environ.get("AVOCET_WCT_EXPORT_DIR", str(data_dir / "exports"))),
            session_dir=Path(os.environ.get("AVOCET_WCT_SESSION_DIR", str(data_dir / "sessions"))),
            remote_aggregate_cache_dir=Path(
                os.environ.get("AVOCET_WCT_REMOTE_AGGREGATE_CACHE_DIR", str(data_dir / "remote-aggregate-cache"))
            ),
            remote_cache_ttl_seconds=int(os.environ.get("AVOCET_WCT_REMOTE_CACHE_TTL_SECONDS", "3600")),
            remote_cache_max_bytes=int(os.environ.get("AVOCET_WCT_REMOTE_CACHE_MAX_BYTES", str(25 * 1024 * 1024 * 1024))),
            object_store_manifest_path=Path(
                os.environ.get("AVOCET_WCT_OBJECT_STORE_MANIFEST", str(data_dir / "object-store" / "latest-manifest.json"))
            ),
            object_store_external_base=_env_text("AVOCET_WCT_OBJECT_STORE_EXTERNAL_BASE", DEFAULT_OBJECT_STORE_EXTERNAL_BASE),
            object_store_internal_base=os.environ.get("AVOCET_WCT_OBJECT_STORE_INTERNAL_BASE", ""),
            remote_catalog_url=_env_text("AVOCET_WCT_REMOTE_CATALOG_URL", DEFAULT_REMOTE_CATALOG_URL),
        )
