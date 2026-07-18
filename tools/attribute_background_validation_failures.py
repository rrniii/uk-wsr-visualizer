#!/usr/bin/env python3
"""Persist exact failure attribution for a background-validation run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_failure_attribution import (
    build_background_failure_attribution,
    write_background_failure_attribution,
)
from uk_wsr_visualizer.background_training_pipeline import file_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-results",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--frozen-policy",
        type=Path,
        required=True,
    )
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()

    report = build_background_failure_attribution(
        args.validation_results,
        args.frozen_policy,
    )
    json_path, markdown_path, csv_path = (
        write_background_failure_attribution(
            report,
            json_path=args.output_json,
            markdown_path=args.output_markdown,
            csv_path=args.output_csv,
        )
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "target_count": report["target_count"],
                "sweep_count": report["sweep_count"],
                "holdout_scoring_target_count": report[
                    "holdout_scoring_target_count"
                ],
                "output_json": str(json_path),
                "output_json_sha256": file_sha256(json_path),
                "output_markdown": (
                    str(markdown_path) if markdown_path else None
                ),
                "output_csv": str(csv_path) if csv_path else None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
