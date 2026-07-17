"""Reproducible exact-mask comparison of UK WSR nuisance filters."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .dependencies import require_numpy, require_pillow
from .background_model import (
    BackgroundScan,
    build_background_model,
)
from .preview import apply_palette
from .qc import QCConfig, QCMaskFlag, build_qc_mask
from .qc_evidence import (
    EVIDENCE_VERSION,
    EvidenceConfig,
    EvidenceContext,
    NuisanceFlag,
    classify_nuisance_echoes,
)
from .qc_synthetic import (
    SyntheticConfig,
    SyntheticScene,
    SyntheticTruthFlag,
    evaluate_predicted_removal,
    generate_synthetic_scene,
)

VALIDATION_SCHEMA_VERSION = 1
CURRENT_METHOD = "qc-v2-current-default"
CANDIDATE_METHOD = EVIDENCE_VERSION
LEARNED_CANDIDATE_METHOD = f"{EVIDENCE_VERSION}-learned-prior"
METHOD_COLORS = {
    CURRENT_METHOD: "#6b7f8c",
    CANDIDATE_METHOD: "#268a5b",
    LEARNED_CANDIDATE_METHOD: "#a34c2b",
}
METHOD_LABELS = {
    CURRENT_METHOD: "Current qc-v2",
    CANDIDATE_METHOD: "Candidate",
    LEARNED_CANDIDATE_METHOD: "Candidate + learned prior",
}
UTC_TIMES = ("0000", "0400", "0800", "1200", "1800", "2200")
PROMOTION_GATES = {
    "precision_min": 0.995,
    "retain_recall_min": 0.9995,
    "high_signal_retain_recall_min": 1.0,
    "artifact_recall_improvement_min": 0.10,
}
LEARNED_PRIOR_GATES = {
    "precision_min": 0.995,
    "retain_recall_min": 0.9995,
    "static_clutter_recall_min": 0.90,
    "static_clutter_recall_gain_min": 0.50,
    "artifact_recall_non_regression_tolerance": 0.0,
}


@dataclass
class SyntheticValidationRun:
    report: dict[str, Any]
    examples: dict[str, dict[str, Any]]


@dataclass
class LearnedPriorSyntheticValidationRun:
    report: dict[str, Any]
    examples: dict[str, dict[str, Any]]


def run_synthetic_validation(
    *,
    seeds: Iterable[int] = range(12),
    nrays: int = 180,
    nbins: int = 220,
) -> SyntheticValidationRun:
    """Evaluate the shipped default and multi-evidence candidate exactly."""

    np = require_numpy()
    selected_seeds = [int(seed) for seed in seeds]
    if not selected_seeds:
        raise ValueError("at least one synthetic seed is required")
    records: list[dict[str, Any]] = []
    examples: dict[str, dict[str, Any]] = {}
    for pulse in ("lp", "sp"):
        for seed in selected_seeds:
            scene = generate_synthetic_scene(
                SyntheticConfig(
                    pulse=pulse,
                    nrays=int(nrays),
                    nbins=int(nbins),
                ),
                seed=seed,
            )
            current_prediction, current_counts = _current_qc_prediction(scene)
            candidate = classify_nuisance_echoes(
                scene.dbzh,
                scene.companions,
                pulse=pulse,
            )
            candidate_prediction = np.asarray(
                candidate.remove_mask,
                dtype=bool,
            )
            for method, prediction, counts in (
                (CURRENT_METHOD, current_prediction, current_counts),
                (CANDIDATE_METHOD, candidate_prediction, candidate.counts),
            ):
                records.append(
                    {
                        "method": method,
                        "pulse": pulse,
                        "seed": seed,
                        "metrics": evaluate_predicted_removal(
                            prediction,
                            scene,
                        ),
                        "decision_counts": counts,
                    }
                )
            if seed == selected_seeds[0]:
                examples[pulse] = {
                    "scene": scene,
                    "current_prediction": current_prediction,
                    "candidate_prediction": candidate_prediction,
                    "candidate_nuisance": candidate.nuisance_mask,
                    "candidate_evidence": candidate.evidence_mask,
                    "candidate_confidence": candidate.confidence,
                    "candidate_noise_profile": candidate.noise_profile,
                }

    summaries = {}
    for method in (CURRENT_METHOD, CANDIDATE_METHOD):
        summaries[method] = {
            pulse: aggregate_metrics(
                [
                    record["metrics"]
                    for record in records
                    if record["method"] == method
                    and (pulse == "all" or record["pulse"] == pulse)
                ]
            )
            for pulse in ("all", "lp", "sp")
        }
    candidate_all = summaries[CANDIDATE_METHOD]["all"]
    current_all = summaries[CURRENT_METHOD]["all"]
    gate_results = {
        "precision": candidate_all["precision"]
        >= PROMOTION_GATES["precision_min"],
        "retain_recall": candidate_all["retain_recall"]
        >= PROMOTION_GATES["retain_recall_min"],
        "high_signal_retain_recall": candidate_all[
            "high_signal_retain_recall"
        ]
        >= PROMOTION_GATES["high_signal_retain_recall_min"],
        "artifact_recall_improvement": (
            candidate_all["artifact_recall"]
            - current_all["artifact_recall"]
        )
        >= PROMOTION_GATES["artifact_recall_improvement_min"],
    }
    report = {
        "schema": "uk_wsr_qc_synthetic_validation",
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "scene_contract": {
            "seeds": selected_seeds,
            "pulse_types": ["lp", "sp"],
            "nrays": int(nrays),
            "nbins": int(nbins),
            "artifact_classes": [
                "receiver_noise",
                "static_clutter",
                "anomalous_propagation",
                "radial_interference",
                "isolated_speckle",
            ],
            "retained_classes": [
                "precipitation",
                "biological_echo",
                "clear_air_atmospheric",
            ],
        },
        "methods": [CURRENT_METHOD, CANDIDATE_METHOD],
        "summary": summaries,
        "promotion_gates": PROMOTION_GATES,
        "synthetic_gate_results": gate_results,
        "synthetic_gate_passed": all(gate_results.values()),
        "promotion_eligible": False,
        "promotion_blockers": [
            "independent real-data annotations are not complete",
            "static clutter requires independently trained learned priors",
            "desktop and iOS candidate parity is not yet proven",
        ],
        "records": records,
    }
    return SyntheticValidationRun(report=report, examples=examples)


def aggregate_metrics(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not metrics:
        raise ValueError("cannot aggregate an empty metric list")
    totals = {
        key: sum(int(metric.get(key) or 0) for metric in metrics)
        for key in (
            "true_positive",
            "false_positive",
            "false_negative",
            "true_negative",
            "artifact_count",
            "retain_count",
            "high_signal_count",
            "high_signal_removed",
        )
    }
    per_artifact = {}
    for artifact in metrics[0]["per_artifact"]:
        count = sum(
            int(metric["per_artifact"][artifact]["count"])
            for metric in metrics
        )
        detected = sum(
            round(
                float(metric["per_artifact"][artifact]["recall"])
                * int(metric["per_artifact"][artifact]["count"])
            )
            for metric in metrics
        )
        per_artifact[artifact] = {
            "count": count,
            "detected": detected,
            "recall": _fraction(detected, count),
        }
    predicted = totals["true_positive"] + totals["false_positive"]
    return {
        **totals,
        "scene_count": len(metrics),
        "precision": _fraction(totals["true_positive"], predicted),
        "artifact_recall": _fraction(
            totals["true_positive"],
            totals["artifact_count"],
        ),
        "retain_recall": _fraction(
            totals["true_negative"],
            totals["retain_count"],
        ),
        "coherent_signal_removal_fraction": _fraction(
            totals["false_positive"],
            totals["retain_count"],
        ),
        "high_signal_retain_recall": _fraction(
            totals["high_signal_count"] - totals["high_signal_removed"],
            totals["high_signal_count"],
        ),
        "per_artifact": per_artifact,
    }


def run_learned_prior_synthetic_validation(
    *,
    training_seeds: Iterable[int] = range(1000, 1048),
    holdout_seeds: Iterable[int] = range(2000, 2012),
    nrays: int = 180,
    nbins: int = 220,
) -> LearnedPriorSyntheticValidationRun:
    """Train on moving scenes and score the learned prior on unseen seeds."""

    np = require_numpy()
    train = [int(value) for value in training_seeds]
    holdout = [int(value) for value in holdout_seeds]
    if len(train) < 8:
        raise ValueError("at least eight learned-prior training seeds are required")
    if not holdout:
        raise ValueError("at least one learned-prior holdout seed is required")
    if set(train) & set(holdout):
        raise ValueError("learned-prior training and holdout seeds must be disjoint")

    records: list[dict[str, Any]] = []
    examples: dict[str, dict[str, Any]] = {}
    model_summaries: dict[str, dict[str, Any]] = {}
    evidence_config = EvidenceConfig()
    for pulse in ("lp", "sp"):
        scans: list[BackgroundScan] = []
        start = date(2023, 1, 1)
        for index, seed in enumerate(train):
            scene = generate_synthetic_scene(
                SyntheticConfig(
                    pulse=pulse,
                    nrays=int(nrays),
                    nbins=int(nbins),
                    dynamic_geometry=True,
                ),
                seed=seed,
            )
            scans.append(
                BackgroundScan(
                    scene.dbzh,
                    metadata=SimpleNamespace(
                        date=(start + timedelta(days=index * 7)).strftime(
                            "%Y%m%d"
                        ),
                        time=UTC_TIMES[index % len(UTC_TIMES)],
                        dataset="dataset1",
                    ),
                    companion_fields=scene.companions,
                )
            )
        model = build_background_model(
            scans,
            key={
                "radar": "synthetic",
                "pulse": pulse,
                "quantity": "DBZH",
                "dataset": "dataset1",
                "elevation_deg": 0.5,
                "season_bucket": "all",
                "time_of_day_bucket": "all",
            },
        )
        conditioned_static_frequency = model.arrays[
            "low_ci_near_zero_vrad_frequency"
        ]
        conditioned_persistence = model.arrays[
            "low_ci_persistent_echo_frequency"
        ]
        conditioned_sample_count = np.minimum(
            np.asarray(
                model.arrays["low_ci_sample_count"],
                dtype="float32",
            ),
            np.asarray(
                model.arrays["low_ci_vrad_sample_count"],
                dtype="float32",
            ),
        )
        conditioned_support = (
            conditioned_sample_count
            >= evidence_config.background_conditioned_min_samples
        )
        supported_persistence = np.where(
            conditioned_support,
            conditioned_persistence,
            np.nan,
        )
        supported_static_frequency = np.where(
            conditioned_support,
            conditioned_static_frequency,
            np.nan,
        )
        model_summaries[pulse] = {
            **model.summary(),
            "source_date_count": model.metadata["source_date_count"],
            "training_span_days": model.metadata["training_span_days"],
            "conditioned_static_sample_gates": int(
                (
                    conditioned_support
                ).sum()
            ),
        }
        for seed in holdout:
            scene = generate_synthetic_scene(
                SyntheticConfig(
                    pulse=pulse,
                    nrays=int(nrays),
                    nbins=int(nbins),
                    dynamic_geometry=True,
                ),
                seed=seed,
            )
            baseline = classify_nuisance_echoes(
                scene.dbzh,
                scene.companions,
                pulse=pulse,
                config=evidence_config,
            )
            learned = classify_nuisance_echoes(
                scene.dbzh,
                scene.companions,
                pulse=pulse,
                config=evidence_config,
                context=EvidenceContext(
                    background_persistent_frequency=model.arrays[
                        "low_ci_persistent_echo_frequency"
                    ],
                    background_near_zero_vrad_frequency=(
                        conditioned_static_frequency
                    ),
                    background_conditioned_sample_count=(
                        conditioned_sample_count
                    ),
                ),
            )
            for method, result in (
                (CANDIDATE_METHOD, baseline),
                (LEARNED_CANDIDATE_METHOD, learned),
            ):
                records.append(
                    {
                        "method": method,
                        "pulse": pulse,
                        "seed": seed,
                        "metrics": evaluate_predicted_removal(
                            result.remove_mask,
                            scene,
                        ),
                        "decision_counts": result.counts,
                    }
                )
            if seed == holdout[0]:
                examples[pulse] = {
                    "scene": scene,
                    "baseline_prediction": baseline.remove_mask,
                    "learned_prediction": learned.remove_mask,
                    "learned_static_prediction": learned.nuisance(
                        NuisanceFlag.STATIC_CLUTTER
                    ),
                    "persistent_echo_frequency": model.arrays[
                        "low_ci_persistent_echo_frequency"
                    ],
                    "conditioned_static_frequency": (
                        conditioned_static_frequency
                    ),
                    "conditioned_static_samples": model.arrays[
                        "low_ci_vrad_sample_count"
                    ],
                    "conditioned_persistence": conditioned_persistence,
                    "conditioned_sample_count": conditioned_sample_count,
                    "conditioned_support": conditioned_support,
                    "supported_persistence": supported_persistence,
                    "supported_static_frequency": (
                        supported_static_frequency
                    ),
                }

    summaries = {
        method: {
            pulse: aggregate_metrics(
                [
                    record["metrics"]
                    for record in records
                    if record["method"] == method
                    and (pulse == "all" or record["pulse"] == pulse)
                ]
            )
            for pulse in ("all", "lp", "sp")
        }
        for method in (CANDIDATE_METHOD, LEARNED_CANDIDATE_METHOD)
    }
    baseline_all = summaries[CANDIDATE_METHOD]["all"]
    learned_all = summaries[LEARNED_CANDIDATE_METHOD]["all"]
    baseline_static = baseline_all["per_artifact"]["static_clutter"]["recall"]
    learned_static = learned_all["per_artifact"]["static_clutter"]["recall"]
    gate_results = {
        "precision": learned_all["precision"]
        >= LEARNED_PRIOR_GATES["precision_min"],
        "retain_recall": learned_all["retain_recall"]
        >= LEARNED_PRIOR_GATES["retain_recall_min"],
        "static_clutter_recall": learned_static
        >= LEARNED_PRIOR_GATES["static_clutter_recall_min"],
        "static_clutter_recall_gain": (
            learned_static - baseline_static
        )
        >= LEARNED_PRIOR_GATES["static_clutter_recall_gain_min"],
        "artifact_recall_non_regression": learned_all["artifact_recall"]
        + LEARNED_PRIOR_GATES["artifact_recall_non_regression_tolerance"]
        >= baseline_all["artifact_recall"],
    }
    report = {
        "schema": "uk_wsr_qc_learned_prior_synthetic_validation",
        "schema_version": 1,
        "generated_at": _now_utc(),
        "training_contract": {
            "training_seeds": train,
            "holdout_seeds": holdout,
            "seeds_disjoint": True,
            "dynamic_geometry": True,
            "fixed_mechanism": "static_clutter_only",
            "moving_mechanisms": [
                "precipitation",
                "biological_echo",
                "clear_air_atmospheric",
                "anomalous_propagation",
                "radial_interference",
            ],
            "pulse_types": ["lp", "sp"],
            "nrays": int(nrays),
            "nbins": int(nbins),
            "training_scene_count": len(train) * 2,
            "holdout_scene_count": len(holdout) * 2,
            "learned_static_statistic": (
                "echo persistence and near-zero VRAD frequency conditioned "
                "on low CI, with explicit conditioned sample support"
            ),
            "conditioned_min_samples": (
                evidence_config.background_conditioned_min_samples
            ),
        },
        "methods": [CANDIDATE_METHOD, LEARNED_CANDIDATE_METHOD],
        "summary": summaries,
        "models": model_summaries,
        "validation_gates": LEARNED_PRIOR_GATES,
        "validation_gate_results": gate_results,
        "validation_gate_passed": all(gate_results.values()),
        "promotion_eligible": False,
        "promotion_blockers": [
            "independent real-data annotations are not complete",
            "real multi-date models are not yet benchmarked",
            "desktop and iOS learned-prior parity is not yet proven",
        ],
        "records": records,
    }
    return LearnedPriorSyntheticValidationRun(
        report=report,
        examples=examples,
    )


def write_learned_prior_synthetic_validation(
    run: LearnedPriorSyntheticValidationRun,
    output_dir: str | Path,
) -> list[Path]:
    """Persist learned-prior metrics, exact fixtures, plots, and narrative."""

    np = require_numpy()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(run.report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)

    csv_path = output / "holdout_metrics.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            lineterminator="\n",
            fieldnames=[
                "method",
                "pulse",
                "seed",
                "precision",
                "artifact_recall",
                "static_clutter_recall",
                "retain_recall",
                "false_positive",
            ],
        )
        writer.writeheader()
        for record in run.report["records"]:
            metrics = record["metrics"]
            writer.writerow(
                {
                    "method": record["method"],
                    "pulse": record["pulse"],
                    "seed": record["seed"],
                    "precision": metrics["precision"],
                    "artifact_recall": metrics["artifact_recall"],
                    "static_clutter_recall": metrics["per_artifact"][
                        "static_clutter"
                    ]["recall"],
                    "retain_recall": metrics["retain_recall"],
                    "false_positive": metrics["false_positive"],
                }
            )
    written.append(csv_path)

    for pulse, example in run.examples.items():
        fixture_path = output / f"learned_prior_holdout_{pulse}.npz"
        scene: SyntheticScene = example["scene"]
        np.savez_compressed(
            fixture_path,
            dbzh=scene.dbzh,
            truth_mask=scene.truth_mask,
            retain_mask=scene.retain_mask,
            baseline_prediction=example["baseline_prediction"],
            learned_prediction=example["learned_prediction"],
            learned_static_prediction=example["learned_static_prediction"],
            persistent_echo_frequency=example[
                "persistent_echo_frequency"
            ],
            conditioned_static_frequency=example[
                "conditioned_static_frequency"
            ],
            conditioned_static_samples=example[
                "conditioned_static_samples"
            ],
            conditioned_sample_count=example[
                "conditioned_sample_count"
            ],
            conditioned_support=example["conditioned_support"],
            conditioned_persistence=example[
                "conditioned_persistence"
            ],
            supported_persistence=example[
                "supported_persistence"
            ],
            supported_static_frequency=example[
                "supported_static_frequency"
            ],
            **{
                f"companion_{quantity}": values
                for quantity, values in scene.companions.items()
            },
        )
        written.append(fixture_path)
        montage_path = output / f"learned_prior_holdout_{pulse}.png"
        _write_learned_prior_montage(example, pulse, montage_path)
        written.append(montage_path)

    chart_path = output / "learned_prior_comparison.png"
    _write_learned_prior_comparison(run.report, chart_path)
    written.append(chart_path)
    readme_path = output / "README.md"
    readme_path.write_text(
        learned_prior_validation_markdown(run.report),
        encoding="utf-8",
    )
    written.append(readme_path)
    return written


def write_synthetic_validation(
    run: SyntheticValidationRun,
    output_dir: str | Path,
) -> list[Path]:
    """Write machine-readable metrics, exact fixtures, plots, and a report."""

    np = require_numpy()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(run.report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)

    csv_path = output / "scene_metrics.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "method",
                "pulse",
                "seed",
                "precision",
                "artifact_recall",
                "retain_recall",
                "high_signal_retain_recall",
                "true_positive",
                "false_positive",
                "false_negative",
            ],
        )
        writer.writeheader()
        for record in run.report["records"]:
            metrics = record["metrics"]
            writer.writerow(
                {
                    "method": record["method"],
                    "pulse": record["pulse"],
                    "seed": record["seed"],
                    **{
                        key: metrics[key]
                        for key in writer.fieldnames
                        if key in metrics
                    },
                }
            )
    written.append(csv_path)

    for pulse, example in run.examples.items():
        fixture_path = output / f"exact_scene_{pulse}.npz"
        scene: SyntheticScene = example["scene"]
        np.savez_compressed(
            fixture_path,
            dbzh=scene.dbzh,
            truth_mask=scene.truth_mask,
            retain_mask=scene.retain_mask,
            current_prediction=example["current_prediction"],
            candidate_prediction=example["candidate_prediction"],
            candidate_nuisance=example["candidate_nuisance"],
            candidate_evidence=example["candidate_evidence"],
            candidate_confidence=example["candidate_confidence"],
            candidate_noise_profile=example["candidate_noise_profile"],
            **{
                f"companion_{quantity}": values
                for quantity, values in scene.companions.items()
            },
        )
        written.append(fixture_path)
        montage_path = output / f"exact_scene_{pulse}_comparison.png"
        _write_example_montage(example, pulse, montage_path)
        written.append(montage_path)

    comparison_path = output / "method_comparison.png"
    _write_method_comparison(run.report, comparison_path)
    written.append(comparison_path)
    artifact_path = output / "artifact_recall.png"
    _write_artifact_recall(run.report, artifact_path)
    written.append(artifact_path)
    readme_path = output / "README.md"
    readme_path.write_text(
        synthetic_validation_markdown(run.report),
        encoding="utf-8",
    )
    written.append(readme_path)
    return written


def synthetic_validation_markdown(report: dict[str, Any]) -> str:
    current = report["summary"][CURRENT_METHOD]["all"]
    candidate = report["summary"][CANDIDATE_METHOD]["all"]
    rows = []
    for method, values in (
        ("Current qc-v2", current),
        ("Multi-evidence candidate", candidate),
    ):
        rows.append(
            f"| {method} | {values['precision']:.4f} | "
            f"{values['artifact_recall']:.4f} | "
            f"{values['retain_recall']:.4f} | "
            f"{values['high_signal_retain_recall']:.4f} |"
        )
    blockers = "\n".join(
        f"- {value}" for value in report["promotion_blockers"]
    )
    return f"""# UK WSR exact-mask synthetic validation

