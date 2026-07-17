#!/usr/bin/env python3
"""Freeze validation safety screens before scoring the holdout split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_training_pipeline import file_sha256
from uk_wsr_visualizer.background_validation_policy import (
    build_frozen_background_validation_policy,
    write_frozen_background_validation_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-results",
        type=Path,
        default=Path(
            "reports/background_validation_v2/validation_results.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/background_validation_v2/frozen_policy.json"
        ),
    )
    args = parser.parse_args()

    policy = build_frozen_background_validation_policy(
        args.validation_results
    )
    destination = write_frozen_background_validation_policy(
        policy,
        args.output,
    )
    print(
        json.dumps(
            {
                "status": policy["status"],
                "target_count": policy["target_count"],
                "state_counts": policy["state_counts"],
                "promotion_eligible_target_count": policy[
                    "promotion_eligible_target_count"
                ],
                "output": str(destination),
                "output_sha256": file_sha256(destination),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
