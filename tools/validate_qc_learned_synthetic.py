#!/usr/bin/env python3
"""Validate a learned clutter prior on disjoint dynamic synthetic scenes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.qc_synthetic_validation import (
    CANDIDATE_METHOD,
    LEARNED_CANDIDATE_METHOD,
    run_learned_prior_synthetic_validation,
    write_learned_prior_synthetic_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/qc_synthetic_learned_v1"),
    )
    parser.add_argument("--training-scenes-per-pulse", type=int, default=48)
    parser.add_argument("--holdout-scenes-per-pulse", type=int, default=12)
    parser.add_argument("--nrays", type=int, default=180)
    parser.add_argument("--nbins", type=int, default=220)
    args = parser.parse_args()
    if args.training_scenes_per_pulse < 8:
        raise SystemExit("--training-scenes-per-pulse must be at least eight")
    if args.holdout_scenes_per_pulse < 1:
        raise SystemExit("--holdout-scenes-per-pulse must be at least one")

    run = run_learned_prior_synthetic_validation(
        training_seeds=range(
            1000,
            1000 + args.training_scenes_per_pulse,
        ),
        holdout_seeds=range(
            2000,
            2000 + args.holdout_scenes_per_pulse,
        ),
        nrays=args.nrays,
        nbins=args.nbins,
    )
    written = write_learned_prior_synthetic_validation(
        run,
        args.output_dir,
    )
    baseline = run.report["summary"][CANDIDATE_METHOD]["all"]
    learned = run.report["summary"][LEARNED_CANDIDATE_METHOD]["all"]
    print(
        json.dumps(
            {
                "training_scene_count": run.report["training_contract"][
                    "training_scene_count"
                ],
                "holdout_scene_count": run.report["training_contract"][
                    "holdout_scene_count"
                ],
                "baseline_static_clutter_recall": baseline["per_artifact"][
                    "static_clutter"
                ]["recall"],
                "learned_static_clutter_recall": learned["per_artifact"][
                    "static_clutter"
                ]["recall"],
                "learned_artifact_recall": learned["artifact_recall"],
                "learned_precision": learned["precision"],
                "learned_retain_recall": learned["retain_recall"],
                "validation_gate_passed": run.report[
                    "validation_gate_passed"
                ],
                "promotion_eligible": run.report["promotion_eligible"],
                "written": [str(path) for path in written],
            },
            sort_keys=True,
        )
    )
    return 0 if run.report["validation_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
