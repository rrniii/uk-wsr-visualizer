#!/usr/bin/env python3
"""Build the independent, stratified UK WSR QC benchmark manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.field_audit import PUBLIC_BASE
from uk_wsr_visualizer.qc_benchmark import (
    build_benchmark_manifest,
    validate_benchmark_manifest,
    write_benchmark_artifacts,
)

ROOT_CATALOG_URL = f"{PUBLIC_BASE}/ukmo-nimrod/catalog/pvol/catalog.json"


class CatalogCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def fetch(self, url: str) -> dict[str, Any]:
        relative = url.removeprefix(PUBLIC_BASE).lstrip("/")
        path = self.root / relative
        if not path.exists():
            _download(url, path)
        return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root-catalog",
        type=Path,
        default=Path("/tmp/uk_wsr_pvol_catalog.json"),
    )
    parser.add_argument(
        "--catalog-cache",
        type=Path,
        default=Path("/tmp/uk_wsr_qc_benchmark_catalogs"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation/qc_benchmark_v1"),
    )
    parser.add_argument("--max-day-offset", type=int, default=14)
    parser.add_argument("--max-time-offset-minutes", type=int, default=20)
    parser.add_argument("--minimum-day-coverage-fraction", type=float, default=0.80)
    args = parser.parse_args()

    if not args.root_catalog.exists():
        _download(ROOT_CATALOG_URL, args.root_catalog)
    root = json.loads(args.root_catalog.read_text(encoding="utf-8"))
    cache = CatalogCache(args.catalog_cache)
    manifest = build_benchmark_manifest(
        root,
        cache.fetch,
        max_day_offset=args.max_day_offset,
        max_time_offset_minutes=args.max_time_offset_minutes,
        minimum_day_coverage_fraction=args.minimum_day_coverage_fraction,
    )
    write_benchmark_artifacts(manifest, args.output_dir)
    errors = validate_benchmark_manifest(manifest)
    print(
        json.dumps(
            {
                "benchmark_id": manifest["benchmark_id"],
                "radar_count": manifest["radar_count"],
                "file_count": manifest["file_count"],
                "selection_errors": len(manifest["errors"]),
                "validation_errors": errors,
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "uk-wsr-qc-benchmark/1"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
