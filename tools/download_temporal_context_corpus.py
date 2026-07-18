#!/usr/bin/env python3
"""Download and verify selected consecutive-volume corpus partitions."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.background_training import (
    background_training_exclusions_from_benchmark,
)
from uk_wsr_visualizer.background_training_download import (
    download_and_validate_training_source,
)
from uk_wsr_visualizer.qc_benchmark_download import (
    load_download_ledger,
    utc_now,
)
from uk_wsr_visualizer.temporal_corpus import (
    temporal_corpus_local_path,
    validate_temporal_context_manifest,
)

CHECKPOINT_INTERVAL = 25
DEFAULT_SPLITS = ("training", "validation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("validation/temporal_context_v1/manifest.json"),
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=Path("validation/qc_benchmark_v1/manifest.json"),
    )
    parser.add_argument(
        "--benchmark-targets",
        type=Path,
        default=Path("validation/qc_benchmark_v1/review_targets.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_temporal_context_v1_pvol"),
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--split",
        action="append",
        choices=("training", "validation", "holdout"),
    )
    parser.add_argument("--radar", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=CHECKPOINT_INTERVAL,
    )
    parser.add_argument("--open-holdout", action="store_true")
    parser.add_argument("--frozen-policy", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    benchmark = json.loads(
        args.benchmark_manifest.read_text(encoding="utf-8")
    )
    targets = (
        json.loads(args.benchmark_targets.read_text(encoding="utf-8"))
        if args.benchmark_targets.exists()
        else None
    )
    exclusions = background_training_exclusions_from_benchmark(
        benchmark,
        targets,
    )
    validation_errors = validate_temporal_context_manifest(
        manifest,
        exclusions=exclusions,
    )
    if validation_errors:
        raise SystemExit(
            "invalid manifest: " + "; ".join(validation_errors)
        )

    wanted_splits = tuple(args.split or DEFAULT_SPLITS)
    _verify_holdout_gate(
        wanted_splits,
        open_holdout=args.open_holdout,
        frozen_policy=args.frozen_policy,
    )
    wanted_radars = set(args.radar or [])
    files = [
        item
        for item in manifest["files"]
        if item["split"] in wanted_splits
        and (not wanted_radars or item["radar"] in wanted_radars)
    ]
    if args.limit is not None:
        files = files[: max(0, args.limit)]
    if not files:
        raise SystemExit("no temporal-corpus files matched")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = args.output_dir / "download_ledger.json"
    ledger = load_download_ledger(ledger_path)
    completed: dict[str, dict[str, Any]] = dict(
        ledger.get("files") or {}
    )
    failures: list[dict[str, Any]] = []
    selected_ids = {str(item["source_id"]) for item in files}
    manifest_sha256 = sha256(args.manifest.read_bytes()).hexdigest()
    started = time.monotonic()

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(
                download_and_validate_training_source,
                item,
                temporal_corpus_local_path(args.output_dir, item),
                retries=max(1, args.retries),
                previous=completed.get(str(item["source_id"])),
                excluded_source_sha256=exclusions.source_sha256,
            ): item
            for item in files
        }
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                result = future.result()
                completed[str(item["source_id"])] = result
                if (
                    index % max(1, args.progress_every) == 0
                    or index == len(files)
                ):
                    print(
                        json.dumps(
                            {
                                "download_progress": (
                                    f"{index}/{len(files)}"
                                ),
                                "source_id": item["source_id"],
                                "radar": item["radar"],
                                "split": item["split"],
                                "pulse": item["pulse"],
                                "status": result["status"],
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 - persisted failure.
                completed.pop(str(item["source_id"]), None)
                failure = {
                    "source_id": item.get("source_id"),
                    "radar": item.get("radar"),
                    "split": item.get("split"),
                    "date": item.get("date"),
                    "time": item.get("time"),
                    "pulse": item.get("pulse"),
                    "url": item.get("object_url"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
                failures.append(failure)
                print(json.dumps(failure, sort_keys=True), flush=True)
            if index % CHECKPOINT_INTERVAL == 0:
                _write_ledger(
                    ledger_path,
                    manifest=args.manifest,
                    manifest_sha256=manifest_sha256,
                    selected_ids=selected_ids,
                    selected_splits=wanted_splits,
                    completed=completed,
                    failures=failures,
                    selected_file_count=len(files),
                    elapsed_seconds=time.monotonic() - started,
                    exclusion_digest=exclusions.digest(),
                )

    final = _write_ledger(
        ledger_path,
        manifest=args.manifest,
        manifest_sha256=manifest_sha256,
        selected_ids=selected_ids,
        selected_splits=wanted_splits,
        completed=completed,
        failures=failures,
        selected_file_count=len(files),
        elapsed_seconds=time.monotonic() - started,
        exclusion_digest=exclusions.digest(),
    )
    print(
        json.dumps(
            {
                "selected_splits": list(wanted_splits),
                "selected_file_count": len(files),
                "validated_file_count": final["validated_file_count"],
                "failure_count": len(failures),
                "catalog_size_mismatch_count": final[
                    "catalog_size_mismatch_count"
                ],
                "validated_size_gib": round(
                    final["validated_size_bytes"] / (1024**3),
                    3,
                ),
                "ledger": str(ledger_path),
            },
            sort_keys=True,
        )
    )
    return (
        1
        if failures or final["validated_file_count"] != len(files)
        else 0
    )


def _verify_holdout_gate(
    splits: tuple[str, ...],
    *,
    open_holdout: bool,
    frozen_policy: Path | None,
) -> None:
    if "holdout" not in splits:
        if open_holdout or frozen_policy is not None:
            raise SystemExit(
                "holdout controls are invalid unless holdout is selected"
            )
        return
    if not open_holdout or frozen_policy is None:
        raise SystemExit(
            "holdout download requires --open-holdout and --frozen-policy"
        )
    policy = json.loads(frozen_policy.read_text(encoding="utf-8"))
    if (
        policy.get("status") != "frozen"
        or int(policy.get("holdout_scoring_target_count") or 0) <= 0
    ):
        raise SystemExit(
            "frozen policy does not authorise any holdout targets"
        )


def _write_ledger(
    path: Path,
    *,
    manifest: Path,
    manifest_sha256: str,
    selected_ids: set[str],
    selected_splits: tuple[str, ...],
    completed: dict[str, dict[str, Any]],
    failures: list[dict[str, Any]],
    selected_file_count: int,
    elapsed_seconds: float,
    exclusion_digest: str,
) -> dict[str, Any]:
    selected_results = {
        source_id: result
        for source_id, result in completed.items()
        if source_id in selected_ids
    }
    payload = {
        "schema": "uk_wsr_temporal_context_download_ledger",
        "schema_version": 1,
        "manifest": str(manifest),
        "manifest_sha256": manifest_sha256,
        "selected_splits": list(selected_splits),
        "selected_source_ids_sha256": sha256(
            "\n".join(sorted(selected_ids)).encode("utf-8")
        ).hexdigest(),
        "benchmark_exclusion_digest_sha256": exclusion_digest,
        "generated_at": utc_now(),
        "selected_file_count": selected_file_count,
        "validated_file_count": len(selected_results),
        "validated_size_bytes": sum(
            int(result.get("size_bytes") or 0)
            for result in selected_results.values()
        ),
        "catalog_size_mismatch_count": sum(
            1
            for result in selected_results.values()
            if result.get("catalog_size_match") is False
        ),
        "elapsed_seconds": elapsed_seconds,
        "failures": failures,
        "files": dict(sorted(completed.items())),
    }
    temporary = path.with_suffix(".json.part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
