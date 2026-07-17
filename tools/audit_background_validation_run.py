#!/usr/bin/env python3
"""Audit persisted real-data validation artifacts and decision invariants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_validation_audit import (
    audit_background_validation_run,
    write_background_validation_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path(
            "reports/background_validation_v2_upper_fail_open/"
            "validation_results.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/background_validation_v2_upper_fail_open/audit.json"
        ),
    )
    args = parser.parse_args()

    audit = audit_background_validation_run(args.results)
    destination = write_background_validation_audit(audit, args.output)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "audited_record_count": audit["audited_record_count"],
                "passed_record_count": audit["passed_record_count"],
                "failed_record_count": audit["failed_record_count"],
                "error_count": audit["error_count"],
                "output": str(destination),
            },
            sort_keys=True,
        )
    )
    return 0 if audit["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
