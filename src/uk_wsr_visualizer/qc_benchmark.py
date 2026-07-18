"""Independent real-data benchmark contracts for UK WSR quality control."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable

from .field_audit import PUBLIC_BASE

BENCHMARK_ID = "uk-wsr-qc-real-v1"
BENCHMARK_SCHEMA_VERSION = 1
ANNOTATION_SCHEMA_VERSION = 1
DEFAULT_MAX_DAY_OFFSET = 14
DEFAULT_MAX_TIME_OFFSET_MINUTES = 20
DEFAULT_MINIMUM_DAY_COVERAGE_FRACTION = 0.80


@dataclass(frozen=True)
class BenchmarkAnchor:
    anchor_id: str
    target_date: str
    target_time: str
    season: str
    utc_slot: str
    split: str


def _anchors_for_date(
    date: str,
    season: str,
    split: str,
    times: tuple[str, str],
) -> tuple[BenchmarkAnchor, BenchmarkAnchor]:
    return tuple(
        BenchmarkAnchor(
            anchor_id=f"{season}-{split}-{time}",
            target_date=date,
            target_time=time,
            season=season,
            utc_slot={
                "0000": "overnight",
                "0400": "pre_dawn",
                "0800": "morning",
                "1200": "midday",
                "1800": "evening_transition",
                "2200": "late_evening",
            }[time],
            split=split,
        )
        for time in times
    )


# Each season has six UTC slots on three separated dates. The assignment of
# slot pairs rotates across splits to avoid confounding split with time of day.
DEFAULT_BENCHMARK_ANCHORS: tuple[BenchmarkAnchor, ...] = (
    *_anchors_for_date("20240101", "winter", "development", ("0000", "1200")),
    *_anchors_for_date("20241208", "winter", "validation", ("0400", "1800")),
    *_anchors_for_date("20241221", "winter", "holdout", ("0800", "2200")),
    *_anchors_for_date("20240315", "spring", "development", ("0400", "1800")),
    *_anchors_for_date("20240410", "spring", "validation", ("0800", "2200")),
    *_anchors_for_date("20240519", "spring", "holdout", ("0000", "1200")),
    *_anchors_for_date("20240615", "summer", "development", ("0800", "2200")),
    *_anchors_for_date("20240713", "summer", "validation", ("0000", "1200")),
    *_anchors_for_date("20240629", "summer", "holdout", ("0400", "1800")),
    *_anchors_for_date("20240921", "autumn", "development", ("0800", "2200")),
    *_anchors_for_date("20241008", "autumn", "validation", ("0400", "1800")),
    *_anchors_for_date("20241019", "autumn", "holdout", ("0000", "1200")),
)

LABEL_TAXONOMY: dict[str, dict[str, str]] = {
    "receiver_noise": {
        "action": "remove",
        "family": "noise",
        "description": "Receiver or processing noise without coherent atmospheric structure.",
    },
    "static_ground_clutter": {
        "action": "remove",
        "family": "clutter",
        "description": "Persistent terrain, building, mast, or other stationary ground return.",
    },
    "anomalous_propagation_clutter": {
        "action": "remove",
        "family": "clutter",
        "description": "Transient non-meteorological ground return caused by refractive propagation.",
    },
    "sea_clutter": {
        "action": "remove",
        "family": "clutter",
        "description": "Sea-surface return rather than an atmospheric echo.",
    },
    "wind_turbine_clutter": {
        "action": "remove",
        "family": "clutter",
        "description": "Wind-turbine return, including Doppler-broadened turbine contamination.",
    },
    "radial_interference": {
        "action": "remove",
        "family": "interference",
        "description": "Radial, spoke, or other radio-frequency interference.",
    },
    "isolated_speckle": {
        "action": "remove",
        "family": "noise",
        "description": "Isolated unsupported gates that are not part of a coherent echo.",
    },
    "invalid_measurement": {
        "action": "remove",
        "family": "invalid",
        "description": "Decoded but invalid, saturated, corrupt, or geometrically impossible data.",
    },
    "precipitation": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Rain, snow, hail, melting-layer, or other precipitation echo.",
    },
    "biological_birds": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Bird echo, including migration, roost, or local flight activity.",
    },
    "biological_insects": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Insect echo or an insect-dominated biological layer.",
    },
    "biological_other": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Biological echo that cannot be assigned confidently to birds or insects.",
    },
    "clear_air_atmospheric": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Non-precipitating atmospheric echo, including Bragg or turbulence structure.",
    },
    "mixed_coherent_signal": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Overlapping weather, biological, or clear-air signal that remains scientifically valid.",
    },
    "other_coherent_signal": {
        "action": "retain",
        "family": "coherent_signal",
        "description": "Coherent measured return not covered above; retained by default.",
    },
    "uncertain": {
        "action": "ignore",
        "family": "review",
        "description": "Evidence is insufficient for a remove or retain judgement.",
    },
    "class_boundary": {
        "action": "ignore",
        "family": "review",
        "description": "Transition pixels excluded from strict gate-level scoring.",
    },
}


def build_benchmark_manifest(
    root_catalog: dict[str, Any],
    fetch_json: Callable[[str], dict[str, Any]],
    *,
    anchors: Iterable[BenchmarkAnchor] = DEFAULT_BENCHMARK_ANCHORS,
    pulses: tuple[str, ...] = ("lp", "sp"),
    public_base: str = PUBLIC_BASE,
    max_day_offset: int = DEFAULT_MAX_DAY_OFFSET,
    max_time_offset_minutes: int = DEFAULT_MAX_TIME_OFFSET_MINUTES,
    minimum_day_coverage_fraction: float = DEFAULT_MINIMUM_DAY_COVERAGE_FRACTION,
) -> dict[str, Any]:
    """Select complete, leakage-controlled PVOL cases for every radar."""

    selected_anchors = tuple(anchors)
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    coverage_cache: dict[str, dict[str, Any]] = {}
    catalog_cache: dict[str, dict[str, Any]] = {}
    used_urls: dict[tuple[str, str], set[str]] = defaultdict(set)

    radars = sorted(
        root_catalog.get("radars", []),
        key=lambda value: str(value.get("radar") or ""),
    )
    for radar_entry in radars:
        radar = str(radar_entry.get("radar") or "")
        for anchor in selected_anchors:
            coverage_key = _coverage_key(radar_entry, anchor.target_date[:4])
            if not coverage_key:
                errors.append(_selection_error(radar, anchor, "coverage_missing"))
                continue
            coverage_url = _public_url(public_base, coverage_key)
            try:
                if coverage_url not in coverage_cache:
                    coverage_cache[coverage_url] = fetch_json(coverage_url)
                coverage = coverage_cache[coverage_url]
            except Exception as exc:  # noqa: BLE001 - manifest records catalog failures.
                errors.append(
                    _selection_error(
                        radar,
                        anchor,
                        f"coverage_fetch_failed:{type(exc).__name__}:{exc}",
                    )
                )
                continue

            selection = _select_complete_day(
                coverage.get("days", []),
                anchor=anchor,
                pulses=pulses,
                radar=radar,
                fetch_json=fetch_json,
                catalog_cache=catalog_cache,
                public_base=public_base,
                used_urls=used_urls,
                max_day_offset=max_day_offset,
                max_time_offset_minutes=max_time_offset_minutes,
                minimum_day_coverage_fraction=minimum_day_coverage_fraction,
            )
            if selection is None:
                errors.append(_selection_error(radar, anchor, "complete_volume_missing"))
                continue
            day, pulse_files = selection
            for pulse in pulses:
                source = pulse_files[pulse]
                object_url = str(
                    source.get("object_url")
                    or _public_url(public_base, str(source.get("object_key") or ""))
                )
                used_urls[(radar, pulse)].add(object_url)
                selected_date = str(day["date"])
                selected_time = str(source["time"])
                files.append(
                    {
                        "case_id": _case_id(
                            radar,
                            selected_date,
                            selected_time,
                            pulse,
                            str(source["filename"]),
                        ),
                        "anchor_id": anchor.anchor_id,
                        "split": anchor.split,
                        "season": anchor.season,
                        "utc_slot": anchor.utc_slot,
                        "target_date": anchor.target_date,
                        "target_time": anchor.target_time,
                        "date": selected_date,
                        "time": selected_time,
                        "date_offset_days": _date_distance(selected_date, anchor.target_date),
                        "time_offset_minutes": _time_distance(selected_time, anchor.target_time),
                        "radar": radar,
                        "radar_num": str(radar_entry.get("radar_num") or ""),
                        "pulse": pulse,
                        "quantity": "DBZH",
                        "all_elevations": True,
                        "filename": str(source["filename"]),
                        "object_key": source.get("object_key"),
                        "object_url": object_url,
                        "size_bytes": int(source.get("size_bytes") or 0),
                        "annotation_status": "untriaged",
                        "exclude_from_background_training": True,
                    }
                )

    files.sort(
        key=lambda value: (
            value["radar"],
            value["split"],
            value["target_date"],
            value["target_time"],
            value["pulse"],
        )
    )
    expected_file_count = len(radars) * len(selected_anchors) * len(pulses)
    return {
        "schema": "uk_wsr_qc_benchmark_manifest",
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "generated_at": _now_utc(),
        "selection": {
            "description": (
                "24 independent PVOL volumes per radar and pulse: six UTC slots "
                "in each season, split by date into development, validation, and holdout"
            ),
            "anchors": [asdict(anchor) for anchor in selected_anchors],
            "pulses": list(pulses),
            "all_elevations_per_file": True,
            "max_day_offset": max_day_offset,
            "max_time_offset_minutes": max_time_offset_minutes,
            "minimum_day_coverage_fraction": minimum_day_coverage_fraction,
            "expected_file_count": expected_file_count,
            "leakage_control": (
                "Every listed source is excluded from learned-background training; "
                "all sweeps from one PVOL remain in the same split."
            ),
        },
        "annotation_contract": {
            "taxonomy": LABEL_TAXONOMY,
            "primary_review_blind_to_qc": True,
            "ci_is_evidence_not_ground_truth": True,
            "current_filter_is_not_ground_truth": True,
            "ambiguous_gates_default_to_retain_or_ignore": True,
            "minimum_double_review_fraction": 0.20,
        },
        "radar_count": len(radars),
        "anchor_count": len(selected_anchors),
        "file_count": len(files),
        "errors": errors,
        "counts": benchmark_counts(files),
        "files": files,
    }


def benchmark_counts(files: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries = list(files)
    return {
        "by_split": dict(sorted(Counter(str(item["split"]) for item in entries).items())),
        "by_season": dict(sorted(Counter(str(item["season"]) for item in entries).items())),
        "by_utc_slot": dict(sorted(Counter(str(item["utc_slot"]) for item in entries).items())),
        "by_pulse": dict(sorted(Counter(str(item["pulse"]) for item in entries).items())),
        "by_radar": dict(sorted(Counter(str(item["radar"]) for item in entries).items())),
    }


def validate_benchmark_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    files = list(manifest.get("files", []))
    selection = manifest.get("selection", {})
    anchors = list(selection.get("anchors", []))
    pulses = tuple(str(value) for value in selection.get("pulses", []))
    radar_count = int(manifest.get("radar_count") or 0)
    expected = int(manifest.get("selection", {}).get("expected_file_count") or 0)
    if manifest.get("schema") != "uk_wsr_qc_benchmark_manifest":
        errors.append("invalid manifest schema")
    if manifest.get("benchmark_id") != BENCHMARK_ID:
        errors.append("invalid benchmark id")
    if manifest.get("errors"):
        errors.append(f"selection contains {len(manifest['errors'])} errors")
    if len(files) != expected:
        errors.append(f"file count {len(files)} != expected {expected}")
    case_ids = [str(item.get("case_id") or "") for item in files]
    if len(case_ids) != len(set(case_ids)):
        errors.append("case ids are not unique")
    urls = [str(item.get("object_url") or "") for item in files]
    if len(urls) != len(set(urls)):
        errors.append("source urls are not unique")
    expected_cells = {
        (str(radar), str(anchor["anchor_id"]), pulse)
        for radar in sorted({item.get("radar") for item in files})
        for anchor in anchors
        for pulse in pulses
    }
    actual_cells = {
        (str(item.get("radar")), str(item.get("anchor_id")), str(item.get("pulse")))
        for item in files
    }
    if actual_cells != expected_cells:
        missing = len(expected_cells - actual_cells)
        unexpected = len(actual_cells - expected_cells)
        errors.append(f"radar/anchor/pulse grid mismatch: {missing} missing, {unexpected} unexpected")
    expected_counts = {
        "by_split": _expected_anchor_counts(anchors, "split", radar_count, len(pulses)),
        "by_season": _expected_anchor_counts(anchors, "season", radar_count, len(pulses)),
        "by_utc_slot": _expected_anchor_counts(anchors, "utc_slot", radar_count, len(pulses)),
        "by_pulse": {pulse: radar_count * len(anchors) for pulse in pulses},
    }
    actual_counts = benchmark_counts(files)
    for name, wanted in expected_counts.items():
        if actual_counts.get(name) != wanted:
            errors.append(f"{name} is unbalanced: {actual_counts.get(name)} != {wanted}")
    expected_per_radar = len(anchors) * len(pulses)
    by_radar = actual_counts.get("by_radar", {})
    if len(by_radar) != radar_count or any(
        count != expected_per_radar for count in by_radar.values()
    ):
        errors.append(
            f"by_radar is unbalanced: expected {radar_count} radars with "
            f"{expected_per_radar} files each"
        )
    max_day_offset = int(selection.get("max_day_offset") or 0)
    max_time_offset = int(selection.get("max_time_offset_minutes") or 0)
    for item in files:
        if item.get("split") not in {"development", "validation", "holdout"}:
            errors.append(f"{item.get('case_id')}: invalid split")
        if item.get("pulse") not in {"lp", "sp"}:
            errors.append(f"{item.get('case_id')}: invalid pulse")
        if not item.get("exclude_from_background_training"):
            errors.append(f"{item.get('case_id')}: training exclusion missing")
        if item.get("quantity") != "DBZH" or item.get("all_elevations") is not True:
            errors.append(f"{item.get('case_id')}: DBZH/all-elevation contract missing")
        if int(item.get("date_offset_days") or 0) > max_day_offset:
            errors.append(f"{item.get('case_id')}: date offset exceeds selection limit")
        if int(item.get("time_offset_minutes") or 0) > max_time_offset:
            errors.append(f"{item.get('case_id')}: time offset exceeds selection limit")
    return errors


def annotation_json_schema() -> dict[str, Any]:
    labels = sorted(LABEL_TAXONOMY)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://uk-wsr.example/schemas/qc-annotations-v1.json",
        "title": "UK WSR QC benchmark annotations",
        "type": "object",
        "required": [
            "schema",
            "schema_version",
            "benchmark_id",
            "manifest_sha256",
            "reviewer",
            "items",
        ],
        "properties": {
            "schema": {"const": "uk_wsr_qc_annotations"},
            "schema_version": {"const": ANNOTATION_SCHEMA_VERSION},
            "benchmark_id": {"const": BENCHMARK_ID},
            "manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "reviewer": {"type": "string", "minLength": 1},
            "created_at": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "case_id",
                        "dataset",
                        "quantity",
                        "shape",
                        "review_stage",
                        "qc_outputs_visible",
                        "ci_used_as_ground_truth",
                        "current_filter_used_as_ground_truth",
                        "regions",
                    ],
                    "properties": {
                        "case_id": {"type": "string", "minLength": 1},
                        "dataset": {"type": "string", "pattern": "^dataset[0-9]+$"},
                        "elevation_deg": {"type": ["number", "null"]},
                        "quantity": {"const": "DBZH"},
                        "shape": {
                            "type": "array",
                            "prefixItems": [
                                {"type": "integer", "minimum": 1},
                                {"type": "integer", "minimum": 1},
                            ],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "review_stage": {
                            "enum": ["primary", "secondary", "adjudicated"],
                        },
                        "qc_outputs_visible": {"type": "boolean"},
                        "ci_used_as_ground_truth": {"const": False},
                        "current_filter_used_as_ground_truth": {"const": False},
                        "regions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "region_id",
                                    "label",
                                    "action",
                                    "confidence",
                                    "geometry",
                                ],
                                "properties": {
                                    "region_id": {"type": "string", "minLength": 1},
                                    "label": {"enum": labels},
                                    "action": {"enum": ["remove", "retain", "ignore"]},
                                    "confidence": {
                                        "type": "number",
                                        "minimum": 0.0,
                                        "maximum": 1.0,
                                    },
                                    "geometry": {
                                        "oneOf": [
                                            {
                                                "type": "object",
                                                "required": ["type", "vertices"],
                                                "properties": {
                                                    "type": {"const": "polar_gate_polygon"},
                                                    "vertices": {
                                                        "type": "array",
                                                        "minItems": 3,
                                                        "items": {
                                                            "type": "array",
                                                            "prefixItems": [
                                                                {"type": "number"},
                                                                {"type": "number"},
                                                            ],
                                                            "minItems": 2,
                                                            "maxItems": 2,
                                                        },
                                                    },
                                                },
                                            },
                                            {
                                                "type": "object",
                                                "required": ["type", "runs"],
                                                "properties": {
                                                    "type": {"const": "row_major_rle"},
                                                    "runs": {
                                                        "type": "array",
                                                        "items": {
                                                            "type": "array",
                                                            "prefixItems": [
                                                                {"type": "integer", "minimum": 0},
                                                                {"type": "integer", "minimum": 1},
                                                            ],
                                                            "minItems": 2,
                                                            "maxItems": 2,
                                                        },
                                                    },
                                                },
                                            },
                                            {
                                                "type": "object",
                                                "required": ["type"],
                                                "properties": {
                                                    "type": {"const": "full_sweep"},
                                                },
                                            },
                                        ]
                                    },
                                    "notes": {"type": "string"},
                                },
                            },
                        },
                        "notes": {"type": "string"},
                    },
                },
            },
        },
    }


def annotation_template(manifest: dict[str, Any], reviewer: str = "UNASSIGNED") -> dict[str, Any]:
    return {
        "schema": "uk_wsr_qc_annotations",
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "manifest_sha256": canonical_json_sha256(manifest),
        "reviewer": reviewer,
        "created_at": _now_utc(),
        "review_policy": {
            "primary_view": "raw_and_companion_fields_blind_to_qc",
            "primary_qc_outputs_visible": False,
            "ci_is_evidence_not_ground_truth": True,
            "current_filter_is_not_ground_truth": True,
            "ambiguous_action": "ignore",
        },
        "items": [],
    }


def validate_annotation_document(
    document: dict[str, Any],
    manifest: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    manifest_cases = {str(item["case_id"]): item for item in manifest.get("files", [])}
    if document.get("schema") != "uk_wsr_qc_annotations":
        errors.append("invalid annotation schema")
    if document.get("benchmark_id") != BENCHMARK_ID:
        errors.append("annotation benchmark id does not match")
    if document.get("manifest_sha256") != canonical_json_sha256(manifest):
        errors.append("annotation manifest hash does not match")

    seen_targets: set[tuple[str, str, str]] = set()
    seen_regions: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(document.get("items", [])):
        prefix = f"items[{index}]"
        case_id = str(item.get("case_id") or "")
        if case_id not in manifest_cases:
            errors.append(f"{prefix}: unknown case_id {case_id!r}")
        target = (case_id, str(item.get("dataset") or ""), str(item.get("review_stage") or ""))
        if target in seen_targets:
            errors.append(f"{prefix}: duplicate case/dataset/review-stage")
        seen_targets.add(target)
        if item.get("review_stage") == "primary" and item.get("qc_outputs_visible") is not False:
            errors.append(f"{prefix}: primary review must be blind to QC outputs")
        if item.get("ci_used_as_ground_truth") is not False:
            errors.append(f"{prefix}: CI cannot be used as ground truth")
        if item.get("current_filter_used_as_ground_truth") is not False:
            errors.append(f"{prefix}: current filter cannot be used as ground truth")
        shape = item.get("shape")
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or any(not isinstance(value, int) or value <= 0 for value in shape)
        ):
            errors.append(f"{prefix}: invalid shape")
            shape = None
        for region_index, region in enumerate(item.get("regions", [])):
            region_prefix = f"{prefix}.regions[{region_index}]"
            label = str(region.get("label") or "")
            definition = LABEL_TAXONOMY.get(label)
            if definition is None:
                errors.append(f"{region_prefix}: unknown label {label!r}")
                continue
            if region.get("action") != definition["action"]:
                errors.append(
                    f"{region_prefix}: action {region.get('action')!r} does not match "
                    f"{label!r} ({definition['action']!r})"
                )
            confidence = region.get("confidence")
            if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
                errors.append(f"{region_prefix}: confidence must be between 0 and 1")
            region_key = (*target, str(region.get("region_id") or ""))
            if region_key in seen_regions:
                errors.append(f"{region_prefix}: duplicate region_id")
            seen_regions.add(region_key)
            if shape is not None:
                errors.extend(_validate_geometry(region.get("geometry"), shape, region_prefix))
    return errors


def benchmark_markdown(manifest: dict[str, Any]) -> str:
    counts = manifest.get("counts", {})
    validation_errors = validate_benchmark_manifest(manifest)
    status = "complete and ready for triage" if not validation_errors else "incomplete"
    total_bytes = sum(int(item.get("size_bytes") or 0) for item in manifest.get("files", []))
    split_rows = "\n".join(
        f"| {split} | {count:,} |"
        for split, count in counts.get("by_split", {}).items()
    )
    return f"""# UK WSR Independent QC Benchmark v1

