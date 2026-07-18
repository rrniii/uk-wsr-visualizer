#!/usr/bin/env python3
"""Inject exact nuisances around conservative anchors in real UK WSR sweeps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_training_pipeline import file_sha256
from uk_wsr_visualizer.export_types import FieldSelection
from uk_wsr_visualizer.geospatial import read_polar_field_with_companions
from uk_wsr_visualizer.qc_synthetic_validation import (
    SemiSyntheticBaseCase,
    run_real_semi_synthetic_validation,
    select_signal_rich_semi_synthetic_records,
    write_real_semi_synthetic_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-results",
        type=Path,
        default=Path(
            "reports/background_validation_v3_candidate5/"
            "validation_results.json"
        ),
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(
            "/private/tmp/uk_wsr_background_training_v2_pvol/"
            "download_ledger.json"
        ),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            "/private/tmp/uk_wsr_qc_real_semi_synthetic_candidate5"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "reports/qc_real_semi_synthetic_candidate5"
        ),
    )
    parser.add_argument("--seed-start", type=int, default=5000)
    parser.add_argument(
        "--context-mode",
        choices=("persistent_static", "coverage_only_dynamic"),
        default="persistent_static",
    )
    args = parser.parse_args()

    validation = json.loads(
        args.validation_results.read_text(encoding="utf-8")
    )
    if validation.get("complete") is not True:
        raise SystemExit(
            "semi-synthetic selection requires complete validation"
        )
    selected = select_signal_rich_semi_synthetic_records(
        validation.get("records") or []
    )
    if not selected:
        raise SystemExit("no PPI validation records were selected")

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    ledger_files = ledger.get("files", {})
    rows = (
        list(ledger_files.values())
        if isinstance(ledger_files, dict)
        else list(ledger_files)
    )
    sources = {str(row["source_id"]): row for row in rows}
    source_hashes: dict[Path, str] = {}
    cases = []
    for index, record in enumerate(selected, start=1):
        source_id = str(record["source"]["source_id"])
        source = sources[source_id]
        source_path = Path(source["local_path"])
        source_hashes.setdefault(source_path, file_sha256(source_path))
        if source_hashes[source_path] != record["source"]["sha256"]:
            raise ValueError(f"{source_id} source hash changed")
        dbzh, metadata, companions = read_polar_field_with_companions(
            source_path,
            str(record["radar"]),
            str(record["source"]["date"]),
            FieldSelection(
                pulse=str(record["pulse"]),
                time=str(record["source"]["time"]),
                quantity=str(record["quantity"]),
                dataset=str(record["source"]["dataset"]),
            ),
        )
        if tuple(dbzh.shape) != tuple(record["shape"]):
            raise ValueError(f"{source_id} sweep shape changed")
        if (
            metadata.elevation_deg is None
            or abs(
                float(metadata.elevation_deg)
                - float(record["elevation_deg"])
            )
            > 0.075
        ):
            raise ValueError(f"{source_id} elevation changed")
        cases.append(
            SemiSyntheticBaseCase(
                case_id=str(record["job_id"]),
                radar=str(record["radar"]),
                pulse=str(record["pulse"]),
                elevation_deg=float(record["elevation_deg"]),
                source_id=source_id,
                source_sha256=str(record["source"]["sha256"]),
                dataset=str(record["source"]["dataset"]),
                date=str(record["source"]["date"]),
                time=str(record["source"]["time"]),
                rstart_km=float(record["rstart_km"]),
                rscale_m=float(record["rscale_m"]),
                dbzh=dbzh,
                companions=companions,
            )
        )
        print(
            json.dumps(
                {
                    "loaded": f"{index}/{len(selected)}",
                    "job_id": record["job_id"],
                    "radar": record["radar"],
                    "pulse": record["pulse"],
                },
                sort_keys=True,
            ),
            flush=True,
        )

    run = run_real_semi_synthetic_validation(
        cases,
        seed_start=args.seed_start,
        context_mode=args.context_mode,
    )
    written = write_real_semi_synthetic_validation(
        run,
        args.output_dir,
        artifact_root=args.artifact_root,
    )
    summary = run.report["summary"]["all"]
    print(
        json.dumps(
            {
                "case_count": run.report["case_count"],
                "radar_count": run.report["radar_count"],
                "precision": summary["precision"],
                "artifact_recall": summary["artifact_recall"],
                "retain_recall": summary["retain_recall"],
                "high_signal_retain_recall": summary[
                    "high_signal_retain_recall"
                ],
                "validation_gate_passed": run.report[
                    "validation_gate_passed"
                ],
                "context_mode": args.context_mode,
                "written": [str(path) for path in written],
            },
            sort_keys=True,
        )
    )
    return 0 if run.report["validation_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
