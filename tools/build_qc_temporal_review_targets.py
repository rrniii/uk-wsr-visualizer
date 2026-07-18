#!/usr/bin/env python3
"""Build blinded temporal challenge/control review targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.qc_temporal_review import (
    build_temporal_review_target_manifest,
    validate_temporal_review_target_manifest,
    write_temporal_review_artifacts,
)


DEFAULT_REGRESSION_RESULTS = (
    Path(
        "reports/qc_regression_candidate5/"
        "high-moorsley-20260711-lp-1400-e0400/"
        "validation_results.json"
    ),
    Path(
        "reports/qc_regression_candidate5/"
        "high-moorsley-20260711-sp-1500-e0100/"
        "validation_results.json"
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-results",
        type=Path,
        default=Path(
            "reports/background_validation_v3_candidate5_temporal/"
            "validation_results.json"
        ),
    )
    parser.add_argument(
        "--frozen-policy",
        type=Path,
        default=Path(
            "reports/background_validation_v3_candidate5_temporal/"
            "frozen_policy.json"
        ),
    )
    parser.add_argument(
        "--temporal-manifest",
        type=Path,
        default=Path("validation/temporal_context_v1/manifest.json"),
    )
    parser.add_argument(
        "--download-ledger",
        type=Path,
        default=Path(
            "/private/tmp/uk_wsr_temporal_context_v1_pvol/"
            "download_ledger.json"
        ),
    )
    parser.add_argument(
        "--regression-manifest",
        type=Path,
        default=Path("validation/qc_regression_cases_v1/manifest.json"),
    )
    parser.add_argument(
        "--regression-results",
        action="append",
        type=Path,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation/qc_temporal_review_v1"),
    )
    parser.add_argument(
        "--required-reviewer-count",
        type=int,
        choices=(1, 2),
        default=1,
    )
    args = parser.parse_args()

    validation = _read(args.validation_results)
    frozen_policy = _read(args.frozen_policy)
    temporal_manifest = _read(args.temporal_manifest)
    download_ledger = _read(args.download_ledger)
    regression_manifest = _read(args.regression_manifest)
    cases = {
        str(case["case_id"]): case
        for case in regression_manifest.get("cases", ())
    }
    regression_pairs = []
    paths = tuple(args.regression_results or DEFAULT_REGRESSION_RESULTS)
    for path in paths:
        result = _read(path)
        records = list(result.get("records", ()))
        if len(records) != 1:
            raise ValueError(f"{path}: expected exactly one regression record")
        record = records[0]
        case_id = str(record.get("regression_name") or "")
        if case_id not in cases:
            raise ValueError(f"{path}: unknown regression case {case_id}")
        regression_pairs.append((record, cases[case_id]))

    review = build_temporal_review_target_manifest(
        validation,
        frozen_policy,
        temporal_manifest,
        download_ledger,
        regression_cases=regression_pairs,
        required_reviewer_count=args.required_reviewer_count,
    )
    errors = validate_temporal_review_target_manifest(
        review,
        validation=validation,
        frozen_policy=frozen_policy,
        temporal_manifest=temporal_manifest,
        download_ledger=download_ledger,
    )
    written = write_temporal_review_artifacts(review, args.output_dir)
    print(
        json.dumps(
            {
                "target_count": review["target_count"],
                "geometry_count": review["geometry_count"],
                "double_review_count": review["counts"][
                    "double_review_count"
                ],
                "required_reviewer_count": args.required_reviewer_count,
                "regression_count": review["counts"][
                    "by_internal_role"
                ].get("reported_regression", 0),
                "validation_errors": errors,
                "written": [str(path) for path in written],
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
