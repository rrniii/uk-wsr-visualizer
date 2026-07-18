#!/usr/bin/env python3
"""Run the isolated local application for blinded UK WSR QC review."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from uk_wsr_visualizer.qc_review_app import ReviewStore, create_review_app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--stage",
        choices=("primary", "secondary", "adjudicated"),
        default="primary",
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("validation/qc_benchmark_v1/manifest.json"),
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("validation/qc_benchmark_v1/review_targets.json"),
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_qc_benchmark_pvol"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation/qc_benchmark_v1/annotations"),
    )
    parser.add_argument("--radar", action="append")
    parser.add_argument("--split", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    store = ReviewStore(
        benchmark_path=args.benchmark,
        targets_path=args.targets,
        source_root=args.source_dir,
        output_dir=args.output_dir,
        reviewer=args.reviewer,
        stage=args.stage,
        radars=set(args.radar or []),
        splits=set(args.split or []),
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
