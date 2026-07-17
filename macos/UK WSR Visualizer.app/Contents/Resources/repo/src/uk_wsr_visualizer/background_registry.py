"""Qualification registry for packaged learned background models."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKGROUND_MODEL_REGISTRY_SCHEMA = "uk_wsr_background_model_manifest"
BACKGROUND_MODEL_REGISTRY_SCHEMA_VERSION = 2
BACKGROUND_MODEL_QC_VERSION = "qc-v2"

REQUIRED_RUNTIME_ARRAYS = (
    "sample_count",
    "persistent_echo_frequency",
    "dbzh_p90",
    "near_zero_vrad_frequency",
    "ci_sample_count",
    "low_ci_frequency",
)

DATE_HELD_OUT_VALIDATION_DESIGNS = (
    "date_held_out",
    "site_and_date_held_out",
)


@dataclass(frozen=True)
class BackgroundModelRegistryPolicy:
    """Hard release gates for a model that may be selected automatically."""

    minimum_training_dates: int = 7
    minimum_training_span_days: int = 14
    minimum_validation_dates: int = 2
    required_qc_version: str = BACKGROUND_MODEL_QC_VERSION
    required_runtime_arrays: tuple[str, ...] = REQUIRED_RUNTIME_ARRAYS
    accepted_validation_designs: tuple[str, ...] = DATE_HELD_OUT_VALIDATION_DESIGNS


def load_background_model_registry(path: str | Path) -> dict[str, Any] | None:
    """Load a versioned registry, failing closed for missing or legacy manifests."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != BACKGROUND_MODEL_REGISTRY_SCHEMA:
        return None
    try:
        version = int(payload.get("schema_version") or 0)
    except (TypeError, ValueError):
        return None
    if version < BACKGROUND_MODEL_REGISTRY_SCHEMA_VERSION:
        return None
    if not isinstance(payload.get("models"), list):
        return None
    return payload


