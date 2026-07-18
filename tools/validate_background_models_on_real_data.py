#!/usr/bin/env python3
"""Score learned-background models on disjoint real PVOL validation data."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_training_pipeline import (
    build_sweep_inventory,
    cluster_training_targets,
    file_sha256,
    load_verified_training_sources,
)
from uk_wsr_visualizer.background_validation_pipeline import (
    DEFAULT_TEMPORAL_GAP_MINUTES,
    BackgroundValidationModelResolver,
    ValidationSweepReadCache,
    build_background_validation_jobs,
    evaluate_background_validation_job,
    load_resumable_validation_record,
    validation_configuration_contract,
    write_background_validation_artifact,
    write_background_validation_report,
)
from uk_wsr_visualizer.qc_evidence import EvidenceConfig
from uk_wsr_visualizer.temporal_corpus import (
    load_verified_temporal_context_corpus,
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
        "--artifact-root",
        type=Path,
        default=Path("/tmp/uk_wsr_background_validation_v2"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/background_validation_v2"),
    )
    parser.add_argument("--temporal-manifest", type=Path)
    parser.add_argument("--temporal-ledger", type=Path)
    parser.add_argument(
        "--split",
        choices=("validation", "holdout"),
        default="validation",
    )
    parser.add_argument("--frozen-policy", type=Path)
    parser.add_argument("--radar", action="append")
    parser.add_argument("--pulse", action="append")
    parser.add_argument("--target-id", action="append")
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument(
        "--stratified",
        action="store_true",
        help=(
            "Select capped runs round-robin across radar, target, season, and "
            "day/night bucket instead of taking the first sorted jobs."
        ),
    )
    parser.add_argument(
        "--max-temporal-gap-minutes",
        type=int,
        default=DEFAULT_TEMPORAL_GAP_MINUTES,
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument(
        "--read-cache-entries",
        type=int,
        default=8,
        help="Bounded verified sweep-read LRU size; zero disables caching.",
    )
    args = parser.parse_args()
    if bool(args.temporal_manifest) != bool(args.temporal_ledger):
        raise SystemExit(
            "--temporal-manifest and --temporal-ledger are required together"
        )

    config = EvidenceConfig()
    temporal_manifest_hash = (
        file_sha256(args.temporal_manifest)
        if args.temporal_manifest is not None
        else None
    )
    configuration, configuration_hash = (
        validation_configuration_contract(
            config,
            max_temporal_gap_minutes=args.max_temporal_gap_minutes,
            temporal_manifest_sha256=temporal_manifest_hash,
        )
    )
    frozen_policy_hash = _verify_frozen_policy(
        args.frozen_policy,
        split=args.split,
        configuration_sha256=configuration_hash,
    )

    eligible_source_ids: set[str] | None = None
    if args.temporal_manifest is not None:
        ledger_payload = json.loads(
            args.temporal_ledger.read_text(encoding="utf-8")
        )
        ledger_splits = tuple(
            str(value)
            for value in ledger_payload.get("selected_splits") or []
        )
        if args.split not in ledger_splits:
            raise SystemExit(
                f"temporal ledger does not contain {args.split}"
            )
        corpus = load_verified_temporal_context_corpus(
            args.temporal_manifest,
            args.temporal_ledger,
            splits=ledger_splits,
            radar=args.radar,
            pulse=args.pulse,
        )
        sources = corpus.sources
        eligible_source_ids = {
            source_id
            for sequence in corpus.sequences
            if sequence.split == args.split
            for source_id in sequence.eligible_scoring_source_ids
        }
    else:
        sources = load_verified_training_sources(
            args.manifest,
            args.ledger,
            radar=args.radar,
            pulse=args.pulse,
        )
    sweeps = build_sweep_inventory(sources, quantity="DBZH")
    targets = list(cluster_training_targets(sweeps))
    jobs = list(
        build_background_validation_jobs(
            targets,
            split=args.split,
            max_temporal_gap_minutes=args.max_temporal_gap_minutes,
            eligible_source_ids=eligible_source_ids,
        )
    )
    wanted_targets = set(args.target_id or [])
    if wanted_targets:
        known_targets = {target.target_id for target in targets}
        missing = wanted_targets - known_targets
        if missing:
            raise SystemExit(
                "unknown target ids: " + ",".join(sorted(missing))
            )
        jobs = [
            job
            for job in jobs
            if job.target.target_id in wanted_targets
        ]
    if args.max_jobs is not None:
        maximum = max(0, args.max_jobs)
        jobs = (
            _stratified_jobs(jobs, maximum)
            if args.stratified
            else jobs[:maximum]
        )
    if not jobs:
        raise SystemExit("no validation jobs matched")

    report_path = args.report_dir / f"{args.split}_results.json"
    records: list[dict] = []
    errors: list[dict[str, str]] = []
    checkpoint_every = max(1, int(args.checkpoint_every))
    read_cache = ValidationSweepReadCache(args.read_cache_entries)
    model_resolver = BackgroundValidationModelResolver(args.model_dir)
    loaded_model_target: str | None = None
    loaded_model = None
    for index, job in enumerate(jobs, start=1):
        try:
            if loaded_model_target != job.target.target_id:
                model_path = model_resolver.resolve_path(job.target)
                loaded_model = load_background_model(model_path)
                loaded_model_target = job.target.target_id
            model = loaded_model
            if model is None:
                raise RuntimeError("background model cache is empty")
            sidecar_path = (
                args.artifact_root
                / args.split
                / job.target.target_id
                / f"{job.sweep.source_id}.npz.json"
            )
            record = (
                load_resumable_validation_record(
                    sidecar_path,
                    source_sha256=job.sweep.sha256,
                    model_array_hash=model.array_hash,
                    configuration_sha256=configuration_hash,
                )
                if args.resume
                else None
            )
            resumed = record is not None
            if record is None:
                evaluation = evaluate_background_validation_job(
                    job,
                    model,
                    config=config,
                    configuration_sha256=configuration_hash,
                    read_cache=read_cache,
                )
                npz_path, written_sidecar, sidecar = (
                    write_background_validation_artifact(
                        evaluation,
                        args.artifact_root,
                        configuration_contract=configuration,
                    )
                )
                record = dict(evaluation.record) | {
                    "artifact_npz": str(npz_path),
                    "artifact_sidecar": str(written_sidecar),
                    "artifact_sha256": sidecar["artifact_sha256"],
                    "artifact_array_hash": sidecar["array_hash"],
                    "resumed": False,
                }
            records.append(record)
            print(
                json.dumps(
                    {
                        "progress": f"{index}/{len(jobs)}",
                        "job_id": job.job_id,
                        "removed_fraction": record["learned"][
                            "removed_fraction"
                        ],
                        "learned_increment_fraction": record["delta"][
                            "learned_increment_fraction"
                        ],
                        "upper_context": record["context"][
                            "upper_elevation_available"
                        ],
                        "temporal_context": record["context"][
                            "temporal_available"
                        ],
                        "resumed": resumed,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - batch records failures.
            error = {
                "job_id": job.job_id,
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(error)
            print(json.dumps(error, sort_keys=True), flush=True)
            if not args.keep_going:
                _write_report(
                    report_path,
                    args=args,
                    jobs=jobs,
                    records=records,
                    errors=errors,
                    configuration=configuration,
                    configuration_hash=configuration_hash,
                    frozen_policy_hash=frozen_policy_hash,
                    all_jobs_attempted=False,
                )
                raise

        if (
            index % checkpoint_every == 0
            or index == len(jobs)
        ):
            _write_report(
                report_path,
                args=args,
                jobs=jobs,
                records=records,
                errors=errors,
                configuration=configuration,
                configuration_hash=configuration_hash,
                frozen_policy_hash=frozen_policy_hash,
                all_jobs_attempted=index == len(jobs),
            )
    print(
        json.dumps(
            {
                "read_cache": read_cache.statistics(),
                "target_model_load_count": len(
                    {job.target.target_id for job in jobs}
                ),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 1 if errors else 0


def _stratified_jobs(jobs: list, maximum: int) -> list:
    """Select a capped validation set without radar or target ordering bias."""

    if maximum <= 0:
        return []
    target_jobs: dict[str, deque] = {}
    targets_by_radar: dict[str, list[str]] = defaultdict(list)
    grouped: dict[str, list] = defaultdict(list)
    for job in jobs:
        grouped[job.target.target_id].append(job)
    for target_id, target_group in grouped.items():
        ordered = sorted(target_group, key=_job_diversity_key)
        target_jobs[target_id] = deque(ordered)
        targets_by_radar[ordered[0].target.radar].append(target_id)

    radar_queues = {
        radar: deque(sorted(target_ids))
        for radar, target_ids in targets_by_radar.items()
    }
    selected: list = []
    while len(selected) < maximum and any(radar_queues.values()):
        for radar in sorted(radar_queues):
            queue = radar_queues[radar]
            if not queue or len(selected) >= maximum:
                continue
            target_id = queue.popleft()
            candidates = target_jobs[target_id]
            selected.append(candidates.popleft())
            if candidates:
                queue.append(target_id)
    return selected


def _job_diversity_key(job: object) -> tuple[int, int, str, str]:
    sweep = job.sweep
    month = datetime.strptime(str(sweep.date), "%Y%m%d").month
    season = (month % 12) // 3
    minutes = int(str(sweep.time)[:2]) * 60 + int(str(sweep.time)[2:])
    time_bucket = 0 if 6 * 60 <= minutes < 19 * 60 else 1
    return (season, time_bucket, str(sweep.date), str(sweep.time))


def _verify_frozen_policy(
    path: Path | None,
    *,
    split: str,
    configuration_sha256: str,
) -> str | None:
    if split == "validation":
        if path is not None:
            raise SystemExit(
                "--frozen-policy is only accepted for the holdout split"
            )
        return None
    if path is None:
        raise SystemExit(
            "holdout scoring requires --frozen-policy from validation"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "frozen":
        raise SystemExit("holdout policy is not frozen")
    if payload.get("configuration_sha256") != configuration_sha256:
        raise SystemExit(
            "holdout policy configuration hash does not match candidate"
        )
    return file_sha256(path)


def _write_report(
    path: Path,
    *,
    args: argparse.Namespace,
    jobs: list,
    records: list[dict],
    errors: list[dict[str, str]],
    configuration: dict,
    configuration_hash: str,
    frozen_policy_hash: str | None,
    all_jobs_attempted: bool,
) -> None:
    write_background_validation_report(
        path,
        split=args.split,
        expected_job_count=len(jobs),
        records=records,
        errors=errors,
        configuration_contract=configuration,
        configuration_sha256=configuration_hash,
        artifact_root=args.artifact_root,
        all_jobs_attempted=all_jobs_attempted,
        frozen_policy_sha256=frozen_policy_hash,
    )


if __name__ == "__main__":
    raise SystemExit(main())
