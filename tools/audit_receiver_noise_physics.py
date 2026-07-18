#!/usr/bin/env python3
"""Audit receiver-noise removals against the physical range-power law."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.receiver_noise_audit import (
    audit_receiver_noise_physics,
    write_receiver_noise_physics_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-results",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
    )
    args = parser.parse_args()

    audit = audit_receiver_noise_physics(args.validation_results)
    output_json, output_csv = write_receiver_noise_physics_audit(
        audit,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )
    print(
        json.dumps(
            {
                "groups": audit["groups"],
                "output_csv": (
                    str(output_csv) if output_csv is not None else None
                ),
                "output_json": str(output_json),
                "record_count": audit["record_count"],
                "status_counts": audit["status_counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