def eligible_registry_entries(payload: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
    """Return only entries explicitly promoted for qc-v2 automatic use."""

    if not isinstance(payload, dict):
        return ()
    if payload.get("schema") != BACKGROUND_MODEL_REGISTRY_SCHEMA:
        return ()
    try:
        version = int(payload.get("schema_version") or 0)
    except (TypeError, ValueError):
        return ()
    if version < BACKGROUND_MODEL_REGISTRY_SCHEMA_VERSION:
        return ()
    models = payload.get("models")
    if not isinstance(models, list):
        return ()
    return tuple(
        entry
        for entry in models
        if isinstance(entry, dict)
        and entry.get("filename")
        and entry.get("eligible_for_default") is True
        and entry.get("status") == "qualified"
        and entry.get("qc_version") == BACKGROUND_MODEL_QC_VERSION
        and not entry.get("qualification_reasons")
    )


def audit_background_model_registry(
    model_dir: str | Path,
    *,
    manifest_path: str | Path | None = None,
    policy: BackgroundModelRegistryPolicy | None = None,
) -> dict[str, Any]:
    """Audit every manifest entry and return a schema-v2 qualification registry."""

    directory = Path(model_dir)
    source_manifest = Path(manifest_path) if manifest_path is not None else directory / "manifest.json"
    raw = _load_json(source_manifest)
    raw_models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(raw_models, list):
        raw_models = [
            {"filename": str(path.relative_to(directory))}
            for path in sorted(directory.rglob("*.json"))
            if path.name != "manifest.json"
        ]

    selected_policy = policy or BackgroundModelRegistryPolicy()
    models = [
        _audit_entry(entry, directory=directory, policy=selected_policy)
        for entry in raw_models
        if isinstance(entry, dict) and entry.get("filename")
    ]
    models.sort(key=_entry_sort_key)
    eligible_count = sum(entry["eligible_for_default"] for entry in models)
    reason_counts = Counter(
        reason
        for entry in models
        for reason in entry.get("qualification_reasons", [])
    )
    return {
        "schema": BACKGROUND_MODEL_REGISTRY_SCHEMA,
        "schema_version": BACKGROUND_MODEL_REGISTRY_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "qc_version": BACKGROUND_MODEL_QC_VERSION,
        "status": "qualified" if eligible_count == len(models) and models else "qualification_audit",
        "qualification_policy": _policy_manifest(selected_policy),
        "model_count": len(models),
        "eligible_model_count": eligible_count,
        "quarantined_model_count": len(models) - eligible_count,
        "qualification_reason_counts": dict(sorted(reason_counts.items())),
        "models": models,
    }


def registry_audit_markdown(payload: dict[str, Any]) -> str:
    """Render a concise, publishable Markdown qualification audit."""

    models = [entry for entry in payload.get("models", []) if isinstance(entry, dict)]
    radar_rows: list[str] = []
    radars = sorted({str(entry.get("radar") or "unknown") for entry in models})
    for radar in radars:
        selected = [entry for entry in models if str(entry.get("radar") or "unknown") == radar]
        lp_count = sum(str(entry.get("pulse") or "").lower() == "lp" for entry in selected)
        sp_count = sum(str(entry.get("pulse") or "").lower() == "sp" for entry in selected)
        eligible = sum(entry.get("eligible_for_default") is True for entry in selected)
        radar_rows.append(f"| {radar} | {lp_count} | {sp_count} | {len(selected)} | {eligible} | {len(selected) - eligible} |")

    reason_rows = [
        f"| `{reason}` | {count} |"
        for reason, count in sorted((payload.get("qualification_reason_counts") or {}).items())
    ]
    policy = payload.get("qualification_policy") or {}
    return f"""# Learned Background Model Registry: qc-v2 Qualification Audit

Status: **{payload.get('quarantined_model_count', 0)} models quarantined; {payload.get('eligible_model_count', 0)} eligible for automatic use.**

This audit supersedes the July 2026 same-day learned-background validation as
release evidence. A model is not selected automatically merely because its
file is packaged. It must be explicitly qualified in this schema-v2 registry
and must pass the independent runtime diversity check.

## Release Policy

- Required QC contract: `{policy.get('required_qc_version', BACKGROUND_MODEL_QC_VERSION)}`
- Minimum training dates: {policy.get('minimum_training_dates')}
- Minimum training span: {policy.get('minimum_training_span_days')} days
- Minimum independently held-out validation dates: {policy.get('minimum_validation_dates')}
- Accepted validation designs: {', '.join(f'`{value}`' for value in policy.get('accepted_validation_designs', []))}
- Required runtime arrays: {', '.join(f'`{value}`' for value in policy.get('required_runtime_arrays', []))}

## Network Coverage

| Radar | LP targets | SP targets | Total | Eligible | Quarantined |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(radar_rows)}

## Qualification Failures

| Reason | Models |
| --- | ---: |
{chr(10).join(reason_rows)}

## Interpretation

The quarantined files remain available only as historical qc-v1 research
artifacts. They are excluded from desktop and iOS automatic selection. They
must not be described as validated clutter-removal defaults.

The next qualifying run must train across multiple dates and validate on
different dates. It must also persist CI statistics required by qc-v2 and pass
the signal-retention and vertical-profile release gates.
"""


def _audit_entry(
    original: dict[str, Any],
    *,
    directory: Path,
    policy: BackgroundModelRegistryPolicy,
) -> dict[str, Any]:
    entry = dict(original)
    filename = str(entry.get("filename") or "")
    model_path = _safe_model_path(directory, filename)
    model_payload = _load_json(model_path) if model_path is not None else {}
    key = model_payload.get("key") if isinstance(model_payload.get("key"), dict) else {}
    metadata = model_payload.get("metadata") if isinstance(model_payload.get("metadata"), dict) else {}

    training_dates = _training_dates(entry, key, metadata)
    source_date_count = _int_value(
        metadata.get("source_date_count"),
        entry.get("source_date_count"),
        default=len(training_dates),
    )
    if source_date_count == 0 and training_dates:
        source_date_count = len(training_dates)
    source_start_date = str(
        metadata.get("source_start_date")
        or entry.get("source_start_date")
        or (training_dates[0] if training_dates else "")
    ) or None
    source_end_date = str(
        metadata.get("source_end_date")
        or entry.get("source_end_date")
        or (training_dates[-1] if training_dates else "")
    ) or None
    training_span_days = _int_value(
        metadata.get("training_span_days"),
        entry.get("training_span_days"),
        default=_date_span_days(training_dates),
    )
    validation_dates = sorted(
        {
            _normalise_date(value)
            for value in entry.get("validation_dates", [])
            if _normalise_date(value)
        }
    )
    validation_date_count = _int_value(
        entry.get("validation_date_count"),
        default=len(validation_dates),
    )
    validation_design = str(entry.get("validation_design") or "same_day_within_sequence")
    qc_version = str(entry.get("qc_version") or metadata.get("qc_version") or "qc-v1-legacy")
    arrays = model_payload.get("inline_arrays")
    if not isinstance(arrays, dict):
        arrays = model_payload.get("arrays") if isinstance(model_payload.get("arrays"), dict) else {}
    array_names = sorted(str(name) for name in arrays)
    missing_arrays = sorted(set(policy.required_runtime_arrays) - set(array_names))

    reasons: list[str] = []
    if model_path is None:
        reasons.append("unsafe_model_path")
    elif not model_path.exists():
        reasons.append("model_file_missing")
    elif not model_payload:
        reasons.append("model_file_unreadable")
    if qc_version != policy.required_qc_version:
        reasons.append(f"qc_version:{qc_version}!={policy.required_qc_version}")
    if source_date_count < policy.minimum_training_dates:
        reasons.append(
            f"insufficient_training_dates:{source_date_count}<{policy.minimum_training_dates}"
        )
    if training_span_days < policy.minimum_training_span_days:
        reasons.append(
            f"insufficient_training_span_days:{training_span_days}<{policy.minimum_training_span_days}"
        )
    if validation_design not in policy.accepted_validation_designs:
        reasons.append(f"validation_design:{validation_design}")
    if validation_date_count < policy.minimum_validation_dates:
        reasons.append(
            f"insufficient_validation_dates:{validation_date_count}<{policy.minimum_validation_dates}"
        )
    if missing_arrays:
        reasons.append(f"missing_runtime_arrays:{','.join(missing_arrays)}")

    eligible = not reasons
    return entry | {
        "filename": filename,
        "radar": entry.get("radar") or key.get("radar"),
        "pulse": entry.get("pulse") or key.get("pulse"),
        "quantity": entry.get("quantity") or key.get("quantity"),
        "dataset": entry.get("dataset") or key.get("dataset"),
        "elevation_deg": entry.get("elevation_deg", key.get("elevation_deg")),
        "qc_version": qc_version,
        "source_date_count": source_date_count,
        "source_start_date": source_start_date,
        "source_end_date": source_end_date,
        "training_span_days": training_span_days,
        "validation_design": validation_design,
        "validation_dates": validation_dates,
        "validation_date_count": validation_date_count,
        "runtime_array_names": array_names,
        "eligible_for_default": eligible,
        "status": "qualified" if eligible else "quarantined",
        "qualification_reasons": reasons,
        "qualification_reason": None if eligible else ";".join(reasons),
    }


def _safe_model_path(directory: Path, filename: str) -> Path | None:
    if not filename:
        return None
    root = directory.resolve()
    candidate = (directory / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _training_dates(entry: dict[str, Any], key: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    source_dates = metadata.get("source_dates")
    if isinstance(source_dates, list):
        values.extend(source_dates)
    for name in ("source_start_date", "source_end_date", "training_date"):
        values.append(metadata.get(name))
        values.append(entry.get(name))
        values.append(key.get(name))
    first_source = metadata.get("first_source")
    if isinstance(first_source, dict):
        values.append(first_source.get("date"))
    return sorted({_normalise_date(value) for value in values if _normalise_date(value)})


def _normalise_date(value: Any) -> str:
    text = str(value or "").replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return ""
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return ""
    return text


def _date_span_days(values: list[str]) -> int:
    if len(values) < 2:
        return 0
    parsed = [datetime.strptime(value, "%Y%m%d").date() for value in values]
    return (max(parsed) - min(parsed)).days


def _int_value(*values: Any, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return int(default)


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _entry_sort_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    dataset = str(entry.get("dataset") or "")
    suffix = dataset.lower().removeprefix("dataset")
    dataset_order = int(suffix) if suffix.isdigit() else 10_000
    return (
        str(entry.get("radar") or ""),
        str(entry.get("pulse") or ""),
        dataset_order,
        dataset,
        float(entry.get("elevation_deg") or 0.0),
    )


def _policy_manifest(policy: BackgroundModelRegistryPolicy) -> dict[str, Any]:
    payload = asdict(policy)
    payload["required_runtime_arrays"] = list(policy.required_runtime_arrays)
    payload["accepted_validation_designs"] = list(policy.accepted_validation_designs)
    return payload


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