Status: **{status}**

This manifest defines the real-data evaluation corpus for clutter and noise
removal. It contains {manifest.get('file_count', 0):,} complete PVOL files from
{manifest.get('radar_count', 0)} radars, both pulse types, all elevations, four
seasons, and six UTC time slots. The referenced source volume is approximately
{total_bytes / (1024 ** 3):.2f} GiB.

| Split | PVOL files |
| --- | ---: |
{split_rows}

Every source URL is unique and is excluded from learned-background training.
All elevations from one PVOL remain in one split. The holdout dates must not be
used for threshold selection, feature engineering, model training, or
qualitative tuning.

## Ground-Truth Contract

- Primary review uses raw DBZH and companion fields while remaining blind to
  current QC masks and scores.
- CI may be inspected as one instrument field, but it is never a label.
- Current `qc-v2`, community filters, and learned maps are benchmark
  predictions, never annotation sources.
- `remove` is limited to noise, clutter, interference, isolated speckle, and
  invalid measurements.
- Weather, birds, insects, clear-air structure, mixed echoes, and every other
  coherent measured signal are labelled `retain`.
- Ambiguous gates are `ignore`, not silently converted into removal targets.
- At least 20% of evaluated targets require an independent secondary review,
  followed by adjudication where remove/retain decisions disagree.

