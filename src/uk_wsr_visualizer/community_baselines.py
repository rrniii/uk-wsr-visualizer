"""Pinned community QC baselines evaluated without treating them as truth."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .background_model import BackgroundModel
from .background_training_pipeline import file_sha256
from .background_validation_pipeline import hash_validation_arrays
from .dependencies import require_numpy
from .qc import normalized_quantity
from .qc_evidence import EvidenceFlag

COMMUNITY_BASELINE_SCHEMA = "uk_wsr_community_qc_baselines"
COMMUNITY_BASELINE_SCHEMA_VERSION = 1
COMMUNITY_BASELINE_METHODS = (
    "pyart_texture",
    "pyart_texture_despeckle",
    "wradlib_gabella",
    "wradlib_fuzzy_p20",
    "wradlib_fuzzy_p50",
    "wradlib_fuzzy_p80",
)
DEFAULT_COMMUNITY_CASE_COUNT = 102
_DBZH_THRESHOLDS = (0.0, 5.0, 10.0, 15.0, 20.0, 30.0)


@dataclass(frozen=True)
class CommunityBaselineResult:
    """Exact community masks and method provenance for one sweep."""

    arrays: dict[str, Any]
    method_status: dict[str, dict[str, Any]]
    versions: dict[str, str]


def select_community_baseline_records(
    records: Iterable[dict[str, Any]],
    *,
    case_count: int = DEFAULT_COMMUNITY_CASE_COUNT,
) -> tuple[dict[str, Any], ...]:
    """Select deterministic PPI controls and high-risk cases across the network."""

    rows = [
        row
        for row in records
        if str(row.get("geometry_class")) == "ppi"
    ]
    wanted = max(1, min(int(case_count), len(rows)))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(
            (str(row["radar"]), str(row["pulse"])),
            [],
        ).append(row)
    wanted = max(wanted, min(len(groups), len(rows)))

    selected: dict[str, dict[str, Any]] = {}
    for key in sorted(groups):
        group = groups[key]
        rankings = (
            (
                lambda row: float(
                    row["delta"]["learned_increment_fraction"]
                ),
                True,
            ),
            (
                lambda row: float(row["learned"]["removed_fraction"]),
                True,
            ),
            (
                lambda row: float(row["learned"]["removed_fraction"]),
                False,
            ),
        )
        for rank, reverse in rankings:
            ordered = sorted(
                group,
                key=lambda row: (
                    rank(row),
                    str(row["job_id"]),
                ),
                reverse=reverse,
            )
            selected[str(ordered[0]["job_id"])] = ordered[0]

    fill = sorted(
        rows,
        key=lambda row: (
            float(
                row["delta"]["learned_increment_dbzh"][
                    "linear_reflectivity_fraction"
                ]
            ),
            float(row["delta"]["learned_increment_fraction"]),
            float(row["learned"]["removed_fraction"]),
            str(row["job_id"]),
        ),
        reverse=True,
    )
    for row in fill:
        if len(selected) >= wanted:
            break
        selected.setdefault(str(row["job_id"]), row)
    if len(selected) > wanted:
        must_keep: list[dict[str, Any]] = []
        for key in sorted(groups):
            group_selected = [
                selected[str(row["job_id"])]
                for row in groups[key]
                if str(row["job_id"]) in selected
            ]
            if group_selected:
                must_keep.append(
                    max(
                        group_selected,
                        key=lambda row: float(
                            row["delta"]["learned_increment_fraction"]
                        ),
                    )
                )
        trimmed = {
            str(row["job_id"]): row for row in must_keep
        }
        for row in fill:
            if len(trimmed) >= wanted:
                break
            job_id = str(row["job_id"])
            if job_id in selected:
                trimmed.setdefault(job_id, row)
        selected = trimmed
    return tuple(
        sorted(
            selected.values(),
            key=lambda row: (
                str(row["radar"]),
                str(row["pulse"]),
                float(row["elevation_deg"]),
                str(row["source"]["date"]),
                str(row["source"]["time"]),
                str(row["job_id"]),
            ),
        )
    )


def run_community_baselines(
    dbzh: Any,
    companions: dict[str, Any],
    model: BackgroundModel,
    *,
    elevation_deg: float,
) -> CommunityBaselineResult:
    """Run pinned Py-ART and wradlib algorithms on one exact gate grid."""

    np = require_numpy()
    import pyart
    import wradlib

    values = np.asarray(dbzh, dtype="float32")
    if tuple(model.shape) != tuple(values.shape):
        raise ValueError("community baseline model shape mismatch")
    fields = {
        normalized_quantity(name): np.asarray(array, dtype="float32")
        for name, array in companions.items()
        if np.asarray(array).shape == values.shape
    }
    arrays: dict[str, Any] = {}
    status: dict[str, dict[str, Any]] = {}

    pyart_masks, pyart_status = _run_pyart(
        pyart,
        values,
        fields,
        elevation_deg=elevation_deg,
    )
    arrays.update(pyart_masks)
    status.update(pyart_status)

    wradlib_arrays, wradlib_status = _run_wradlib(
        wradlib,
        values,
        fields,
        model,
    )
    arrays.update(wradlib_arrays)
    status.update(wradlib_status)
    return CommunityBaselineResult(
        arrays=arrays,
        method_status=status,
        versions={
            "arm_pyart": str(pyart.__version__),
            "wradlib": str(wradlib.__version__),
            "numpy": str(np.__version__),
        },
    )


def community_method_metrics(
    dbzh: Any,
    method_mask: Any,
    *,
    candidate_remove_mask: Any,
    candidate_increment_mask: Any,
    candidate_protected_mask: Any,
    candidate_evidence_mask: Any,
) -> dict[str, Any]:
    """Describe a method footprint without inferring echo class."""

    np = require_numpy()
    values = np.asarray(dbzh, dtype="float32")
    finite = np.isfinite(values)
    remove = np.asarray(method_mask, dtype=bool) & finite
    candidate = np.asarray(candidate_remove_mask, dtype=bool) & finite
    increment = np.asarray(candidate_increment_mask, dtype=bool) & finite
    protected = np.asarray(candidate_protected_mask, dtype=bool) & finite
    evidence = np.asarray(candidate_evidence_mask, dtype="uint32")
    upper = (
        evidence & int(EvidenceFlag.UPPER_ELEVATION_SUPPORT)
    ) != 0
    selected = values[remove]
    linear_total = float(
        np.power(
            10.0,
            np.clip(values[finite], -50.0, 100.0) / 10.0,
        ).sum(dtype="float64")
    )
    linear_removed = float(
        np.power(
            10.0,
            np.clip(selected, -50.0, 100.0) / 10.0,
        ).sum(dtype="float64")
    )
    union = remove | candidate
    return {
        "finite_count": int(finite.sum()),
        "removed_count": int(remove.sum()),
        "removed_fraction": _fraction(remove.sum(), finite.sum()),
        "removed_linear_reflectivity_fraction": _fraction(
            linear_removed,
            linear_total,
        ),
        "removed_at_or_above_dbzh": {
            f"{threshold:g}": int((selected >= threshold).sum())
            for threshold in _DBZH_THRESHOLDS
        },
        "maximum_removed_dbzh": (
            float(selected.max()) if selected.size else None
        ),
        "candidate_overlap_count": int((remove & candidate).sum()),
        "candidate_jaccard": _fraction(
            (remove & candidate).sum(),
            union.sum(),
        ),
        "candidate_increment_overlap_count": int(
            (remove & increment).sum()
        ),
        "candidate_protected_count": int((remove & protected).sum()),
        "candidate_upper_supported_count": int((remove & upper).sum()),
    }


def write_community_baseline_artifact(
    result: CommunityBaselineResult,
    output_root: str | Path,
    *,
    validation_record: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    """Persist exact community masks and probabilities atomically."""

    np = require_numpy()
    root = Path(output_root)
    artifact_dir = root / str(validation_record["target_id"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_id = str(validation_record["source"]["source_id"])
    npz_path = artifact_dir / f"{source_id}.npz"
    sidecar_path = artifact_dir / f"{source_id}.npz.json"
    temporary = npz_path.with_suffix(".npz.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            **{
                name: np.asarray(values)
                for name, values in sorted(result.arrays.items())
            },
        )
    temporary.replace(npz_path)
    sidecar = {
        "schema": "uk_wsr_community_qc_baseline_artifact",
        "schema_version": 1,
        "job_id": validation_record["job_id"],
        "target_id": validation_record["target_id"],
        "source": validation_record["source"],
        "model_array_hash": validation_record["model"]["array_hash"],
        "validation_configuration_sha256": validation_record[
            "configuration_sha256"
        ],
        "versions": result.versions,
        "method_status": result.method_status,
        "array_hash": hash_validation_arrays(result.arrays),
        "artifact_sha256": file_sha256(npz_path),
        "arrays": {
            name: {
                "dtype": str(np.asarray(values).dtype),
                "shape": list(np.asarray(values).shape),
            }
            for name, values in sorted(result.arrays.items())
        },
        "npz_path": npz_path.name,
        "promotion_eligible": False,
    }
    _write_json_atomic(sidecar_path, sidecar)
    return npz_path, sidecar_path, sidecar


def summarise_community_baselines(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate method footprints without making accuracy claims."""

    rows = list(records)
    methods: dict[str, dict[str, Any]] = {}
    for method in COMMUNITY_BASELINE_METHODS:
        available = [
            row
            for row in rows
            if row["methods"].get(method, {}).get("status") == "scored"
        ]
        metrics = [
            row["methods"][method]["metrics"] for row in available
        ]
        finite = sum(int(item["finite_count"]) for item in metrics)
        removed = sum(int(item["removed_count"]) for item in metrics)
        methods[method] = {
            "scored_case_count": len(available),
            "finite_gate_count": finite,
            "removed_count": removed,
            "removed_fraction": _fraction(removed, finite),
            "candidate_protected_count": sum(
                int(item["candidate_protected_count"])
                for item in metrics
            ),
            "candidate_upper_supported_count": sum(
                int(item["candidate_upper_supported_count"])
                for item in metrics
            ),
            "removed_at_or_above_dbzh": {
                f"{threshold:g}": sum(
                    int(
                        item["removed_at_or_above_dbzh"][
                            f"{threshold:g}"
                        ]
                    )
                    for item in metrics
                )
                for threshold in _DBZH_THRESHOLDS
            },
        }
    return {
        "case_count": len(rows),
        "radar_count": len({row["radar"] for row in rows}),
        "pulse_counts": dict(
            sorted(
                (
                    pulse,
                    sum(row["pulse"] == pulse for row in rows),
                )
                for pulse in ("lp", "sp")
            )
        ),
        "methods": methods,
        "interpretation": (
            "descriptive method footprints only; disagreement is not error "
            "without independent echo-class labels"
        ),
        "promotion_eligible": False,
    }


