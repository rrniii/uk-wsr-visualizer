#!/usr/bin/env python3
"""Audit all learned-background research artifacts and corpus provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_training_audit import (
    audit_background_training_run,
    write_background_training_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("reports/background_training_v2/inventory.json"),
    )
    parser.add_argument(
        "--training-results",
        type=Path,
        default=Path(
            "reports/background_training_v2/training_results.json"
        ),
    )
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/background_training_v2/audit.json"),
    )
    parser.add_argument(
        "--conditioned-support-count",
        type=int,
        default=12,
    )
    args = parser.parse_args()

    audit = audit_background_training_run(
        args.inventory,
        args.training_results,
        model_dir=args.model_dir,
        conditioned_support_count=args.conditioned_support_count,
    )
    destination = write_background_training_audit(audit, args.output)
    print(
        json.dumps(
            {
                "status": audit["status"],
                "audited_model_count": audit["audited_model_count"],
                "passed_model_count": audit["passed_model_count"],
                "failed_model_count": audit["failed_model_count"],
                "error_count": audit["error_count"],
                "output": str(destination),
            },
            sort_keys=True,
        )
    )
    return 0 if audit["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
