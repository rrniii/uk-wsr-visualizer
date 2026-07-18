#!/usr/bin/env python3
"""Build blinded, all-elevation review targets from downloaded benchmark PVOLs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.qc_review import (
    build_review_target_manifest,
    validate_review_target_manifest,
    write_review_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("validation/qc_benchmark_v1/manifest.json"),
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_qc_benchmark_pvol"),
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("/tmp/uk_wsr_qc_benchmark_pvol/download_ledger.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation/qc_benchmark_v1"),
    )
    args = parser.parse_args()

    benchmark = json.loads(args.manifest.read_text(encoding="utf-8"))
    ledger = (
        json.loads(args.ledger.read_text(encoding="utf-8"))
        if args.ledger.exists()
        else {"files": {}}
    )
    review = build_review_target_manifest(
        benchmark,
        source_root=args.source_dir,
        download_ledger=ledger,
    )
    write_review_artifacts(review, benchmark, args.output_dir)
    errors = validate_review_target_manifest(review, benchmark)
    print(
        json.dumps(
            {
                "target_count": review["target_count"],
                "double_review_count": review["counts"]["double_review_count"],
                "selection_errors": review["error_count"],
                "validation_errors": errors,
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
