#!/usr/bin/env python3
"""Download and integrity-check sources in a UK WSR QC benchmark manifest."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.qc_benchmark import (
    benchmark_local_path,
    validate_benchmark_manifest,
)
from uk_wsr_visualizer.qc_benchmark_download import (
    download_and_validate_source,
    load_download_ledger,
    utc_now,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("validation/qc_benchmark_v1/manifest.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_qc_benchmark_pvol"),
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--split", action="append")
    parser.add_argument("--radar", action="append")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validation_errors = validate_benchmark_manifest(manifest)
    if validation_errors:
        raise SystemExit("invalid manifest: " + "; ".join(validation_errors))

    wanted_splits = set(args.split or [])
    wanted_radars = set(args.radar or [])
    files = [
        item
        for item in manifest["files"]
        if (not wanted_splits or item["split"] in wanted_splits)
        and (not wanted_radars or item["radar"] in wanted_radars)
    ]
    if args.limit is not None:
        files = files[: max(0, args.limit)]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = args.output_dir / "download_ledger.json"
    ledger = load_download_ledger(ledger_path)
    completed: dict[str, dict[str, Any]] = dict(ledger.get("files", {}))
    failures: list[dict[str, Any]] = []
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                download_and_validate_source,
                item,
                benchmark_local_path(args.output_dir, item),
                retries=max(1, args.retries),
                previous=completed.get(str(item["case_id"])),
            ): item
            for item in files
        }
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                result = future.result()
                completed[str(item["case_id"])] = result
                print(
                    json.dumps(
                        {
                            "download_progress": f"{index}/{len(files)}",
                            "case_id": item["case_id"],
                            "radar": item["radar"],
                            "pulse": item["pulse"],
                            "status": result["status"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - batch ledger records failures.
                completed.pop(str(item["case_id"]), None)
                failure = {
                    "case_id": item.get("case_id"),
                    "radar": item.get("radar"),
                    "date": item.get("date"),
                    "time": item.get("time"),
                    "pulse": item.get("pulse"),
                    "url": item.get("object_url"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                failures.append(failure)
                print(json.dumps(failure, sort_keys=True), flush=True)

    selected_ids = {str(item["case_id"]) for item in files}
    selected_results = {
        case_id: result
        for case_id, result in completed.items()
        if case_id in selected_ids
    }
    ledger = {
        "schema": "uk_wsr_qc_benchmark_download_ledger",
        "schema_version": 1,
        "manifest": str(args.manifest),
        "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
        "generated_at": utc_now(),
        "selected_file_count": len(files),
        "validated_file_count": len(selected_results),
        "validated_size_bytes": sum(
            int(result.get("size_bytes") or 0) for result in selected_results.values()
        ),
        "catalog_size_mismatch_count": sum(
            1
            for result in selected_results.values()
            if result.get("catalog_size_match") is False
        ),
        "elapsed_seconds": time.monotonic() - started,
        "failures": failures,
        "files": dict(sorted(completed.items())),
    }
    temporary = ledger_path.with_suffix(".json.part")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)
    print(
        json.dumps(
            {
                "selected_file_count": len(files),
                "validated_file_count": len(selected_results),
                "failure_count": len(failures),
                "catalog_size_mismatch_count": ledger["catalog_size_mismatch_count"],
                "validated_size_gib": round(ledger["validated_size_bytes"] / (1024**3), 3),
                "ledger": str(ledger_path),
            },
            sort_keys=True,
        )
    )
    return 1 if failures or len(selected_results) != len(files) else 0


if __name__ == "__main__":
    raise SystemExit(main())