Status: **{"synthetic gates passed" if report["synthetic_gate_passed"] else "synthetic gates failed"}; not eligible for promotion**

This suite evaluates nuisance removal and coherent-signal retention against
exact gate masks. It is an algorithm test, not a substitute for independently
reviewed real UKMO sweeps.

| Method | Precision | Artifact recall | Retain recall | >=20 dBZ retain recall |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

The candidate changes artifact recall by
`{candidate['artifact_recall'] - current['artifact_recall']:+.4f}` while its
coherent-signal removal fraction is
`{candidate['coherent_signal_removal_fraction']:.6f}`.

![Method comparison](method_comparison.png)

![Artifact recall](artifact_recall.png)

## Promotion blockers

{blockers}

## Reproduction

```bash
PYTHONPATH=src .venv/bin/python tools/validate_qc_synthetic.py \
  --output-dir reports/qc_synthetic_v1
```
"""


def learned_prior_validation_markdown(report: dict[str, Any]) -> str:
    baseline = report["summary"][CANDIDATE_METHOD]["all"]
    learned = report["summary"][LEARNED_CANDIDATE_METHOD]["all"]
    baseline_static = baseline["per_artifact"]["static_clutter"]["recall"]
    learned_static = learned["per_artifact"]["static_clutter"]["recall"]
    blockers = "\n".join(
        f"- {value}" for value in report["promotion_blockers"]
    )
    return f"""# UK WSR learned-prior synthetic train/holdout validation