## Files

- `manifest.json`: immutable source selections and split assignments.
- `manifest.sha256`: checksum used by annotation files.
- `annotation.schema.json`: machine-readable region annotation contract.
- `annotations.template.json`: empty primary-review document.
- `excluded_from_training.txt`: source URLs that training jobs must reject.

Selection errors: {len(manifest.get('errors', []))}. Validation errors:
{len(validation_errors)}.
"""


def write_benchmark_artifacts(manifest: dict[str, Any], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (output / "manifest.json").write_text(manifest_text, encoding="utf-8")
    digest = canonical_json_sha256(manifest)
    (output / "manifest.sha256").write_text(f"{digest}  manifest.json\n", encoding="utf-8")
    (output / "annotation.schema.json").write_text(
        json.dumps(annotation_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "annotations.template.json").write_text(
        json.dumps(annotation_template(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    urls = sorted(str(item["object_url"]) for item in manifest.get("files", []))
    (output / "excluded_from_training.txt").write_text(
        "".join(f"{url}\n" for url in urls),
        encoding="utf-8",
    )
    (output / "README.md").write_text(benchmark_markdown(manifest), encoding="utf-8")


def benchmark_local_path(root: str | Path, item: dict[str, Any]) -> Path:
    return (
        Path(root)
        / str(item["split"])
        / str(item["radar"])
        / str(item["date"])
        / str(item["pulse"])
        / str(item["filename"])
    )


def canonical_json_sha256(value: Any) -> str:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return sha256(payload).hexdigest()


def _expected_anchor_counts(
    anchors: Iterable[dict[str, Any]],
    field: str,
    radar_count: int,
    pulse_count: int,
) -> dict[str, int]:
    anchor_counts = Counter(str(anchor[field]) for anchor in anchors)
    return {
        key: count * radar_count * pulse_count
        for key, count in sorted(anchor_counts.items())
    }


def _select_complete_day(
    days: Iterable[dict[str, Any]],
    *,
    anchor: BenchmarkAnchor,
    pulses: tuple[str, ...],
    radar: str,
    fetch_json: Callable[[str], dict[str, Any]],
    catalog_cache: dict[str, dict[str, Any]],
    public_base: str,
    used_urls: dict[tuple[str, str], set[str]],
    max_day_offset: int,
    max_time_offset_minutes: int,
    minimum_day_coverage_fraction: float,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]] | None:
    day_list = list(days)
    maximum_pulse_counts = {
        pulse: max(
            (
                int(day.get("pulse_counts", {}).get(pulse) or 0)
                for day in day_list
            ),
            default=0,
        )
        for pulse in pulses
    }
    candidates = sorted(
        (
            day
            for day in day_list
            if day.get("date")
            and _date_distance(str(day["date"]), anchor.target_date) <= max_day_offset
            and _day_has_sufficient_coverage(
                day,
                pulses=pulses,
                maximum_pulse_counts=maximum_pulse_counts,
                minimum_fraction=minimum_day_coverage_fraction,
            )
        ),
        key=lambda day: (
            _date_distance(str(day["date"]), anchor.target_date),
            str(day["date"]),
        ),
    )
    for day in candidates:
        catalog_key = str(day.get("catalog_key") or "")
        if not catalog_key:
            continue
        catalog_url = _public_url(public_base, catalog_key)
        try:
            if catalog_url not in catalog_cache:
                catalog_cache[catalog_url] = fetch_json(catalog_url)
            catalog = catalog_cache[catalog_url]
        except Exception:  # noqa: BLE001 - try the next nearby date.
            continue
        selected: dict[str, dict[str, Any]] = {}
        for pulse in pulses:
            source = _nearest_file(
                catalog.get("files", []),
                pulse=pulse,
                target_time=anchor.target_time,
            )
            if source is None:
                break
            distance = _time_distance(str(source.get("time") or ""), anchor.target_time)
            object_url = str(
                source.get("object_url")
                or _public_url(public_base, str(source.get("object_key") or ""))
            )
            if (
                distance > max_time_offset_minutes
                or not object_url
                or object_url in used_urls[(radar, pulse)]
            ):
                break
            selected[pulse] = source
        if len(selected) == len(pulses):
            return day, selected
    return None


def _day_has_sufficient_coverage(
    day: dict[str, Any],
    *,
    pulses: tuple[str, ...],
    maximum_pulse_counts: dict[str, int],
    minimum_fraction: float,
) -> bool:
    pulse_counts = day.get("pulse_counts")
    if not isinstance(pulse_counts, dict):
        return True
    for pulse in pulses:
        maximum = int(maximum_pulse_counts.get(pulse) or 0)
        count = int(pulse_counts.get(pulse) or 0)
        if maximum > 0 and count < maximum * minimum_fraction:
            return False
    return True


def _nearest_file(
    files: Iterable[dict[str, Any]],
    *,
    pulse: str,
    target_time: str,
) -> dict[str, Any] | None:
    candidates = [
        entry
        for entry in files
        if str(entry.get("pulse") or "").lower() == pulse.lower()
        and str(entry.get("time") or "").zfill(4).isdigit()
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda entry: (
            _time_distance(str(entry.get("time") or ""), target_time),
            str(entry.get("time") or ""),
        ),
    )


def _validate_geometry(geometry: Any, shape: list[int], prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(geometry, dict):
        return [f"{prefix}: geometry must be an object"]
    kind = geometry.get("type")
    size = shape[0] * shape[1]
    if kind == "polar_gate_polygon":
        vertices = geometry.get("vertices")
        if not isinstance(vertices, list) or len(vertices) < 3:
            errors.append(f"{prefix}: polygon requires at least three vertices")
        else:
            for vertex in vertices:
                if (
                    not isinstance(vertex, list)
                    or len(vertex) != 2
                    or not all(isinstance(value, (int, float)) for value in vertex)
                ):
                    errors.append(f"{prefix}: invalid polygon vertex")
                    continue
                ray, gate = float(vertex[0]), float(vertex[1])
                if not 0 <= ray < shape[0] or not 0 <= gate < shape[1]:
                    errors.append(f"{prefix}: polygon vertex outside sweep shape")
    elif kind == "row_major_rle":
        for run in geometry.get("runs", []):
            if (
                not isinstance(run, list)
                or len(run) != 2
                or not all(isinstance(value, int) for value in run)
                or run[0] < 0
                or run[1] <= 0
                or run[0] + run[1] > size
            ):
                errors.append(f"{prefix}: invalid row-major RLE run")
    elif kind != "full_sweep":
        errors.append(f"{prefix}: unsupported geometry type {kind!r}")
    return errors


def _coverage_key(radar_entry: dict[str, Any], year: str) -> str | None:
    suffix = f"/{year}/coverage.json"
    return next(
        (
            str(value)
            for value in radar_entry.get("coverage_keys", [])
            if str(value).endswith(suffix)
        ),
        None,
    )


def _selection_error(
    radar: str,
    anchor: BenchmarkAnchor,
    reason: str,
) -> dict[str, Any]:
    return {
        "radar": radar,
        "anchor_id": anchor.anchor_id,
        "target_date": anchor.target_date,
        "target_time": anchor.target_time,
        "error": reason,
    }


def _case_id(radar: str, date: str, time: str, pulse: str, filename: str) -> str:
    digest = sha256(f"{radar}|{date}|{time}|{pulse}|{filename}".encode("utf-8")).hexdigest()[:16]
    return f"{radar}-{date}-{time}-{pulse}-{digest}"


def _date_distance(first: str, second: str) -> int:
    first_date = datetime.strptime(first, "%Y%m%d").date()
    second_date = datetime.strptime(second, "%Y%m%d").date()
    return abs((first_date - second_date).days)


def _time_distance(first: str, second: str) -> int:
    first_minutes = _minutes(first)
    second_minutes = _minutes(second)
    direct = abs(first_minutes - second_minutes)
    return min(direct, 24 * 60 - direct)


def _minutes(value: str) -> int:
    text = str(value).zfill(4)
    if len(text) != 4 or not text.isdigit():
        raise ValueError(f"invalid HHMM time {value!r}")
    hour = int(text[:2])
    minute = int(text[2:])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"invalid HHMM time {value!r}")
    return hour * 60 + minute


def _public_url(base: str, key: str) -> str:
    if key.startswith(("http://", "https://")):
        return key
    return f"{base.rstrip('/')}/{key.lstrip('/')}"


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
