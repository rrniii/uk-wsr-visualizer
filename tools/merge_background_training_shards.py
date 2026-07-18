#!/usr/bin/env python3
"""Merge contract-identical date-balanced training shard reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def merge_training_shards(
    paths: list[Path],
    output: Path,
    *,
    expected_target_count: int | None = None,
) -> Path:
    if not paths:
        raise ValueError("at least one training shard is required")
    shards: list[dict[str, Any]] = []
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("schema") != "uk_wsr_background_training_v3_results":
            raise ValueError(f"unexpected training schema in {path}")
        if report.get("complete") is not True:
            raise ValueError(f"incomplete training shard: {path}")
        if report.get("errors"):
            raise ValueError(f"training shard contains errors: {path}")
        if int(report.get("trained_target_count") or -1) != len(
            report.get("records") or ()
        ):
            raise ValueError(f"training shard record count mismatch: {path}")
        shards.append(report)

    contract_hash = str(shards[0]["training_contract_sha256"])
    contract = shards[0]["training_contract"]
    for path, report in zip(paths[1:], shards[1:]):
        if (
            report.get("training_contract_sha256") != contract_hash
            or report.get("training_contract") != contract
        ):
            raise ValueError(
                f"training contract mismatch in {path}"
            )

    records = [
        record
        for report in shards
        for record in report.get("records") or ()
    ]
    target_ids = [str(record["target_id"]) for record in records]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("duplicate training targets across shards")
    target_count = sum(int(report["target_count"]) for report in shards)
    if target_count != len(records):
        raise ValueError("merged target count does not match records")
    if (
        expected_target_count is not None
        and target_count != int(expected_target_count)
    ):
        raise ValueError(
            f"merged target count {target_count} != "
            f"{expected_target_count}"
        )

    payload = {
        "schema": "uk_wsr_background_training_v3_results",
        "schema_version": 1,
        "training_contract": contract,
        "training_contract_sha256": contract_hash,
        "source_count": sum(
            int(report["source_count"]) for report in shards
        ),
        "source_date_count": sum(
            int(report["source_date_count"]) for report in shards
        ),
        "target_count": target_count,
        "trained_target_count": len(records),
        "error_count": 0,
        "complete": True,
        "promotion_eligible": False,
        "records": sorted(
            records,
            key=lambda record: str(record["target_id"]),
        ),
        "errors": [],
        "shards": [str(path) for path in paths],
        "radars": sorted({str(record["radar"]) for record in records}),
        "pulses": sorted({str(record["pulse"]) for record in records}),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shards", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-target-count", type=int)
    args = parser.parse_args()
    destination = merge_training_shards(
        args.shards,
        args.output,
        expected_target_count=args.expected_target_count,
    )
    report = json.loads(destination.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "complete": report["complete"],
                "target_count": report["target_count"],
                "radar_count": len(report["radars"]),
                "output": str(destination),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
