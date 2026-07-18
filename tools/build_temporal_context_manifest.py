#!/usr/bin/env python3
"""Build the leakage-controlled consecutive-volume UK WSR corpus."""

from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.background_training import (
    background_training_exclusions_from_benchmark,
)
from uk_wsr_visualizer.background_training_pipeline import file_sha256
from uk_wsr_visualizer.field_audit import PUBLIC_BASE
from uk_wsr_visualizer.temporal_corpus import (
    TemporalCorpusSelectionConfig,
    build_temporal_context_manifest,
    write_temporal_context_manifest,
)


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
        "--source-manifest",
        type=Path,
        default=Path("validation/background_training_v2/manifest.json"),
    )
    parser.add_argument(
        "--catalog-cache",
        type=Path,
        default=Path("/tmp/uk_wsr_temporal_context_catalogs"),
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
        default=Path("validation/temporal_context_v1"),
    )
    parser.add_argument("--sequence-length", type=int, default=12)
    parser.add_argument("--maximum-gap-minutes", type=int, default=20)
    args = parser.parse_args()

    source_manifest = json.loads(
        args.source_manifest.read_text(encoding="utf-8")
    )
    benchmark = json.loads(
        args.benchmark_manifest.read_text(encoding="utf-8")
    )
    targets = (
        json.loads(args.benchmark_targets.read_text(encoding="utf-8"))
        if args.benchmark_targets.exists()
        else None
    )
    exclusions = background_training_exclusions_from_benchmark(
        benchmark,
        targets,
    )
    config = TemporalCorpusSelectionConfig(
        sequence_length=args.sequence_length,
        maximum_gap_minutes=args.maximum_gap_minutes,
    )
    manifest = build_temporal_context_manifest(
        source_manifest,
        CatalogCache(args.catalog_cache).fetch,
        source_manifest_sha256=file_sha256(args.source_manifest),
        config=config,
        exclusions=exclusions,
    )
    manifest_path, digest = write_temporal_context_manifest(
        manifest,
        args.output_dir,
    )
    _write_supporting_files(manifest, args.output_dir)
    print(
        json.dumps(
            {
                "manifest_id": manifest["manifest_id"],
                "radar_count": manifest["radar_count"],
                "sequence_count": manifest["sequence_count"],
                "file_count": manifest["file_count"],
                "selection_errors": len(manifest["errors"]),
                "validation_errors": manifest["validation_errors"],
                "manifest": str(manifest_path),
                "manifest_sha256": digest,
            },
            sort_keys=True,
        )
    )
    return 1 if manifest["validation_errors"] else 0


def _write_supporting_files(
    manifest: dict[str, Any],
    output_dir: Path,
) -> None:
    (output_dir / "source_urls.txt").write_text(
        "\n".join(str(item["object_url"]) for item in manifest["files"])
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        "\n".join(
            [
                "# UK WSR Consecutive-Volume Context Corpus v1",
                "",
                (
                    f"- Radars: {manifest['radar_count']}"
                ),
                (
                    f"- Sequences: {manifest['sequence_count']}"
                ),
                (
                    f"- Unique PVOL files: {manifest['file_count']}"
                ),
                (
                    f"- Volumes per sequence: "
                    f"{manifest['selection']['sequence_length']}"
                ),
                "",
                (
                    "Every sequence is date-disjoint across training, "
                    "validation, and holdout; spans one pulse type; retains "
                    "all native elevations and companion fields; and has "
                    "explicit previous/next links. Only interior volumes are "
                    "eligible for learned decisions."
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "uk-wsr-temporal-context-manifest/1"},
    )
    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
