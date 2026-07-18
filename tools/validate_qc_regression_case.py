#!/usr/bin/env python3
"""Validate one named real-data QC regression case with exact context."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_training_pipeline import (
    DEFAULT_ELEVATION_TOLERANCE_DEG,
    VerifiedTrainingSource,
    build_sweep_inventory,
    cluster_training_targets,
    file_sha256,
)
from uk_wsr_visualizer.background_validation_pipeline import (
    BackgroundValidationModelResolver,
    build_background_validation_jobs,
    evaluate_background_validation_job,
    validation_configuration_contract,
    write_background_validation_artifact,
    write_background_validation_report,
)
from uk_wsr_visualizer.qc_evidence import EvidenceConfig


TIME_PATTERN = re.compile(r"_(?P<time>[0-2][0-9][0-5][0-9])\.h5$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--radar", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--pulse", choices=("lp", "sp"), required=True)
    parser.add_argument("--elevation", type=float, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--next", type=Path, required=True)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_background_models_v3_candidate4"),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("/tmp/uk_wsr_qc_regression_cases"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/qc_regression_cases/validation_results.json"),
    )
    args = parser.parse_args()

    sources = tuple(
        _verified_source(
            path,
            name=args.name,
            radar=args.radar,
            pulse=args.pulse,
            date=args.date,
        )
        for path in (args.previous, args.current, args.next)
    )
    targets = cluster_training_targets(build_sweep_inventory(sources))
    current_source_id = sources[1].source_id
    jobs = [
        job
        for job in build_background_validation_jobs(
            targets,
            split="validation",
            eligible_source_ids=(current_source_id,),
        )
        if abs(job.target.elevation_deg - args.elevation)
        <= DEFAULT_ELEVATION_TOLERANCE_DEG
    ]
    if len(jobs) != 1:
        raise SystemExit(
            f"expected one {args.elevation:g}-degree target; found {len(jobs)}"
        )
    job = jobs[0]
    if job.previous_sweep is None or job.next_sweep is None:
        raise SystemExit("regression case does not have complete temporal context")

    config = EvidenceConfig()
    configuration, configuration_sha256 = (
        validation_configuration_contract(
            config,
            max_temporal_gap_minutes=20,
        )
    )
    model_path = BackgroundValidationModelResolver(
        args.model_dir
    ).resolve_path(job.target)
    model = load_background_model(model_path)
    evaluation = evaluate_background_validation_job(
        job,
        model,
        config=config,
        configuration_sha256=configuration_sha256,
    )
    npz_path, sidecar_path, sidecar = (
        write_background_validation_artifact(
            evaluation,
            args.artifact_root / args.name,
            configuration_contract=configuration,
        )
    )
    record = dict(evaluation.record) | {
        "regression_name": args.name,
        "artifact_npz": str(npz_path),
        "artifact_sidecar": str(sidecar_path),
        "artifact_sha256": sidecar["artifact_sha256"],
        "artifact_array_hash": sidecar["array_hash"],
        "resumed": False,
    }
    write_background_validation_report(
        args.output,
        split="validation",
        expected_job_count=1,
        records=[record],
        errors=[],
        configuration_contract=configuration,
        configuration_sha256=configuration_sha256,
        artifact_root=args.artifact_root / args.name,
        all_jobs_attempted=True,
    )
    print(
        json.dumps(
            {
                "name": args.name,
                "job_id": job.job_id,
                "target_id": job.target.target_id,
                "model": str(model_path),
                "removed_fraction": record["learned"]["removed_fraction"],
                "learned_increment_fraction": record["delta"][
                    "learned_increment_fraction"
                ],
                "maximum_removed_dbzh": record["learned"]["removed_dbzh"][
                    "maximum"
                ],
                "temporal_context": record["context"]["temporal_available"],
                "upper_context": record["context"][
                    "upper_elevation_available"
                ],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def _verified_source(
    path: Path,
    *,
    name: str,
    radar: str,
    pulse: str,
    date: str,
) -> VerifiedTrainingSource:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    match = TIME_PATTERN.search(source.name)
    if match is None:
        raise ValueError(f"cannot parse scan time from {source.name}")
    time = match.group("time")
    digest = file_sha256(source)
    return VerifiedTrainingSource(
        source_id=f"{name}-{time}-{digest[:16]}",
        radar=radar,
        pulse=pulse,
        split="validation",
        date=date,
        time=time,
        local_path=str(source),
        object_url=source.as_uri(),
        object_key=None,
        sha256=digest,
        size_bytes=source.stat().st_size,
        season=None,
        utc_slot=None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
