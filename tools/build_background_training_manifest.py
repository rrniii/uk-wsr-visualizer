#!/usr/bin/env python3
"""Build the leakage-controlled multi-date UK WSR background-training manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from hashlib import sha256
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.background_training import (
    BackgroundTrainingSelectionConfig,
    background_training_exclusions_from_benchmark,
    build_background_training_manifest,
)
from uk_wsr_visualizer.field_audit import PUBLIC_BASE

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
        default=Path("/tmp/uk_wsr_background_training_catalogs"),
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=Path("validation/qc_benchmark_v1/manifest.json"),
    )
    parser.add_argument(
        "--benchmark-targets",
        type=Path,
        default=Path("validation/qc_benchmark_v1/review_targets.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation/background_training_v2"),
    )
    parser.add_argument("--training-year", default="2023")
    parser.add_argument("--evaluation-year", default="2025")
    parser.add_argument("--minimum-day-coverage-fraction", type=float, default=0.50)
    args = parser.parse_args()

    if not args.root_catalog.exists():
        _download(ROOT_CATALOG_URL, args.root_catalog)
    root = json.loads(args.root_catalog.read_text(encoding="utf-8"))
    exclusions = _load_exclusions(args.benchmark_manifest, args.benchmark_targets)
    config = BackgroundTrainingSelectionConfig(
        training_year=args.training_year,
        evaluation_year=args.evaluation_year,
        minimum_day_coverage_fraction=args.minimum_day_coverage_fraction,
    )
    cache = CatalogCache(args.catalog_cache)
    manifest = build_background_training_manifest(
        root,
        cache.fetch,
        config=config,
        exclusions=exclusions,
    )
    _write_artifacts(manifest, args.output_dir)
    summary = {
        "manifest_id": manifest["manifest_id"],
        "radar_count": manifest["radar_count"],
        "file_count": manifest["file_count"],
        "selection_errors": len(manifest["errors"]),
        "selection_warnings": len(manifest["warnings"]),
        "validation_errors": manifest["validation_errors"],
        "output_dir": str(args.output_dir),
    }
    print(json.dumps(summary, sort_keys=True))
    return 1 if manifest["validation_errors"] else 0


def _load_exclusions(
    benchmark_manifest_path: Path,
    benchmark_targets_path: Path,
) -> Any:
    manifest = json.loads(benchmark_manifest_path.read_text(encoding="utf-8"))
    targets: dict[str, Any] | None = None
    if benchmark_targets_path.exists():
        targets = json.loads(benchmark_targets_path.read_text(encoding="utf-8"))
    return background_training_exclusions_from_benchmark(manifest, targets)


def _write_artifacts(manifest: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(payload, encoding="utf-8")
    digest = sha256(payload.encode("utf-8")).hexdigest()
    (output_dir / "manifest.sha256").write_text(
        f"{digest}  manifest.json\n",
        encoding="ascii",
    )
    (output_dir / "source_urls.txt").write_text(
        "\n".join(str(item["object_url"]) for item in manifest["files"]) + "\n",
        encoding="utf-8",
    )
    readme = f"""# UK WSR Learned-Background Training Sources v2

This manifest is the leakage-controlled source contract for multi-date learned
noise and clutter priors.

- Radars: {manifest['radar_count']}
- PVOL files: {manifest['file_count']}
- Training year: {manifest['selection']['training_year']}
- Independent validation/holdout year: {manifest['selection']['evaluation_year']}
- Selection errors: {len(manifest['errors'])}
- Validation errors: {len(manifest['validation_errors'])}

Every PVOL contains all native elevations. DBZH supplies the reference gate
geometry while CI, VRAD, SQI, RHOHV, ZDR, PHIDP, and spectrum width provide
joint evidence. The resulting artifact decision is shared by collocated
quantities; missing or misaligned evidence fails open.

The QC benchmark URLs, radar/date pairs, and downloaded SHA-256 values are
excluded. Source hashes must be verified again while materialising the corpus.
Whole dates are exclusive to one of training, validation, or holdout for each
radar.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "uk-wsr-background-training-manifest/2"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open(
        "wb"
    ) as handle:
        shutil.copyfileobj(response, handle)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
