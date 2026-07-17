#!/usr/bin/env python3
"""Compare pinned community QC methods on exact real validation sweeps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_training_pipeline import file_sha256
from uk_wsr_visualizer.community_baselines import (
    DEFAULT_COMMUNITY_CASE_COUNT,
    COMMUNITY_BASELINE_METHODS,
    community_method_metrics,
    run_community_baselines,
    select_community_baseline_records,
    write_community_baseline_artifact,
    write_community_baseline_report,
)
from uk_wsr_visualizer.export_types import FieldSelection
from uk_wsr_visualizer.geospatial import read_polar_field_with_companions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-results",
        type=Path,
        default=Path(
            "reports/background_validation_v2_upper_fail_open/"
            "validation_results.json"
        ),
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
        "--artifact-root",
        type=Path,
        default=Path("/tmp/uk_wsr_community_baselines_v1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/background_validation_v2_upper_fail_open/"
            "community_baselines.json"
        ),
    )
    parser.add_argument(
        "--case-count",
        type=int,
        default=DEFAULT_COMMUNITY_CASE_COUNT,
    )
    parser.add_argument("--all-ppi", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    validation = json.loads(
        args.validation_results.read_text(encoding="utf-8")
    )
    if validation.get("complete") is not True:
        raise SystemExit("community comparison requires complete validation")
    all_records = list(validation.get("records") or [])
    selected = (
        tuple(
            row
            for row in all_records
            if row.get("geometry_class") == "ppi"
        )
        if args.all_ppi
        else select_community_baseline_records(
            all_records,
            case_count=args.case_count,
        )
    )
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    ledger_files = ledger.get("files", {})
    if isinstance(ledger_files, dict):
        ledger_rows = list(ledger_files.values())
    elif isinstance(ledger_files, list):
        ledger_rows = ledger_files
    else:
        raise SystemExit("download ledger files are not a list or object")
    sources = {
        str(item["source_id"]): item
        for item in ledger_rows
    }
    source_hash_cache: dict[Path, str] = {}
    records: list[dict] = []
    errors: list[dict[str, str]] = []
    versions: dict[str, str] = {}
    for index, validation_record in enumerate(selected, start=1):
        job_id = str(validation_record["job_id"])
        try:
            source_id = str(validation_record["source"]["source_id"])
            source_entry = sources[source_id]
            source_path = Path(source_entry["local_path"])
            if source_path not in source_hash_cache:
                source_hash_cache[source_path] = file_sha256(source_path)
            source_hash = source_hash_cache[source_path]
            if source_hash != validation_record["source"]["sha256"]:
                raise ValueError("source file hash changed")
            selection = FieldSelection(
                pulse=str(validation_record["pulse"]),
                time=str(validation_record["source"]["time"]),
                quantity=str(validation_record["quantity"]),
                dataset=str(validation_record["source"]["dataset"]),
            )
            dbzh, metadata, companions = read_polar_field_with_companions(
                source_path,
                str(validation_record["radar"]),
                str(validation_record["source"]["date"]),
                selection,
            )
            if tuple(dbzh.shape) != tuple(validation_record["shape"]):
                raise ValueError("source geometry no longer matches validation")
            model = load_background_model(
                args.model_dir / f"{validation_record['target_id']}.json"
            )
            result = run_community_baselines(
                dbzh,
                companions,
                model,
                elevation_deg=float(metadata.elevation_deg),
            )
            if versions and versions != result.versions:
                raise ValueError("community dependency versions changed")
            versions = result.versions
            with __import__("numpy").load(
                validation_record["artifact_npz"],
                allow_pickle=False,
            ) as candidate:
                candidate_arrays = {
                    name: candidate[name]
                    for name in (
                        "learned_remove_mask",
                        "learned_increment_mask",
                        "learned_protected_mask",
                        "learned_evidence_mask",
                    )
                }
            npz_path, sidecar_path, sidecar = (
                write_community_baseline_artifact(
                    result,
                    args.artifact_root,
                    validation_record=validation_record,
                )
            )
            methods = {}
            for method in COMMUNITY_BASELINE_METHODS:
                method_status = result.method_status[method]
                method_record = dict(method_status)
                if method_status["status"] == "scored":
                    method_record["metrics"] = community_method_metrics(
                        dbzh,
                        result.arrays[method],
                        candidate_remove_mask=candidate_arrays[
                            "learned_remove_mask"
                        ],
                        candidate_increment_mask=candidate_arrays[
                            "learned_increment_mask"
                        ],
                        candidate_protected_mask=candidate_arrays[
                            "learned_protected_mask"
                        ],
                        candidate_evidence_mask=candidate_arrays[
                            "learned_evidence_mask"
                        ],
                    )
                methods[method] = method_record
            record = {
                "job_id": job_id,
                "target_id": validation_record["target_id"],
                "radar": validation_record["radar"],
                "pulse": validation_record["pulse"],
                "quantity": validation_record["quantity"],
                "geometry_class": validation_record["geometry_class"],
                "elevation_deg": validation_record["elevation_deg"],
                "shape": validation_record["shape"],
                "source": validation_record["source"],
                "validation_artifact_sha256": validation_record[
                    "artifact_sha256"
                ],
                "model_array_hash": model.array_hash,
                "community_artifact_npz": str(npz_path),
                "community_artifact_sidecar": str(sidecar_path),
                "community_artifact_sha256": sidecar[
                    "artifact_sha256"
                ],
                "community_array_hash": sidecar["array_hash"],
                "methods": methods,
                "promotion_eligible": False,
            }
            records.append(record)
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(selected)}",
                        "job_id": job_id,
                        "radar": validation_record["radar"],
                        "pulse": validation_record["pulse"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - batch records failures.
            error = {
                "job_id": job_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(error)
            print(json.dumps(error, sort_keys=True), flush=True)
            if not args.keep_going:
                raise

    selection_record = {
        "mode": "all_ppi" if args.all_ppi else "stratified_footprint",
        "requested_case_count": (
            len(selected) if args.all_ppi else int(args.case_count)
        ),
        "selected_case_count": len(selected),
        "ppi_only": True,
        "selection_rule": (
            "per radar/pulse maximum learned increment, maximum total "
            "removal, and low-removal control; remaining slots use maximum "
            "learned-only linear reflectivity risk"
        ),
        "radar_count": len({row["radar"] for row in selected}),
        "pulse_counts": {
            pulse: sum(row["pulse"] == pulse for row in selected)
            for pulse in ("lp", "sp")
        },
    }
    destination = write_community_baseline_report(
        args.output,
        validation_results=args.validation_results,
        validation_results_sha256=file_sha256(args.validation_results),
        selection=selection_record,
        versions=versions,
        records=records,
        errors=errors,
        artifact_root=args.artifact_root,
    )
    print(
        json.dumps(
            {
                "complete": not errors and len(records) == len(selected),
                "scored_case_count": len(records),
                "error_count": len(errors),
                "versions": versions,
                "output": str(destination),
            },
            sort_keys=True,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
