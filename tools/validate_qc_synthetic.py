#!/usr/bin/env python3
"""Compare current and candidate UK WSR QC against exact synthetic masks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.qc_synthetic_validation import (
    CANDIDATE_METHOD,
    CURRENT_METHOD,
    run_synthetic_validation,
    write_synthetic_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/qc_synthetic_v1"),
    )
    parser.add_argument("--seeds", type=int, default=12)
    parser.add_argument("--nrays", type=int, default=180)
    parser.add_argument("--nbins", type=int, default=220)
    args = parser.parse_args()
    if args.seeds < 1:
        raise SystemExit("--seeds must be at least one")

    run = run_synthetic_validation(
        seeds=range(args.seeds),
        nrays=args.nrays,
        nbins=args.nbins,
    )
    written = write_synthetic_validation(run, args.output_dir)
    current = run.report["summary"][CURRENT_METHOD]["all"]
    candidate = run.report["summary"][CANDIDATE_METHOD]["all"]
    print(
        json.dumps(
            {
                "scene_count": candidate["scene_count"],
                "current_artifact_recall": current["artifact_recall"],
                "candidate_artifact_recall": candidate["artifact_recall"],
                "candidate_precision": candidate["precision"],
                "candidate_retain_recall": candidate["retain_recall"],
                "synthetic_gate_passed": run.report[
                    "synthetic_gate_passed"
                ],
                "promotion_eligible": run.report["promotion_eligible"],
                "written": [str(path) for path in written],
            },
            sort_keys=True,
        )
    )
    return 0 if run.report["synthetic_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