Status: **{"validation gates passed" if report["validation_gate_passed"] else "validation gates failed"}; not eligible for promotion**

The learned map is trained on moving weather, biological, clear-air, AP, and
interference scenes. Only static clutter remains fixed. Holdout seeds are
disjoint from training, so the result cannot be obtained by memorising the
retained-signal geometry.

| Method | Precision | Artifact recall | Static-clutter recall | Retain recall |
| --- | ---: | ---: | ---: | ---: |
| Candidate without learned prior | {baseline['precision']:.4f} | {baseline['artifact_recall']:.4f} | {baseline_static:.4f} | {baseline['retain_recall']:.4f} |
| Candidate + CI-conditioned learned prior | {learned['precision']:.4f} | {learned['artifact_recall']:.4f} | {learned_static:.4f} | {learned['retain_recall']:.4f} |

The learned prior changes static-clutter recall by
`{learned_static - baseline_static:+.4f}`. The statistic is near-zero VRAD
frequency conditioned on low CI, preventing atmospheric crossings from
diluting the learned stationary-clutter evidence.

![Learned-prior comparison](learned_prior_comparison.png)

![LP held-out learned map](learned_prior_holdout_lp.png)

![SP held-out learned map](learned_prior_holdout_sp.png)

## Promotion blockers

