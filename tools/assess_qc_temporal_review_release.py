#!/usr/bin/env python3
"""Assess blinded temporal labels before any learned-model promotion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.qc_temporal_review_release import (
    assess_temporal_review_release,
    write_temporal_review_release,
)


def _load(path: Path | None):
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--primary", type=Path)
    parser.add_argument("--secondary", type=Path)
    parser.add_argument("--adjudicated", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    release = assess_temporal_review_release(
        _load(args.targets),
        primary=_load(args.primary),
        secondary=_load(args.secondary),
        adjudicated=_load(args.adjudicated),
    )
    destination = write_temporal_review_release(release, args.output)
    print(json.dumps({
        "output": str(destination),
        "target_state_counts": release["target_state_counts"],
        "geometry_state_counts": release["geometry_state_counts"],
        "promotion_eligible_model_count": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