def write_community_baseline_report(
    path: str | Path,
    *,
    validation_results: str | Path,
    validation_results_sha256: str,
    selection: dict[str, Any],
    versions: dict[str, str],
    records: list[dict[str, Any]],
    errors: list[dict[str, str]],
    artifact_root: str | Path,
) -> Path:
    """Write the community comparison report atomically."""

    report = {
        "schema": COMMUNITY_BASELINE_SCHEMA,
        "schema_version": COMMUNITY_BASELINE_SCHEMA_VERSION,
        "validation_results": str(validation_results),
        "validation_results_sha256": validation_results_sha256,
        "selection": selection,
        "versions": versions,
        "artifact_root": str(artifact_root),
        "expected_case_count": int(selection["selected_case_count"]),
        "scored_case_count": len(records),
        "error_count": len(errors),
        "complete": (
            not errors
            and len(records) == int(selection["selected_case_count"])
        ),
        "method_contract": {
            "pyart_texture": (
                "moment_and_texture_based_gate_filter defaults"
            ),
            "pyart_texture_despeckle": (
                "Py-ART texture filter then despeckle_field threshold=-20 "
                "dBZ and size=10"
            ),
            "wradlib_gabella": (
                "filter_gabella wsize=5 thrsnorain=0 tr1=6 n_p=8 tr2=1.3"
            ),
            "wradlib_fuzzy": (
                "classify_echo_fuzzy defaults; conditioned low-CI/static "
                "learned map supplied as the mandatory clutter map; "
                "meteorological probability thresholds 0.2, 0.5, and 0.8"
            ),
            "missing_evidence": (
                "method-native behavior is recorded; fuzzy all-dual-pol "
                "missing gates fail open"
            ),
        },
        "summary": summarise_community_baselines(records),
        "records": records,
        "errors": errors,
        "promotion_eligible_model_count": 0,
    }
    destination = Path(path)
    _write_json_atomic(destination, report)
    return destination


