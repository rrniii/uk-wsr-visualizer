"""Exact failure attribution for learned-background validation runs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .background_training_pipeline import file_sha256
from .dependencies import require_numpy
from .qc_evidence import EvidenceFlag, NuisanceFlag

BACKGROUND_FAILURE_ATTRIBUTION_SCHEMA = (
    "uk_wsr_background_failure_attribution"
)
BACKGROUND_FAILURE_ATTRIBUTION_SCHEMA_VERSION = 1


def build_background_failure_attribution(
    validation_results_path: str | Path,
    frozen_policy_path: str | Path,
) -> dict[str, Any]:
    """Attribute rejected validation decisions to exact masks and evidence."""

    np = require_numpy()
    validation_path = Path(validation_results_path)
    policy_path = Path(frozen_policy_path)
    validation = _read_json(validation_path)
    policy = _read_json(policy_path)
    _validate_inputs(validation_path, validation, policy)

    policy_targets = {
        str(target["target_id"]): target
        for target in policy.get("targets") or []
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in validation["records"]:
        grouped.setdefault(str(record["target_id"]), []).append(record)
    if set(grouped) != set(policy_targets):
        raise ValueError("validation and policy target sets differ")

    targets: list[dict[str, Any]] = []
    global_baseline_nuisance: Counter[str] = Counter()
    global_increment_nuisance: Counter[str] = Counter()
    global_increment_evidence: Counter[str] = Counter()
    for target_id, records in sorted(grouped.items()):
        baseline_nuisance: Counter[str] = Counter()
        increment_nuisance: Counter[str] = Counter()
        increment_evidence: Counter[str] = Counter()
        exact_increment_count = 0
        for record in records:
            baseline_nuisance.update(
                {
                    str(name): int(count)
                    for name, count in (
                        record["baseline"]["nuisance_counts"]
                    ).items()
                }
            )
            arrays = _load_verified_artifact(record)
            increment = np.asarray(
                arrays["learned_increment_mask"],
                dtype=bool,
            )
            nuisance = np.asarray(
                arrays["learned_nuisance_mask"],
                dtype="uint16",
            )
            evidence = np.asarray(
                arrays["learned_evidence_mask"],
                dtype="uint32",
            )
            if not (
                increment.shape == nuisance.shape == evidence.shape
            ):
                raise ValueError(
                    f"attribution array shape mismatch for "
                    f"{record['job_id']}"
                )
            exact_increment_count += int(increment.sum())
            _count_flags(
                increment_nuisance,
                increment,
                nuisance,
                NuisanceFlag,
            )
            _count_flags(
                increment_evidence,
                increment,
                evidence,
                EvidenceFlag,
            )
        reported_increment_count = sum(
            int(record["delta"]["learned_increment_count"])
            for record in records
        )
        if exact_increment_count != reported_increment_count:
            raise ValueError(
                f"learned increment count mismatch for {target_id}"
            )
        target_policy = policy_targets[target_id]
        first = records[0]
        target = {
            "target_id": target_id,
            "radar": first["radar"],
            "pulse": first["pulse"],
            "quantity": first["quantity"],
            "geometry_class": first["geometry_class"],
            "elevation_deg": first["elevation_deg"],
            "state": target_policy["state"],
            "blockers": list(target_policy.get("blockers") or []),
            "review_reasons": list(
                target_policy.get("review_reasons") or []
            ),
            "validation_sweep_count": len(records),
            "learned_increment_count": exact_increment_count,
            "baseline_nuisance_counts": dict(
                sorted(baseline_nuisance.items())
            ),
            "learned_increment_nuisance_counts": dict(
                sorted(increment_nuisance.items())
            ),
            "learned_increment_evidence_counts": dict(
                sorted(increment_evidence.items())
            ),
            "dominant_baseline_nuisance": _dominant(
                baseline_nuisance
            ),
            "dominant_learned_increment_nuisance": _dominant(
                increment_nuisance
            ),
            "worst_baseline_sweep": _worst_sweep(
                records,
                metric_path=(
                    "baseline",
                    "removed_fraction",
                ),
            ),
            "worst_baseline_power_sweep": _worst_sweep(
                records,
                metric_path=(
                    "baseline",
                    "removed_dbzh",
                    "linear_reflectivity_fraction",
                ),
            ),
            "worst_learned_increment_sweep": _worst_sweep(
                records,
                metric_path=(
                    "delta",
                    "learned_increment_fraction",
                ),
            ),
            "worst_learned_increment_power_sweep": _worst_sweep(
                records,
                metric_path=(
                    "delta",
                    "learned_increment_dbzh",
                    "linear_reflectivity_fraction",
                ),
            ),
        }
        targets.append(target)
        global_baseline_nuisance.update(baseline_nuisance)
        global_increment_nuisance.update(increment_nuisance)
        global_increment_evidence.update(increment_evidence)

    blocker_counts = Counter(
        blocker
        for target in targets
        for blocker in target["blockers"]
    )
    state_counts = Counter(target["state"] for target in targets)
    holdout_target_count = int(
        policy.get("holdout_scoring_target_count", 0)
    )
    return {
        "schema": BACKGROUND_FAILURE_ATTRIBUTION_SCHEMA,
        "schema_version": BACKGROUND_FAILURE_ATTRIBUTION_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "status": (
            "rejected_before_holdout"
            if holdout_target_count == 0
            else "partial_candidate_set"
        ),
        "validation_results": str(validation_path),
        "validation_results_sha256": file_sha256(validation_path),
        "frozen_policy": str(policy_path),
        "frozen_policy_sha256": file_sha256(policy_path),
        "configuration_sha256": validation["configuration_sha256"],
        "target_count": len(targets),
        "sweep_count": len(validation["records"]),
        "holdout_scoring_target_count": holdout_target_count,
        "state_counts": dict(sorted(state_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "global_baseline_nuisance_counts": dict(
            sorted(global_baseline_nuisance.items())
        ),
        "global_learned_increment_nuisance_counts": dict(
            sorted(global_increment_nuisance.items())
        ),
        "global_learned_increment_evidence_counts": dict(
            sorted(global_increment_evidence.items())
        ),
        "targets": targets,
    }


def write_background_failure_attribution(
    report: dict[str, Any],
    *,
    json_path: str | Path,
    markdown_path: str | Path | None = None,
    csv_path: str | Path | None = None,
) -> tuple[Path, Path | None, Path | None]:
    """Persist machine-readable, narrative, and tabular attribution."""

    json_destination = Path(json_path)
    _write_text_atomic(
        json_destination,
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )
    markdown_destination = (
        Path(markdown_path) if markdown_path is not None else None
    )
    if markdown_destination is not None:
        _write_text_atomic(
            markdown_destination,
            render_background_failure_attribution_markdown(report),
        )
    csv_destination = Path(csv_path) if csv_path is not None else None
    if csv_destination is not None:
        _write_attribution_csv(report, csv_destination)
    return json_destination, markdown_destination, csv_destination


def render_background_failure_attribution_markdown(
    report: dict[str, Any],
) -> str:
    """Render a concise publication-ready failure summary."""

    lines = [
        "# Learned background validation failure attribution",
        "",
        f"**Disposition:** `{report['status']}`",
        "",
        (
            f"The validation contains {report['sweep_count']:,} sweeps "
            f"across {report['target_count']:,} radar, pulse, elevation, "
            "and geometry targets. "
            f"{report['holdout_scoring_target_count']:,} targets are "
            "eligible to open the untouched holdout."
        ),
        "",
        "## Hard blockers",
        "",
        "| Blocker | Targets |",
        "|---|---:|",
    ]
    for blocker, count in sorted(
        report["blocker_counts"].items(),
        key=lambda item: (-int(item[1]), item[0]),
    ):
        lines.append(f"| {blocker} | {int(count):,} |")
    lines.extend(
        [
            "",
            "## Exact mechanism attribution",
            "",
            "| Learned-only nuisance mechanism | Gates |",
            "|---|---:|",
        ]
    )
    for name, count in sorted(
        report["global_learned_increment_nuisance_counts"].items(),
        key=lambda item: (-int(item[1]), item[0]),
    ):
        lines.append(f"| {name} | {int(count):,} |")
    lines.extend(
        [
            "",
            "| Learned-only evidence flag | Gates |",
            "|---|---:|",
        ]
    )
    for name, count in sorted(
        report["global_learned_increment_evidence_counts"].items(),
        key=lambda item: (-int(item[1]), item[0]),
    ):
        lines.append(f"| {name} | {int(count):,} |")
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            (
                f"- Validation SHA-256: "
                f"`{report['validation_results_sha256']}`"
            ),
            (
                f"- Frozen policy SHA-256: "
                f"`{report['frozen_policy_sha256']}`"
            ),
            (
                f"- Decision configuration SHA-256: "
                f"`{report['configuration_sha256']}`"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _validate_inputs(
    validation_path: Path,
    validation: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    if (
        validation.get("split") != "validation"
        or validation.get("complete") is not True
        or int(validation.get("error_count", -1)) != 0
    ):
        raise ValueError("validation input is not complete and error-free")
    records = list(validation.get("records") or [])
    if len(records) != int(validation.get("expected_job_count", -1)):
        raise ValueError("validation record count is incomplete")
    if (
        policy.get("validation_results_sha256")
        != file_sha256(validation_path)
    ):
        raise ValueError("policy does not match validation results")
    if (
        policy.get("configuration_sha256")
        != validation.get("configuration_sha256")
    ):
        raise ValueError("policy configuration hash mismatch")


def _load_verified_artifact(record: dict[str, Any]) -> dict[str, Any]:
    np = require_numpy()
    artifact_path = Path(record["artifact_npz"])
    expected_hash = str(record.get("artifact_sha256") or "")
    if (
        not expected_hash
        or not artifact_path.is_file()
        or file_sha256(artifact_path) != expected_hash
    ):
        raise ValueError(
            f"validation artifact hash mismatch for {record['job_id']}"
        )
    required = {
        "learned_increment_mask",
        "learned_nuisance_mask",
        "learned_evidence_mask",
    }
    with np.load(artifact_path, allow_pickle=False) as loaded:
        missing = required - set(loaded.files)
        if missing:
            raise ValueError(
                f"validation artifact missing {sorted(missing)} for "
                f"{record['job_id']}"
            )
        return {
            name: np.asarray(loaded[name])
            for name in sorted(required)
        }


def _count_flags(
    counts: Counter[str],
    selected: Any,
    values: Any,
    flag_type: type[EvidenceFlag] | type[NuisanceFlag],
) -> None:
    np = require_numpy()
    selected_array = np.asarray(selected, dtype=bool)
    values_array = np.asarray(values)
    for flag in flag_type:
        count = int(
            (
                selected_array
                & ((values_array & int(flag)) != 0)
            ).sum()
        )
        if count:
            counts[flag.name.lower()] += count


def _worst_sweep(
    records: list[dict[str, Any]],
    *,
    metric_path: tuple[str, ...],
) -> dict[str, Any]:
    selected = max(
        records,
        key=lambda record: float(_nested_value(record, metric_path)),
    )
    return {
        "job_id": selected["job_id"],
        "source_id": selected["source"]["source_id"],
        "date": selected["source"]["date"],
        "time": selected["source"]["time"],
        "value": float(_nested_value(selected, metric_path)),
    }


def _nested_value(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for key in path:
        value = value[key]
    return value


def _dominant(counts: Counter[str]) -> str | None:
    if not counts:
        return None
    return min(
        counts,
        key=lambda name: (-counts[name], name),
    )


def _write_attribution_csv(
    report: dict[str, Any],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    fieldnames = [
        "target_id",
        "radar",
        "pulse",
        "quantity",
        "geometry_class",
        "elevation_deg",
        "state",
        "validation_sweep_count",
        "learned_increment_count",
        "dominant_baseline_nuisance",
        "dominant_learned_increment_nuisance",
        "blockers",
    ]
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for target in report["targets"]:
            writer.writerow(
                {
                    name: (
                        "; ".join(target[name])
                        if name == "blockers"
                        else target.get(name)
                    )
                    for name in fieldnames
                }
            )
    temporary.replace(destination)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
