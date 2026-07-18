#!/usr/bin/env python3
"""Audit and freeze the downloaded temporal-context corpus snapshot."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.background_training import (
    background_training_exclusions_from_benchmark,
)
from uk_wsr_visualizer.background_training_pipeline import file_sha256
from uk_wsr_visualizer.temporal_corpus import (
    load_verified_temporal_context_corpus,
    validate_temporal_context_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("validation/temporal_context_v1/manifest.json"),
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(
            "/tmp/uk_wsr_temporal_context_v1_pvol/download_ledger.json"
        ),
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
        "--output",
        type=Path,
        default=Path(
            "validation/temporal_context_v1/"
            "training_validation_integrity.json"
        ),
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
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
    errors = validate_temporal_context_manifest(
        manifest,
        exclusions=exclusions,
    )
    manifest_hash = file_sha256(args.manifest)
    ledger_hash = file_sha256(args.ledger)
    if ledger.get("manifest_sha256") != manifest_hash:
        errors.append("ledger manifest hash mismatch")
    if (
        ledger.get("benchmark_exclusion_digest_sha256")
        != exclusions.digest()
    ):
        errors.append("ledger benchmark exclusion digest mismatch")

    selected_splits = tuple(
        str(value) for value in ledger.get("selected_splits") or ()
    )
    if set(selected_splits) != {"training", "validation"}:
        errors.append(
            "integrity snapshot must contain training and validation only"
        )

    corpus = None
    try:
        corpus = load_verified_temporal_context_corpus(
            args.manifest,
            args.ledger,
            splits=selected_splits,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"local corpus verification failed: {exc}")

    ledger_files = ledger.get("files")
    if not isinstance(ledger_files, dict):
        ledger_files = {}
        errors.append("ledger has no source file map")
    selected_manifest_files = [
        item
        for item in manifest.get("files") or ()
        if str(item.get("split") or "") in selected_splits
    ]
    expected_ids = {
        str(item.get("source_id") or "")
        for item in selected_manifest_files
    }
    ledger_ids = set(ledger_files)
    if ledger_ids != expected_ids:
        errors.append("ledger source IDs differ from selected manifest IDs")

    drift_records = []
    invalid_drift = []
    for source_id in sorted(expected_ids & ledger_ids):
        record = ledger_files[source_id]
        if record.get("catalog_size_match") is not False:
            continue
        summary = {
            "source_id": source_id,
            "radar": record.get("radar"),
            "split": record.get("split"),
            "date": record.get("date"),
            "time": record.get("time"),
            "pulse": record.get("pulse"),
            "catalog_size_bytes": record.get("catalog_size_bytes"),
            "actual_size_bytes": record.get("size_bytes"),
            "actual_sha256": record.get("sha256"),
            "status": record.get("status"),
        }
        drift_records.append(summary)
        if (
            record.get("status") != "downloaded_catalog_drift"
            or record.get("hdf5_valid") is not True
            or len(str(record.get("sha256") or "")) != 64
        ):
            invalid_drift.append(source_id)
    if len(drift_records) != int(
        ledger.get("catalog_size_mismatch_count") or 0
    ):
        errors.append("catalog drift count mismatch")
    if invalid_drift:
        errors.append(
            f"{len(invalid_drift)} catalog drift files are not verified"
        )

    holdout_entries = [
        source_id
        for source_id, record in ledger_files.items()
        if str(record.get("split") or "") == "holdout"
    ]
    if "holdout" in selected_splits or holdout_entries:
        errors.append("holdout is present in the downloaded ledger")

    source_snapshot_lines: list[str] = []
    counts: Counter[tuple[str, str, str]] = Counter()
    benchmark_hash_overlap: set[str] = set()
    if corpus is not None:
        for source in corpus.sources:
            source_snapshot_lines.append(
                "|".join(
                    (
                        source.source_id,
                        source.sha256,
                        str(source.size_bytes),
                    )
                )
            )
            counts[(source.radar, source.pulse, source.split)] += 1
            if source.sha256 in exclusions.source_sha256:
                benchmark_hash_overlap.add(source.sha256)
    if benchmark_hash_overlap:
        errors.append(
            f"benchmark hash leakage: {len(benchmark_hash_overlap)} source(s)"
        )

    snapshot_sha256 = sha256(
        "\n".join(sorted(source_snapshot_lines)).encode("utf-8")
    ).hexdigest()
    selected_sequences = [
        sequence
        for sequence in manifest.get("sequences") or ()
        if str(sequence.get("split") or "") in selected_splits
    ]
    report: dict[str, Any] = {
        "schema": "uk_wsr_temporal_context_integrity",
        "schema_version": 1,
        "generated_at": _now_utc(),
        "manifest": str(args.manifest),
        "manifest_sha256": manifest_hash,
        "ledger": str(args.ledger),
        "ledger_sha256": ledger_hash,
        "benchmark_exclusion_digest_sha256": exclusions.digest(),
        "selected_splits": list(selected_splits),
        "selected_file_count": len(selected_manifest_files),
        "verified_file_count": (
            len(corpus.sources) if corpus is not None else 0
        ),
        "verified_size_bytes": int(
            ledger.get("validated_size_bytes") or 0
        ),
        "source_snapshot_sha256": snapshot_sha256,
        "selected_sequence_count": len(selected_sequences),
        "eligible_scoring_source_count": sum(
            len(sequence.get("eligible_scoring_source_ids") or ())
            for sequence in selected_sequences
        ),
        "catalog_drift": {
            "count": len(drift_records),
            "classification": (
                "valid HDF5 objects whose actual bytes changed after the "
                "catalogue snapshot; actual size and SHA-256 are frozen in "
                "the download ledger"
            ),
            "records": drift_records,
        },
        "holdout": {
            "sealed": not holdout_entries and "holdout" not in selected_splits,
            "ledger_file_count": len(holdout_entries),
        },
        "counts_by_radar_pulse_split": [
            {
                "radar": radar,
                "pulse": pulse,
                "split": split,
                "file_count": count,
            }
            for (radar, pulse, split), count in sorted(counts.items())
        ],
        "errors": errors,
        "integrity_passed": not errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "integrity_passed": report["integrity_passed"],
                "verified_file_count": report["verified_file_count"],
                "catalog_drift_count": len(drift_records),
                "holdout_sealed": report["holdout"]["sealed"],
                "source_snapshot_sha256": snapshot_sha256,
                "output": str(args.output),
                "errors": errors,
            },
            sort_keys=True,
        )
    )
    return 0 if report["integrity_passed"] else 1


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


if __name__ == "__main__":
    raise SystemExit(main())
