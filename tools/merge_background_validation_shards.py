#!/usr/bin/env python3
"""Merge complete real-data validation shards into one canonical report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_validation_pipeline import (
    merge_background_validation_shards,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "shards",
        type=Path,
        nargs="+",
        help="Complete shard validation_results.json files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Canonical validation_results.json destination.",
    )
    args = parser.parse_args()

    destination = merge_background_validation_shards(
        args.shards,
        args.output,
    )
    report = json.loads(destination.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "configuration_sha256": report["configuration_sha256"],
                "output": str(destination),
                "record_count": report["scored_job_count"],
                "radar_count": report["summary"]["radar_count"],
                "target_count": report["summary"]["target_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