{blockers}

## Reproduction

```bash
PYTHONPATH=src .venv/bin/python tools/validate_qc_learned_synthetic.py \
  --output-dir reports/qc_synthetic_learned_v1
```
"""


def _write_learned_prior_comparison(
    report: dict[str, Any],
    path: Path,
) -> None:
    values = []
    for method in (CANDIDATE_METHOD, LEARNED_CANDIDATE_METHOD):
        summary = report["summary"][method]["all"]
        for group, value in (
            ("Precision", summary["precision"]),
            ("Artifact recall", summary["artifact_recall"]),
            (
                "Static clutter",
                summary["per_artifact"]["static_clutter"]["recall"],
            ),
            ("Retain recall", summary["retain_recall"]),
        ):
            values.append(
                {
                    "group": group,
                    "method": method,
                    "value": value,
                    "color": METHOD_COLORS[method],
                }
            )
    _grouped_bar_chart(
        values,
        title="Independent synthetic train/holdout learned-prior result",
        y_label="Fraction",
        path=path,
    )


def _write_learned_prior_montage(
    example: dict[str, Any],
    pulse: str,
    path: Path,
) -> None:
    np = require_numpy()
    Image = require_pillow()
    from PIL import ImageDraw

    scene: SyntheticScene = example["scene"]
    static_truth = (
        np.asarray(scene.truth_mask, dtype="uint16")
        & int(SyntheticTruthFlag.STATIC_CLUTTER)
    ) != 0
    panels = [
        ("Held-out raw DBZH", _render_dbzh(scene.dbzh, 330)),
        (
            "Supported learned persistence",
            _render_frequency(
                example["supported_persistence"],
                330,
            ),
        ),
        (
            "Supported low-CI near-zero VRAD",
            _render_frequency(
                example["supported_static_frequency"],
                330,
            ),
        ),
        ("Exact static clutter", _render_binary(static_truth, 330)),
        (
            "Candidate + learned prior",
            _render_outcome(
                scene,
                example["learned_prediction"],
                330,
            ),
        ),
    ]
    margin, header, footer = 22, 88, 62
    panel_width, panel_height = 350, 382
    canvas = Image.new(
        "RGB",
        (
            margin * (len(panels) + 1) + panel_width * len(panels),
            header + panel_height + footer,
        ),
        "#f6f7f8",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (margin, 20),
        f"{pulse.upper()} unseen holdout with independently learned prior",
        fill="#172129",
        font=_font(30, bold=True),
    )
    for index, (title, image) in enumerate(panels):
        x = margin + index * (panel_width + margin)
        box = draw.textbbox((0, 0), title, font=_font(17, bold=True))
        draw.text(
            (x + (panel_width - (box[2] - box[0])) / 2, header),
            title,
            fill="#26333c",
            font=_font(17, bold=True),
        )
        canvas.paste(image, (x + 10, header + 34), image)
    legend = [
        ("retained truth", "#4aa66d"),
        ("correct removal", "#2a7fc1"),
        ("missed nuisance", "#e28c38"),
        ("false removal", "#c63c79"),
    ]
    for index, (label, color) in enumerate(legend):
        x = margin + index * 190
        y = header + panel_height + 20
        draw.rectangle((x, y, x + 18, y + 18), fill=color)
        draw.text((x + 26, y - 1), label, fill="#53616b", font=_font(14))
    canvas.save(path, optimize=True)


def _render_frequency(values: Any, size: int):
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    scaled = np.clip(np.nan_to_num(array), 0.0, 1.0)
    colors = np.empty((*scaled.shape, 3), dtype="uint8")
    colors[..., 0] = np.rint(30.0 + 210.0 * scaled).astype("uint8")
    colors[..., 1] = np.rint(45.0 + 145.0 * scaled).astype("uint8")
    colors[..., 2] = np.rint(125.0 - 95.0 * scaled).astype("uint8")
    return _polar_rgba(colors, np.isfinite(array), size)


def _render_binary(values: Any, size: int):
    np = require_numpy()
    mask = np.asarray(values, dtype=bool)
    colors = np.zeros((*mask.shape, 3), dtype="uint8")
    colors[mask] = (42, 127, 193)
    return _polar_rgba(colors, mask, size)


def _current_qc_prediction(
    scene: SyntheticScene,
) -> tuple[Any, dict[str, int]]:
    np = require_numpy()
    config = QCConfig(
        mode="signal_preserving",
        operation="mask",
        noise_floor_enabled=True,
        noise_floor_hard_mask=False,
        receiver_noise_enabled=True,
        texture_enabled=False,
        companion_qc_enabled=False,
        static_clutter_enabled=False,
        background_model_enabled=False,
    )
    result = build_qc_mask(
        scene.dbzh,
        SimpleNamespace(quantity="DBZH", attrs={}),
        companion_fields=scene.companions,
        config=config,
    )
    prediction = (
        np.asarray(result.mask, dtype="uint16")
        & int(QCMaskFlag.RECEIVER_NOISE)
    ) != 0
    return prediction, dict(result.flag_counts)


def _write_method_comparison(
    report: dict[str, Any],
    path: Path,
) -> None:
    values = []
    for method in (CURRENT_METHOD, CANDIDATE_METHOD):
        summary = report["summary"][method]["all"]
        for metric, label in (
            ("precision", "Precision"),
            ("artifact_recall", "Artifact recall"),
            ("retain_recall", "Retain recall"),
        ):
            values.append(
                {
                    "group": label,
                    "method": method,
                    "value": summary[metric],
                    "color": METHOD_COLORS[method],
                }
            )
    _grouped_bar_chart(
        values,
        title="Exact-mask nuisance removal and signal retention",
        y_label="Fraction",
        path=path,
    )


def _write_artifact_recall(
    report: dict[str, Any],
    path: Path,
) -> None:
    display = {
        "receiver_noise": "Receiver noise",
        "static_clutter": "Static clutter",
        "anomalous_propagation": "AP",
        "radial_interference": "Interference",
        "isolated_speckle": "Speckle",
    }
    values = []
    for artifact, label in display.items():
        for method in (CURRENT_METHOD, CANDIDATE_METHOD):
            values.append(
                {
                    "group": label,
                    "method": method,
                    "value": report["summary"][method]["all"][
                        "per_artifact"
                    ][artifact]["recall"],
                    "color": METHOD_COLORS[method],
                }
            )
    _grouped_bar_chart(
        values,
        title="Recall by synthetic nuisance mechanism",
        y_label="Recall",
        path=path,
    )


def _grouped_bar_chart(
    values: list[dict[str, Any]],
    *,
    title: str,
    y_label: str,
    path: Path,
) -> None:
    Image = require_pillow()
    from PIL import ImageDraw

    width, height = 1280, 760
    image = Image.new("RGB", (width, height), "#f6f7f8")
    draw = ImageDraw.Draw(image)
    font = _font(22)
    small = _font(16)
    bold = _font(30, bold=True)
    draw.text((55, 28), title, fill="#172129", font=bold)
    groups = list(dict.fromkeys(str(item["group"]) for item in values))
    methods = list(dict.fromkeys(str(item["method"]) for item in values))
    left, top, right, bottom = 90, 140, width - 40, height - 100
    for tick in range(6):
        value = tick / 5
        y = bottom - value * (bottom - top)
        draw.line((left, y, right, y), fill="#d8dde1", width=1)
        draw.text((35, y - 9), f"{value:.1f}", fill="#53616b", font=small)
    draw.text((16, top - 25), y_label, fill="#53616b", font=small)
    group_width = (right - left) / max(1, len(groups))
    bar_width = min(74.0, group_width / (len(methods) + 1))
    for group_index, group in enumerate(groups):
        centre = left + (group_index + 0.5) * group_width
        entries = [item for item in values if item["group"] == group]
        for method_index, method in enumerate(methods):
            entry = next(item for item in entries if item["method"] == method)
            x0 = centre + (method_index - (len(methods) - 1) / 2) * (
                bar_width + 8
            ) - bar_width / 2
            y0 = bottom - float(entry["value"]) * (bottom - top)
            draw.rectangle(
                (x0, y0, x0 + bar_width, bottom),
                fill=entry["color"],
            )
            label = f"{float(entry['value']):.3f}"
            box = draw.textbbox((0, 0), label, font=small)
            draw.text(
                (x0 + (bar_width - (box[2] - box[0])) / 2, y0 - 23),
                label,
                fill="#26333c",
                font=small,
            )
        box = draw.textbbox((0, 0), group, font=font)
        draw.text(
            (centre - (box[2] - box[0]) / 2, bottom + 18),
            group,
            fill="#26333c",
            font=font,
        )
    legend_x = left
    legend_y = 78
    for index, method in enumerate(methods):
        x = legend_x + index * 250
        draw.rectangle(
            (x, legend_y, x + 22, legend_y + 22),
            fill=METHOD_COLORS[method],
        )
        label = METHOD_LABELS.get(method, method)
        draw.text(
            (x + 30, legend_y - 1),
            label,
            fill="#26333c",
            font=small,
        )
    image.save(path, optimize=True)


def _write_example_montage(
    example: dict[str, Any],
    pulse: str,
    path: Path,
) -> None:
    np = require_numpy()
    Image = require_pillow()
    from PIL import ImageDraw

    scene: SyntheticScene = example["scene"]
    current = np.asarray(example["current_prediction"], dtype=bool)
    candidate = np.asarray(example["candidate_prediction"], dtype=bool)
    cleaned = np.asarray(scene.dbzh, dtype="float32").copy()
    cleaned[candidate] = np.nan
    panels = [
        ("Synthetic raw DBZH", _render_dbzh(scene.dbzh, 330)),
        ("Exact truth", _render_outcome(scene, scene.remove_mask, 330)),
        ("Current qc-v2", _render_outcome(scene, current, 330)),
        ("Multi-evidence candidate", _render_outcome(scene, candidate, 330)),
        ("Candidate cleaned DBZH", _render_dbzh(cleaned, 330)),
    ]
    margin, header, footer = 22, 82, 62
    panel_width, panel_height = 350, 382
    canvas = Image.new(
        "RGB",
        (
            margin * (len(panels) + 1) + panel_width * len(panels),
            header + panel_height + footer,
        ),
        "#f6f7f8",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (margin, 20),
        f"{pulse.upper()} exact-mask example",
        fill="#172129",
        font=_font(30, bold=True),
    )
    for index, (title, image) in enumerate(panels):
        x = margin + index * (panel_width + margin)
        box = draw.textbbox((0, 0), title, font=_font(17, bold=True))
        draw.text(
            (x + (panel_width - (box[2] - box[0])) / 2, header),
            title,
            fill="#26333c",
            font=_font(17, bold=True),
        )
        canvas.paste(image, (x + 10, header + 34), image)
    legend = [
        ("retained truth", "#4aa66d"),
        ("correct removal", "#2a7fc1"),
        ("missed nuisance", "#e28c38"),
        ("false removal", "#c63c79"),
    ]
    for index, (label, color) in enumerate(legend):
        x = margin + index * 190
        y = header + panel_height + 20
        draw.rectangle((x, y, x + 18, y + 18), fill=color)
        draw.text((x + 26, y - 1), label, fill="#53616b", font=_font(14))
    canvas.save(path, optimize=True)


def _render_dbzh(values: Any, size: int):
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    scaled = np.clip((array + 30.0) / 100.0, 0.0, 1.0)
    colors = apply_palette(
        (np.nan_to_num(scaled) * 255.0).astype("uint8"),
        "homeyer",
    )
    return _polar_rgba(colors, np.isfinite(array), size)


def _render_outcome(scene: SyntheticScene, predicted: Any, size: int):
    np = require_numpy()
    prediction = np.asarray(predicted, dtype=bool)
    truth_remove = np.asarray(scene.remove_mask, dtype=bool)
    truth_retain = np.asarray(scene.retain_mask, dtype=bool)
    codes = np.zeros(prediction.shape, dtype="uint8")
    codes[truth_retain & ~prediction] = 1
    codes[truth_remove & prediction] = 2
    codes[truth_remove & ~prediction] = 3
    codes[truth_retain & prediction] = 4
    palette = np.asarray(
        [
            (18, 22, 27),
            (74, 166, 109),
            (42, 127, 193),
            (226, 140, 56),
            (198, 60, 121),
        ],
        dtype="uint8",
    )
    return _polar_rgba(palette[codes], codes != 0, size)


def _polar_rgba(colors: Any, valid_values: Any, size: int):
    np = require_numpy()
    Image = require_pillow()
    from PIL import ImageDraw

    rgb = np.asarray(colors, dtype="uint8")
    valid_source = np.asarray(valid_values, dtype=bool)
    nrays, nbins = valid_source.shape
    coordinate = np.arange(size, dtype="float32")
    x, y = np.meshgrid(coordinate, coordinate)
    centre = (size - 1) / 2.0
    dx, dy = x - centre, y - centre
    radial = np.sqrt(dx * dx + dy * dy)
    inside = radial <= centre
    gate = np.minimum(
        (radial / max(centre, 1.0) * nbins).astype("int32"),
        nbins - 1,
    )
    azimuth = np.mod(np.arctan2(dx, -dy), 2 * np.pi)
    ray = np.minimum(
        (azimuth / (2 * np.pi) * nrays).astype("int32"),
        nrays - 1,
    )
    sampled = rgb[ray, gate]
    valid = inside & valid_source[ray, gate]
    rgba = np.zeros((size, size, 4), dtype="uint8")
    rgba[inside, :3] = (18, 22, 27)
    rgba[inside, 3] = 255
    rgba[valid, :3] = sampled[valid]
    image = Image.fromarray(rgba, mode="RGBA")
    draw = ImageDraw.Draw(image, mode="RGBA")
    for fraction in (0.25, 0.50, 0.75, 1.0):
        radius = centre * fraction
        draw.ellipse(
            (
                centre - radius,
                centre - radius,
                centre + radius,
                centre + radius,
            ),
            outline=(235, 239, 242, 70),
        )
    return image


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fraction(numerator: int, denominator: int) -> float:
    return float(numerator) / denominator if denominator else 0.0


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
