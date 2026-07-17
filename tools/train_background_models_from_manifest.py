#!/usr/bin/env python3
"""Train research background models from the verified multi-date corpus."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_training_pipeline import (
    build_sweep_inventory,
    cluster_training_targets,
    file_sha256,
    load_verified_training_sources,
    target_training_summary,
    train_background_target,
    training_inventory_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("validation/background_training_v2/manifest.json"),
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(
            "/tmp/uk_wsr_background_training_v2_pvol/download_ledger.json"
        ),
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_background_models_v2"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/background_training_v2"),
    )
    parser.add_argument("--radar", action="append")
    parser.add_argument("--pulse", action="append")
    parser.add_argument("--quantity", default="DBZH")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    sources = load_verified_training_sources(
        args.manifest,
        args.ledger,
        radar=args.radar,
        pulse=args.pulse,
    )
    sweeps = build_sweep_inventory(sources, quantity=args.quantity)
    targets = cluster_training_targets(sweeps)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    manifest_hash = file_sha256(args.manifest)
    ledger_hash = file_sha256(args.ledger)
    inventory = training_inventory_manifest(
        sources,
        sweeps,
        targets,
        source_manifest_sha256=manifest_hash,
        ledger_sha256=ledger_hash,
    )
    inventory_path = args.report_dir / "inventory.json"
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source_count": len(sources),
                "sweep_count": len(sweeps),
                "target_count": len(targets),
                "inventory": str(inventory_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if args.inventory_only:
        return 0

    summaries: list[dict] = []
    errors: list[dict[str, str]] = []
    report_path = args.report_dir / "training_results.json"
    for index, target in enumerate(targets, start=1):
        try:
            npz_path = args.model_dir / f"{target.target_id}.npz"
            json_path = args.model_dir / f"{target.target_id}.json"
            resumed = False
            if args.resume and npz_path.is_file() and json_path.is_file():
                model = load_background_model(json_path)
                if (
                    model.key.get("geometry_id") != target.target_id
                    or model.metadata.get("source_manifest_sha256")
                    != manifest_hash
                    or model.metadata.get("download_ledger_sha256")
                    != ledger_hash
                ):
                    raise ValueError(
                        "existing model does not match current target/corpus"
                    )
                resumed = True
            else:
                model, npz_path, json_path = train_background_target(
                    target,
                    args.model_dir,
                    source_manifest_sha256=manifest_hash,
                    ledger_sha256=ledger_hash,
                )
            summary = target_training_summary(
                target,
                model,
                npz_path,
                json_path,
            )
            summary["resumed"] = resumed
            summaries.append(summary)
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(targets)}",
                        "target_id": target.target_id,
                        "training_source_count": summary[
                            "training_source_count"
                        ],
                        "conditioned_support_gate_fraction": summary[
                            "conditioned_support_gate_fraction"
                        ],
                        "status": summary["status"],
                        "resumed": resumed,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - batch report records failures.
            error = {
                "target_id": target.target_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(error)
            print(json.dumps(error, sort_keys=True), flush=True)
            if not args.keep_going:
                raise
        _write_training_report(
            report_path,
            inventory_path=inventory_path,
            manifest_hash=manifest_hash,
            ledger_hash=ledger_hash,
            model_dir=args.model_dir,
            target_count=len(targets),
            summaries=summaries,
            errors=errors,
            all_targets_attempted=index == len(targets),
        )

    return 1 if errors else 0


def _write_training_report(
    path: Path,
    *,
    inventory_path: Path,
    manifest_hash: str,
    ledger_hash: str,
    model_dir: Path,
    target_count: int,
    summaries: list[dict],
    errors: list[dict[str, str]],
    all_targets_attempted: bool,
) -> None:
    report = {
        "schema": "uk_wsr_background_training_results",
        "schema_version": 1,
        "generated_at": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "all_targets_attempted": all_targets_attempted,
        "complete": all_targets_attempted and not errors,
        "inventory": str(inventory_path),
        "source_manifest_sha256": manifest_hash,
        "download_ledger_sha256": ledger_hash,
        "model_dir": str(model_dir),
        "target_count": target_count,
        "trained_model_count": len(summaries),
        "error_count": len(errors),
        "promotion_eligible_model_count": 0,
        "models": summaries,
        "errors": errors,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
