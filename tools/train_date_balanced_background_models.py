#!/usr/bin/env python3
"""Train qc-v3 date-balanced backgrounds from archive and sequences."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.background_model import (
    BackgroundModelBuildConfig,
    load_background_model,
)
from uk_wsr_visualizer.background_model_v3 import (
    DateBalancedBackgroundConfig,
)
from uk_wsr_visualizer.background_training_pipeline import (
    VerifiedTrainingSource,
    build_sweep_inventory,
    cluster_training_targets,
    file_sha256,
    load_verified_training_sources,
    target_training_summary,
    train_date_balanced_background_target,
)
from uk_wsr_visualizer.temporal_corpus import (
    load_verified_temporal_context_corpus,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-manifest",
        type=Path,
        default=Path("validation/background_training_v2/manifest.json"),
    )
    parser.add_argument(
        "--archive-ledger",
        type=Path,
        default=Path(
            "/tmp/uk_wsr_background_training_v2_pvol/download_ledger.json"
        ),
    )
    parser.add_argument(
        "--temporal-manifest",
        type=Path,
        default=Path("validation/temporal_context_v1/manifest.json"),
    )
    parser.add_argument(
        "--temporal-ledger",
        type=Path,
        default=Path(
            "/tmp/uk_wsr_temporal_context_v1_pvol/download_ledger.json"
        ),
    )
    parser.add_argument(
        "--temporal-integrity",
        type=Path,
        default=Path(
            "validation/temporal_context_v1/"
            "training_validation_integrity.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_background_models_v3"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "reports/background_training_v3/training_results.json"
        ),
    )
    parser.add_argument("--radar", action="append")
    parser.add_argument("--pulse", action="append")
    parser.add_argument("--target-id", action="append")
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    integrity = _verify_temporal_integrity(args)
    base_config = BackgroundModelBuildConfig()
    date_config = DateBalancedBackgroundConfig()
    contract = _training_contract(
        args,
        base_config=base_config,
        date_config=date_config,
        integrity=integrity,
    )
    contract_hash = sha256(
        json.dumps(
            contract,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    archive_sources = tuple(
        source
        for source in load_verified_training_sources(
            args.archive_manifest,
            args.archive_ledger,
            radar=args.radar,
            pulse=args.pulse,
        )
        if source.split == "training"
    )
    temporal = load_verified_temporal_context_corpus(
        args.temporal_manifest,
        args.temporal_ledger,
        splits=("training", "validation"),
        radar=args.radar,
        pulse=args.pulse,
    )
    temporal_sources = tuple(
        source
        for source in temporal.sources
        if source.split == "training"
    )
    sources = _merge_training_sources(
        archive_sources,
        temporal_sources,
    )
    sweeps = build_sweep_inventory(sources, quantity="DBZH")
    targets = list(cluster_training_targets(sweeps))
    wanted_targets = set(args.target_id or [])
    if wanted_targets:
        known = {target.target_id for target in targets}
        missing = wanted_targets - known
        if missing:
            raise SystemExit(
                "unknown target ids: " + ",".join(sorted(missing))
            )
        targets = [
            target
            for target in targets
            if target.target_id in wanted_targets
        ]
    if not targets:
        raise SystemExit("no model targets matched")

    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for index, target in enumerate(targets, start=1):
        try:
            json_path = args.output_dir / f"{target.target_id}.json"
            npz_path = args.output_dir / f"{target.target_id}.npz"
            resumed = False
            model = None
            if args.resume and json_path.is_file() and npz_path.is_file():
                candidate = load_background_model(json_path)
                if (
                    candidate.metadata.get("training_contract_sha256")
                    == contract_hash
                ):
                    model = candidate
                    resumed = True
            if model is None:
                model, npz_path, json_path = (
                    train_date_balanced_background_target(
                        target,
                        args.output_dir,
                        training_contract=contract,
                        training_contract_sha256=contract_hash,
                        base_config=base_config,
                        date_config=date_config,
                    )
                )
            record = target_training_summary(
                target,
                model,
                npz_path,
                json_path,
            ) | {
                "statistics_version": model.metadata.get(
                    "statistics_version"
                ),
                "date_balanced_source_date_count": model.metadata.get(
                    "date_balanced_source_date_count"
                ),
                "training_contract_sha256": contract_hash,
                "resumed": resumed,
            }
            records.append(record)
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(targets)}",
                        "target_id": target.target_id,
                        "training_sources": record[
                            "training_source_count"
                        ],
                        "training_dates": record[
                            "training_date_count"
                        ],
                        "resumed": resumed,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - persisted batch error.
            error = {
                "target_id": target.target_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(error)
            print(json.dumps(error, sort_keys=True), flush=True)
            if not args.keep_going:
                _write_report(
                    args.report,
                    contract=contract,
                    contract_hash=contract_hash,
                    sources=sources,
                    target_count=len(targets),
                    records=records,
                    errors=errors,
                    complete=False,
                )
                raise
        _write_report(
            args.report,
            contract=contract,
            contract_hash=contract_hash,
            sources=sources,
            target_count=len(targets),
            records=records,
            errors=errors,
            complete=index == len(targets),
        )
    return 1 if errors else 0


def _merge_training_sources(
    *groups: tuple[VerifiedTrainingSource, ...],
) -> tuple[VerifiedTrainingSource, ...]:
    merged: dict[str, VerifiedTrainingSource] = {}
    for source in (item for group in groups for item in group):
        previous = merged.get(source.source_id)
        if previous is not None and (
            previous.sha256 != source.sha256
            or previous.object_url != source.object_url
        ):
            raise ValueError(
                f"training source conflict for {source.source_id}"
            )
        merged.setdefault(source.source_id, source)
    return tuple(
        sorted(
            merged.values(),
            key=lambda source: (
                source.radar,
                source.pulse,
                source.date,
                source.time,
                source.source_id,
            ),
        )
    )


def _training_contract(
    args: argparse.Namespace,
    *,
    base_config: BackgroundModelBuildConfig,
    date_config: DateBalancedBackgroundConfig,
    integrity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": "uk_wsr_background_training_v3_contract",
        "schema_version": 2,
        "archive_manifest_sha256": file_sha256(args.archive_manifest),
        "archive_ledger_sha256": file_sha256(args.archive_ledger),
        "temporal_manifest_sha256": file_sha256(args.temporal_manifest),
        "temporal_ledger_sha256": file_sha256(args.temporal_ledger),
        "temporal_integrity_sha256": file_sha256(
            args.temporal_integrity
        ),
        "temporal_source_snapshot_sha256": integrity[
            "source_snapshot_sha256"
        ],
        "implementation_sha256": {
            "train_date_balanced_background_models.py": file_sha256(
                Path(__file__)
            ),
            **{
                name: file_sha256(
                    Path(__file__).parents[1]
                    / "src"
                    / "uk_wsr_visualizer"
                    / name
                )
                for name in (
                    "background_model.py",
                    "background_model_v3.py",
                    "background_training_pipeline.py",
                    "temporal_corpus.py",
                )
            },
        },
        "archive_partition": "training",
        "temporal_partition": "training",
        "deduplication_key": "source_id_with_sha256_and_url_equality",
        "base_config": asdict(base_config),
        "date_balanced_config": asdict(date_config),
        "promotion_eligible": False,
    }


def _verify_temporal_integrity(
    args: argparse.Namespace,
) -> dict[str, Any]:
    report = json.loads(
        args.temporal_integrity.read_text(encoding="utf-8")
    )
    errors = []
    if report.get("integrity_passed") is not True:
        errors.append("integrity report did not pass")
    if report.get("manifest_sha256") != file_sha256(
        args.temporal_manifest
    ):
        errors.append("integrity report manifest hash mismatch")
    if report.get("ledger_sha256") != file_sha256(
        args.temporal_ledger
    ):
        errors.append("integrity report ledger hash mismatch")
    if set(report.get("selected_splits") or ()) != {
        "training",
        "validation",
    }:
        errors.append("integrity report has unexpected partitions")
    if (report.get("holdout") or {}).get("sealed") is not True:
        errors.append("integrity report does not prove sealed holdout")
    if len(str(report.get("source_snapshot_sha256") or "")) != 64:
        errors.append("integrity report has no source snapshot hash")
    if errors:
        raise SystemExit(
            "invalid temporal integrity report: " + "; ".join(errors)
        )
    return report


def _write_report(
    path: Path,
    *,
    contract: dict[str, Any],
    contract_hash: str,
    sources: tuple[VerifiedTrainingSource, ...],
    target_count: int,
    records: list[dict[str, Any]],
    errors: list[dict[str, str]],
    complete: bool,
) -> None:
    payload = {
        "schema": "uk_wsr_background_training_v3_results",
        "schema_version": 1,
        "training_contract": contract,
        "training_contract_sha256": contract_hash,
        "source_count": len(sources),
        "source_date_count": len(
            {(source.radar, source.date) for source in sources}
        ),
        "target_count": target_count,
        "trained_target_count": len(records),
        "error_count": len(errors),
        "complete": bool(
            complete
            and len(records) + len(errors) == target_count
            and not errors
        ),
        "promotion_eligible": False,
        "records": records,
        "errors": errors,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
