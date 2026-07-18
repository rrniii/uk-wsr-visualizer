"""Blinded temporal review targets for UK WSR nuisance classification."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .qc_benchmark import canonical_json_sha256


TEMPORAL_REVIEW_ID = "uk-wsr-qc-temporal-review-v1"
TEMPORAL_REVIEW_SCHEMA = "uk_wsr_qc_temporal_review_targets"
TEMPORAL_REVIEW_SCHEMA_VERSION = 1
HIDDEN_FIELDS = (
    "CI",
    "QC_MASK",
    "QC_SCORE",
    "BACKGROUND_PROBABILITY",
    "CANDIDATE_SELECTION_ROLE",
)
CURRENT_VISIBLE_FIELDS = (
    "DBZH",
    "VRADH",
    "SQIH",
    "RHOHV",
    "ZDR",
    "PHIDP",
    "WRADH",
    "LONG_RANGE_NOISE_DBC_H",
    "LONG_RANGE_NOISE_DBC_V",
)
CONTEXT_VISIBLE_FIELDS = ("DBZH", "VRADH")


def build_temporal_review_target_manifest(
    validation: Mapping[str, Any],
    frozen_policy: Mapping[str, Any],
    temporal_manifest: Mapping[str, Any],
    download_ledger: Mapping[str, Any],
    *,
    regression_cases: Sequence[
        tuple[Mapping[str, Any], Mapping[str, Any]]
    ] = (),
    required_reviewer_count: int = 1,
) -> dict[str, Any]:
    """Build challenge/control pairs without exposing candidate selection."""

    if required_reviewer_count not in (1, 2):
        raise ValueError("required reviewer count must be one or two")
    _validate_inputs(
        validation,
        frozen_policy,
        temporal_manifest,
        download_ledger,
    )
    manifest_files = {
        str(item["source_id"]): item
        for item in temporal_manifest.get("files", ())
    }
    ledger_files = _normalised_ledger_files(download_ledger)
    policy_targets = {
        str(item["target_id"]): item
        for item in frozen_policy.get("targets", ())
    }
    records_by_target: dict[str, list[Mapping[str, Any]]] = defaultdict(
        list
    )
    for record in validation.get("records", ()):
        if str(record.get("split")) != "validation":
            raise ValueError("temporal review may use validation records only")
        records_by_target[str(record["target_id"])].append(record)

    targets: list[dict[str, Any]] = []
    for target_id in sorted(policy_targets):
        records = sorted(
            records_by_target.get(target_id, ()),
            key=_record_order_key,
        )
        if not records:
            raise ValueError(f"{target_id}: no validation records")
        challenge = max(records, key=_challenge_key)
        control = _candidate_independent_control(records, target_id)
        if len(records) > 1 and control["job_id"] == challenge["job_id"]:
            index = records.index(control)
            control = records[(index + 1) % len(records)]
        targets.append(
            _temporal_target(
                challenge,
                selection_role_internal="candidate_challenge",
                policy_target=policy_targets[target_id],
                manifest_files=manifest_files,
                ledger_files=ledger_files,
                required_reviewer_count=required_reviewer_count,
            )
        )
        targets.append(
            _temporal_target(
                control,
                selection_role_internal="candidate_independent_control",
                policy_target=policy_targets[target_id],
                manifest_files=manifest_files,
                ledger_files=ledger_files,
                required_reviewer_count=required_reviewer_count,
            )
        )

    for record, case in regression_cases:
        targets.append(
            _regression_target(
                record,
                case,
                required_reviewer_count=required_reviewer_count,
            )
        )

    targets.sort(
        key=lambda item: (
            item["radar"],
            item["pulse"],
            float(item["elevation_deg"]),
            item["date"],
            item["time"],
            item["target_id"],
        )
    )
    report = {
        "schema": TEMPORAL_REVIEW_SCHEMA,
        "schema_version": TEMPORAL_REVIEW_SCHEMA_VERSION,
        "review_id": TEMPORAL_REVIEW_ID,
        "generated_at": _now_utc(),
        "validation_results_sha256": canonical_json_sha256(validation),
        "frozen_policy_sha256": canonical_json_sha256(frozen_policy),
        "temporal_manifest_sha256": canonical_json_sha256(
            temporal_manifest
        ),
        "download_ledger_sha256": canonical_json_sha256(download_ledger),
        "configuration_sha256": validation["configuration_sha256"],
        "selection": {
            "source_split": "validation",
            "sealed_holdout_opened": False,
            "targets_per_geometry": 2,
            "candidate_challenge_per_geometry": 1,
            "candidate_independent_control_per_geometry": 1,
            "reported_regression_count": len(regression_cases),
            "challenge_control_identity_visible_to_reviewer": False,
            "required_reviewer_count": required_reviewer_count,
            "all_targets_require_independent_double_review": required_reviewer_count == 2,
            "primary_qc_outputs_visible": False,
            "primary_ci_visible": False,
            "visible_evidence": (
                "raw current companion fields plus raw previous, next, "
                "and upper-elevation DBZH/VRAD where available"
            ),
        },
        "expected_geometry_count": len(policy_targets),
        "geometry_count": len(records_by_target),
        "target_count": len(targets),
        "counts": temporal_review_counts(targets),
        "targets": targets,
    }
    errors = validate_temporal_review_target_manifest(
        report,
        validation=validation,
        frozen_policy=frozen_policy,
        temporal_manifest=temporal_manifest,
        download_ledger=download_ledger,
    )
    if errors:
        raise ValueError("; ".join(errors))
    return report


def validate_temporal_review_target_manifest(
    review: Mapping[str, Any],
    *,
    validation: Mapping[str, Any],
    frozen_policy: Mapping[str, Any],
    temporal_manifest: Mapping[str, Any],
    download_ledger: Mapping[str, Any],
) -> list[str]:
    """Validate leakage, source integrity, geometry coverage, and blinding."""

    errors: list[str] = []
    targets = list(review.get("targets", ()))
    policy_ids = {
        str(item["target_id"])
        for item in frozen_policy.get("targets", ())
    }
    manifest_files = {
        str(item["source_id"]): item
        for item in temporal_manifest.get("files", ())
    }
    ledger_files = _normalised_ledger_files(download_ledger)
    if review.get("schema") != TEMPORAL_REVIEW_SCHEMA:
        errors.append("invalid temporal-review schema")
    if review.get("review_id") != TEMPORAL_REVIEW_ID:
        errors.append("invalid temporal-review id")
    if review.get("validation_results_sha256") != canonical_json_sha256(
        validation
    ):
        errors.append("validation-results hash mismatch")
    if review.get("frozen_policy_sha256") != canonical_json_sha256(
        frozen_policy
    ):
        errors.append("frozen-policy hash mismatch")
    if review.get("temporal_manifest_sha256") != canonical_json_sha256(
        temporal_manifest
    ):
        errors.append("temporal-manifest hash mismatch")
    if review.get("download_ledger_sha256") != canonical_json_sha256(
        download_ledger
    ):
        errors.append("download-ledger hash mismatch")

    target_ids = [str(item.get("target_id") or "") for item in targets]
    if not all(target_ids) or len(target_ids) != len(set(target_ids)):
        errors.append("review target ids must be non-empty and unique")
    roles_by_geometry: dict[str, Counter[str]] = defaultdict(Counter)
    for target in targets:
        prefix = str(target.get("target_id") or "unknown")
        role = str(target.get("selection_role_internal") or "")
        geometry_id = str(target.get("geometry_id") or "")
        if role != "reported_regression":
            roles_by_geometry[geometry_id][role] += 1
        if target.get("selection_role") != "stratified_case":
            errors.append(f"{prefix}: selection identity is exposed")
        required_count = review.get("selection", {}).get(
            "required_reviewer_count", 1
        )
        if target.get("required_reviewer_count") != required_count:
            errors.append(f"{prefix}: reviewer requirement mismatch")
        if target.get("double_review_required") is not (required_count == 2):
            errors.append(f"{prefix}: double-review requirement mismatch")
        if target.get("primary_qc_outputs_visible") is not False:
            errors.append(f"{prefix}: QC outputs are visible")
        hidden = {str(value) for value in target.get("primary_hidden_fields", ())}
        if "CI" not in hidden:
            errors.append(f"{prefix}: CI is not hidden")
        shape = target.get("shape")
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or any(not isinstance(value, int) or value <= 0 for value in shape)
        ):
            errors.append(f"{prefix}: invalid sweep shape")
        views = list(target.get("review_views", ()))
        primary = [
            view
            for view in views
            if view.get("annotation_primary") is True
        ]
        if (
            len(primary) != 1
            or primary[0].get("quantity") != "DBZH"
            or primary[0].get("role") != "current"
        ):
            errors.append(f"{prefix}: invalid primary DBZH view")
        if any(str(view.get("quantity")) == "CI" for view in views):
            errors.append(f"{prefix}: CI view is exposed")
        view_ids = [str(view.get("view_id") or "") for view in views]
        if not all(view_ids) or len(view_ids) != len(set(view_ids)):
            errors.append(f"{prefix}: review view ids are invalid")
        for view in views:
            source = view.get("source") or {}
            source_kind = str(source.get("source_kind") or "")
            source_id = str(source.get("source_id") or "")
            expected_hash = str(source.get("sha256") or "")
            if len(expected_hash) != 64:
                errors.append(f"{prefix}: invalid source hash for {source_id}")
            if source_kind == "temporal":
                manifest_entry = manifest_files.get(source_id)
                ledger_entry = ledger_files.get(source_id)
                if manifest_entry is None or ledger_entry is None:
                    errors.append(
                        f"{prefix}: unresolved temporal source {source_id}"
                    )
                    continue
                if manifest_entry.get("split") != "validation":
                    errors.append(
                        f"{prefix}: non-validation temporal source {source_id}"
                    )
                if str(ledger_entry.get("sha256") or "") != expected_hash:
                    errors.append(
                        f"{prefix}: ledger hash mismatch for {source_id}"
                    )
            elif source_kind != "regression":
                errors.append(
                    f"{prefix}: unsupported source kind {source_kind!r}"
                )

    if set(roles_by_geometry) != policy_ids:
        missing = sorted(policy_ids - set(roles_by_geometry))
        extra = sorted(set(roles_by_geometry) - policy_ids)
        errors.append(
            f"geometry coverage mismatch; missing={missing}, extra={extra}"
        )
    required_roles = Counter(
        {
            "candidate_challenge": 1,
            "candidate_independent_control": 1,
        }
    )
    for geometry_id, roles in roles_by_geometry.items():
        if roles != required_roles:
            errors.append(
                f"{geometry_id}: challenge/control allocation {dict(roles)}"
            )
    if review.get("selection", {}).get("sealed_holdout_opened") is not False:
        errors.append("sealed holdout is not explicitly closed")
    return errors


def temporal_review_counts(
    targets: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    entries = list(targets)
    return {
        "by_pulse": dict(
            sorted(Counter(str(item["pulse"]) for item in entries).items())
        ),
        "by_internal_role": dict(
            sorted(
                Counter(
                    str(item["selection_role_internal"])
                    for item in entries
                ).items()
            )
        ),
        "by_policy_state": dict(
            sorted(
                Counter(
                    str(item.get("policy_state") or "regression")
                    for item in entries
                ).items()
            )
        ),
        "by_elevation": dict(
            sorted(
                Counter(
                    f"{float(item['elevation_deg']):.2f}"
                    for item in entries
                ).items()
            )
        ),
        "double_review_count": sum(
            item.get("double_review_required") is True for item in entries
        ),
    }


def write_temporal_review_artifacts(
    review: Mapping[str, Any],
    output_dir: str | Path,
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    targets_path = output / "review_targets.json"
    targets_path.write_text(
        json.dumps(review, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest_path = output / "review_targets.sha256"
    digest_path.write_text(
        f"{canonical_json_sha256(review)}  review_targets.json\n",
        encoding="utf-8",
    )
    progress = {
        "schema": "uk_wsr_qc_temporal_review_progress",
        "schema_version": 1,
        "review_id": TEMPORAL_REVIEW_ID,
        "review_targets_sha256": canonical_json_sha256(review),
        "generated_at": _now_utc(),
        "assignments": [],
        "completed_primary_target_ids": [],
        "completed_secondary_target_ids": [],
        "adjudicated_target_ids": [],
    }
    progress_path = output / "review_progress.template.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme_path = output / "README.md"
    readme_path.write_text(_review_markdown(review), encoding="utf-8")
    return targets_path, digest_path, progress_path, readme_path


def _temporal_target(
    record: Mapping[str, Any],
    *,
    selection_role_internal: str,
    policy_target: Mapping[str, Any],
    manifest_files: Mapping[str, Mapping[str, Any]],
    ledger_files: Mapping[str, Mapping[str, Any]],
    required_reviewer_count: int,
) -> dict[str, Any]:
    current = _temporal_source(
        record["source"],
        manifest_files=manifest_files,
        ledger_files=ledger_files,
    )
    context = record.get("context") or {}
    views = [
        _view(
            "current_dbzh",
            "Current DBZH",
            "current",
            "DBZH",
            current,
            annotation_primary=True,
        )
    ]
    companions = {str(value).upper() for value in record.get("companions", ())}
    for quantity in CURRENT_VISIBLE_FIELDS:
        if quantity == "DBZH" or quantity not in companions:
            continue
        views.append(
            _view(
                f"current_{quantity.lower()}",
                f"Current {quantity}",
                "current",
                quantity,
                current,
            )
        )
    for role in ("previous", "next"):
        source_context = context.get(role)
        if not source_context:
            continue
        source = _temporal_source(
            source_context,
            manifest_files=manifest_files,
            ledger_files=ledger_files,
        )
        for quantity in CONTEXT_VISIBLE_FIELDS:
            views.append(
                _view(
                    f"{role}_{quantity.lower()}",
                    f"{role.title()} {quantity}",
                    role,
                    quantity,
                    source,
                )
            )
    upper_context = context.get("upper_elevation")
    if upper_context:
        source = _temporal_source(
            {
                **dict(record["source"]),
                **dict(upper_context),
                "source_id": upper_context.get("source_id")
                or record["source"]["source_id"],
            },
            manifest_files=manifest_files,
            ledger_files=ledger_files,
        )
        for quantity in CONTEXT_VISIBLE_FIELDS:
            views.append(
                _view(
                    f"upper_{quantity.lower()}",
                    f"Upper elevation {quantity}",
                    "upper_elevation",
                    quantity,
                    source,
                )
            )
    return _target_record(
        record,
        selection_role_internal=selection_role_internal,
        policy_state=str(policy_target["state"]),
        policy_blockers=list(policy_target.get("blockers", ())),
        review_views=views,
        required_reviewer_count=required_reviewer_count,
    )


def _regression_target(
    record: Mapping[str, Any],
    case: Mapping[str, Any],
    *,
    required_reviewer_count: int,
) -> dict[str, Any]:
    files = {str(item["role"]): item for item in case.get("files", ())}
    current = _regression_source(
        record["source"],
        files["current"],
    )
    views = [
        _view(
            "current_dbzh",
            "Current DBZH",
            "current",
            "DBZH",
            current,
            annotation_primary=True,
        )
    ]
    companions = {str(value).upper() for value in record.get("companions", ())}
    for quantity in CURRENT_VISIBLE_FIELDS:
        if quantity == "DBZH" or quantity not in companions:
            continue
        views.append(
            _view(
                f"current_{quantity.lower()}",
                f"Current {quantity}",
                "current",
                quantity,
                current,
            )
        )
    context = record.get("context") or {}
    for role in ("previous", "next"):
        source_context = context.get(role)
        source_file = files.get(role)
        if not source_context or not source_file:
            continue
        source = _regression_source(source_context, source_file)
        for quantity in CONTEXT_VISIBLE_FIELDS:
            views.append(
                _view(
                    f"{role}_{quantity.lower()}",
                    f"{role.title()} {quantity}",
                    role,
                    quantity,
                    source,
                )
            )
    upper = context.get("upper_elevation")
    if upper:
        source = _regression_source(
            {
                **dict(record["source"]),
                **dict(upper),
                "source_id": upper.get("source_id")
                or record["source"]["source_id"],
            },
            files["current"],
        )
        for quantity in CONTEXT_VISIBLE_FIELDS:
            views.append(
                _view(
                    f"upper_{quantity.lower()}",
                    f"Upper elevation {quantity}",
                    "upper_elevation",
                    quantity,
                    source,
                )
            )
    return _target_record(
        record,
        selection_role_internal="reported_regression",
        policy_state="reported_regression",
        policy_blockers=["independent blinded review required"],
        review_views=views,
        required_reviewer_count=required_reviewer_count,
    )


def _target_record(
    record: Mapping[str, Any],
    *,
    selection_role_internal: str,
    policy_state: str,
    policy_blockers: list[str],
    review_views: list[dict[str, Any]],
    required_reviewer_count: int,
) -> dict[str, Any]:
    digest = sha256(
        (
            f"{record['job_id']}|{selection_role_internal}|"
            f"{TEMPORAL_REVIEW_ID}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "target_id": f"temporal-{digest}",
        "geometry_id": str(record["target_id"]),
        "job_id": str(record["job_id"]),
        "radar": str(record["radar"]),
        "pulse": str(record["pulse"]),
        "date": str(record["source"]["date"]),
        "time": str(record["source"]["time"]),
        "quantity": "DBZH",
        "dataset": str(record["source"]["dataset"]),
        "elevation_deg": float(record["elevation_deg"]),
        "shape": [int(value) for value in record["shape"]],
        "split": str(record["split"]),
        "season": _season(str(record["source"]["date"])),
        "utc_slot": _utc_slot(str(record["source"]["time"])),
        "selection_role": "stratified_case",
        "selection_role_internal": selection_role_internal,
        "policy_state": policy_state,
        "policy_blockers": policy_blockers,
        "required_reviewer_count": required_reviewer_count,
        "double_review_required": required_reviewer_count == 2,
        "review_status": "unreviewed",
        "primary_qc_outputs_visible": False,
        "primary_hidden_fields": list(HIDDEN_FIELDS),
        "review_views": review_views,
        "scoring_artifact": {
            "npz": str(record["artifact_npz"]),
            "sha256": str(record["artifact_sha256"]),
            "array_hash": str(record["artifact_array_hash"]),
            "configuration_sha256": str(record["configuration_sha256"]),
        },
    }


def _temporal_source(
    raw: Mapping[str, Any],
    *,
    manifest_files: Mapping[str, Mapping[str, Any]],
    ledger_files: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source_id = str(raw["source_id"])
    manifest = manifest_files.get(source_id)
    ledger = ledger_files.get(source_id)
    if manifest is None or ledger is None:
        raise ValueError(f"unresolved temporal source {source_id}")
    if manifest.get("split") != "validation":
        raise ValueError(f"{source_id}: source is not in validation split")
    expected_hash = str(raw.get("sha256") or ledger.get("sha256") or "")
    if str(ledger.get("sha256") or "") != expected_hash:
        raise ValueError(f"{source_id}: source hash mismatch")
    return {
        "source_kind": "temporal",
        "source_id": source_id,
        "sha256": expected_hash,
        "size_bytes": int(ledger["size_bytes"]),
        "filename": str(manifest["filename"]),
        "url": str(manifest["object_url"]),
        "date": str(raw.get("date") or manifest["date"]),
        "time": str(raw.get("time") or manifest["time"]),
        "dataset": str(raw["dataset"]),
    }


def _regression_source(
    raw: Mapping[str, Any],
    file_entry: Mapping[str, Any],
) -> dict[str, Any]:
    expected_hash = str(raw.get("sha256") or file_entry.get("sha256") or "")
    if expected_hash != str(file_entry.get("sha256") or ""):
        raise ValueError("regression source hash mismatch")
    return {
        "source_kind": "regression",
        "source_id": str(raw["source_id"]),
        "sha256": expected_hash,
        "size_bytes": int(file_entry["size_bytes"]),
        "filename": str(file_entry["filename"]),
        "url": str(file_entry["url"]),
        "date": str(raw["date"]),
        "time": str(raw["time"]),
        "dataset": str(raw["dataset"]),
    }


def _view(
    view_id: str,
    label: str,
    role: str,
    quantity: str,
    source: Mapping[str, Any],
    *,
    annotation_primary: bool = False,
) -> dict[str, Any]:
    return {
        "view_id": view_id,
        "label": label,
        "role": role,
        "quantity": quantity,
        "annotation_primary": bool(annotation_primary),
        "source": dict(source),
    }


def _candidate_independent_control(
    records: Sequence[Mapping[str, Any]],
    target_id: str,
) -> Mapping[str, Any]:
    index = int(
        sha256(
            f"{TEMPORAL_REVIEW_ID}|{target_id}|control".encode("utf-8")
        ).hexdigest()[:16],
        16,
    ) % len(records)
    return records[index]


def _challenge_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    delta = record.get("delta") or {}
    learned = delta.get("learned_increment_dbzh") or {}
    baseline = (record.get("baseline") or {}).get("removed_dbzh") or {}
    return (
        float(learned.get("linear_reflectivity_fraction") or 0.0),
        int(delta.get("learned_increment_count") or 0),
        float(baseline.get("linear_reflectivity_fraction") or 0.0),
        float((record.get("baseline") or {}).get("removed_fraction") or 0.0),
        str(record["job_id"]),
    )


def _record_order_key(record: Mapping[str, Any]) -> tuple[str, ...]:
    source = record.get("source") or {}
    return (
        str(source.get("date") or ""),
        str(source.get("time") or ""),
        str(record.get("job_id") or ""),
    )


def _normalised_ledger_files(
    ledger: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    raw = ledger.get("files", {})
    rows = list(raw.values()) if isinstance(raw, Mapping) else list(raw)
    return {str(item["source_id"]): item for item in rows}


def _validate_inputs(
    validation: Mapping[str, Any],
    frozen_policy: Mapping[str, Any],
    temporal_manifest: Mapping[str, Any],
    download_ledger: Mapping[str, Any],
) -> None:
    if validation.get("schema") != "uk_wsr_background_validation_results":
        raise ValueError("unexpected validation-results schema")
    if validation.get("complete") is not True:
        raise ValueError("validation results are incomplete")
    if validation.get("split") != "validation":
        raise ValueError("temporal review requires validation split")
    if frozen_policy.get("schema") != "uk_wsr_background_validation_policy":
        raise ValueError("unexpected frozen-policy schema")
    if temporal_manifest.get("schema") != "uk_wsr_temporal_context_manifest":
        raise ValueError("unexpected temporal-manifest schema")
    if download_ledger.get("schema") != "uk_wsr_temporal_context_download_ledger":
        raise ValueError("unexpected temporal download-ledger schema")
    if (
        frozen_policy.get("configuration_sha256")
        != validation.get("configuration_sha256")
    ):
        raise ValueError("frozen policy configuration mismatch")
    if frozen_policy.get("target_count") != validation.get(
        "summary", {}
    ).get("target_count"):
        raise ValueError("frozen policy target count mismatch")


def _review_markdown(review: Mapping[str, Any]) -> str:
    counts = review["counts"]
    return f"""# UK WSR Temporal QC Blinded Review

Status: **ready for independent review; sealed holdout remains closed**

This package contains {review['target_count']:,} raw review targets covering
{review['geometry_count']:,} validation geometries. Each geometry contributes
one candidate-challenge scan and one candidate-independent control. The package
also contains {counts['by_internal_role'].get('reported_regression', 0):,}
reported regressions.

- LP targets: {counts['by_pulse'].get('lp', 0):,}
- SP targets: {counts['by_pulse'].get('sp', 0):,}
- Required blinded reviews per target: {review['selection']['required_reviewer_count']}

Reviewers see raw current companion fields and raw previous, next, and
upper-elevation context where available. They do not see CI, Candidate 5 masks,
community masks, the challenge/control identity, or the reported-failure text.
Ambiguous gates must be labelled `uncertain` and excluded from accuracy scores.
"""


def _season(date: str) -> str:
    month = int(date[4:6])
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _utc_slot(time: str) -> str:
    hour = int(time[:2])
    return "day" if 6 <= hour < 19 else "night"


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
