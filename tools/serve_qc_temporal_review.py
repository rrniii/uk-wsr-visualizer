#!/usr/bin/env python3
"""Run the local temporal-context blinded QC review application."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from uk_wsr_visualizer.qc_review_app import create_review_app
from uk_wsr_visualizer.qc_temporal_review_app import TemporalReviewStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--stage",
        choices=("primary", "secondary", "adjudicated"),
        default="primary",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "validation/qc_temporal_review_v1/review_targets.json"
        ),
    )
    parser.add_argument(
        "--temporal-ledger",
        type=Path,
        default=Path(
            "/private/tmp/uk_wsr_temporal_context_v1_pvol/"
            "download_ledger.json"
        ),
    )
    parser.add_argument(
        "--regression-root",
        type=Path,
        default=Path("/private/tmp/uk_wsr_regression_cases"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation/qc_temporal_review_v1/annotations"),
    )
    parser.add_argument("--radar", action="append")
    parser.add_argument("--pulse", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    store = TemporalReviewStore(
        targets_path=args.targets,
        temporal_ledger_path=args.temporal_ledger,
        regression_root=args.regression_root,
        output_dir=args.output_dir,
        reviewer=args.reviewer,
        stage=args.stage,
        radars=set(args.radar or ()),
        pulses=set(args.pulse or ()),
        limit=args.limit,
    )
    uvicorn.run(
        create_review_app(store),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