def _run_pyart(
    pyart: Any,
    dbzh: Any,
    fields: dict[str, Any],
    *,
    elevation_deg: float,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    np = require_numpy()
    radar = pyart.testing.make_empty_ppi_radar(
        dbzh.shape[1],
        dbzh.shape[0],
        1,
    )
    radar.fixed_angle["data"][:] = float(elevation_deg)
    radar.elevation["data"][:] = float(elevation_deg)
    field_mapping = {
        "DBZH": dbzh,
        "ZDR": fields.get("ZDR"),
        "RHOHV": fields.get("RHOHV"),
        "PHIDP": fields.get("PHIDP"),
    }
    available = []
    for name, values in field_mapping.items():
        if values is None:
            continue
        radar.add_field(
            name,
            {"data": np.ma.masked_invalid(values)},
        )
        available.append(name)
    gatefilter = pyart.filters.moment_and_texture_based_gate_filter(
        radar,
        refl_field="DBZH",
        zdr_field="ZDR",
        rhv_field="RHOHV",
        phi_field="PHIDP",
    )
    texture = np.asarray(gatefilter.gate_excluded, dtype=bool)
    pyart.correct.despeckle_field(
        radar,
        "DBZH",
        threshold=-20.0,
        size=10,
        gatefilter=gatefilter,
    )
    despeckled = np.asarray(gatefilter.gate_excluded, dtype=bool)
    finite = np.isfinite(dbzh)
    return (
        {
            "pyart_texture": (texture & finite).astype("uint8"),
            "pyart_texture_despeckle": (
                despeckled & finite
            ).astype("uint8"),
        },
        {
            name: {
                "status": "scored",
                "available_fields": sorted(available),
                "native_missing_field_behavior": (
                    "criterion omitted when field absent; invalid values in "
                    "available fields excluded"
                ),
            }
            for name in ("pyart_texture", "pyart_texture_despeckle")
        },
    )


def _run_wradlib(
    wradlib: Any,
    dbzh: Any,
    fields: dict[str, Any],
    model: BackgroundModel,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    np = require_numpy()
    finite = np.isfinite(dbzh)
    gabella = wradlib.classify.filter_gabella(
        np.asarray(dbzh, dtype="float32"),
        wsize=5,
        thrsnorain=0.0,
        tr1=6.0,
        n_p=8,
        tr2=1.3,
        rm_nans=True,
    )
    arrays: dict[str, Any] = {
        "wradlib_gabella": (
            np.asarray(gabella, dtype=bool) & finite
        ).astype("uint8")
    }
    status: dict[str, dict[str, Any]] = {
        "wradlib_gabella": {
            "status": "scored",
            "available_fields": ["DBZH"],
        }
    }
    required = {
        "zdr": fields.get("ZDR"),
        "rho": fields.get("RHOHV"),
        "phi": fields.get("PHIDP"),
        "dop": fields.get("VRADH"),
    }
    missing = sorted(name for name, values in required.items() if values is None)
    if missing:
        for threshold in (20, 50, 80):
            name = f"wradlib_fuzzy_p{threshold:02d}"
            arrays[name] = np.zeros(dbzh.shape, dtype="uint8")
            status[name] = {
                "status": "unavailable",
                "missing_fields": missing,
                "policy": "fail_open",
            }
        arrays["wradlib_meteorological_probability"] = np.full(
            dbzh.shape,
            np.nan,
            dtype="float32",
        )
        arrays["wradlib_missing_dualpol_mask"] = np.ones(
            dbzh.shape,
            dtype="uint8",
        )
        return arrays, status

    model_arrays = model.arrays
    support = np.minimum(
        np.asarray(
            model_arrays["low_ci_sample_count"],
            dtype="float32",
        ),
        np.asarray(
            model_arrays["low_ci_vrad_sample_count"],
            dtype="float32",
        ),
    )
    clutter_map = (
        (
            np.asarray(
                model_arrays["low_ci_persistent_echo_frequency"],
                dtype="float32",
            )
            >= 0.85
        )
        & (
            np.asarray(
                model_arrays["low_ci_near_zero_vrad_frequency"],
                dtype="float32",
            )
            >= 0.80
        )
        & (support >= 12)
    ).astype("float32")
    fuzzy_inputs = {
        name: np.asarray(values, dtype="float32").copy()
        for name, values in required.items()
    }
    fuzzy_inputs["map"] = clutter_map
    probability, all_dualpol_missing = (
        wradlib.classify.classify_echo_fuzzy(fuzzy_inputs)
    )
    probability = np.asarray(probability, dtype="float32")
    all_dualpol_missing = np.asarray(all_dualpol_missing, dtype=bool)
    arrays["wradlib_meteorological_probability"] = probability
    arrays["wradlib_missing_dualpol_mask"] = (
        all_dualpol_missing.astype("uint8")
    )
    for threshold in (0.20, 0.50, 0.80):
        name = f"wradlib_fuzzy_p{int(threshold * 100):02d}"
        arrays[name] = (
            finite
            & np.isfinite(probability)
            & ~all_dualpol_missing
            & (probability < threshold)
        ).astype("uint8")
        status[name] = {
            "status": "scored",
            "available_fields": [
                "ZDR",
                "RHOHV",
                "PHIDP",
                "VRADH",
                "conditioned_static_clutter_map",
            ],
            "meteorological_probability_threshold": threshold,
            "all_dualpol_missing_policy": "fail_open",
            "clutter_map_gate_count": int(clutter_map.sum()),
        }
    return arrays, status


def _fraction(numerator: Any, denominator: Any) -> float:
    denominator_value = float(denominator)
    return (
        float(numerator) / denominator_value
        if denominator_value
        else 0.0
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def hash_community_contract(payload: dict[str, Any]) -> str:
    """Return a deterministic hash for a comparison contract."""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
