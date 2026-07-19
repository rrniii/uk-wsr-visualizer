"""Literature-anchored fuzzy prelabels for manual UK WSR QC review."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .dependencies import require_numpy
from .qc_benchmark import LABEL_TAXONOMY


FUZZY_PRELABEL_ID = "uk-wsr-review-fuzzy-v1"

# Non-meteorological memberships and weights match wradlib's
# classify_echo_fuzzy defaults. Infinite shoulders are represented by None.
WRADLIB_MEMBERSHIPS = {
    "zdr_texture": (0.7, 1.0, None, None),
    "rhohv_texture": (0.1, 0.15, None, None),
    "phidp_texture": (15.0, 20.0, None, None),
    "velocity": (-0.2, -0.1, 0.1, 0.2),
    "rhohv": (None, None, 0.95, 0.98),
}
WRADLIB_WEIGHTS = {
    "zdr_texture": 0.4,
    "rhohv_texture": 0.4,
    "phidp_texture": 0.1,
    "velocity": 0.1,
    "rhohv": 0.4,
}

# Relevant C-band simultaneous-H/V memberships from LROSE RadxPid's
# pid_thresholds.cband.shv. These are used conservatively because temperature,
# KDP and the full LROSE PID input set are not always present in UKMO PVOLs.
LROSE_C_BAND = {
    "ground_clutter_zh": (5.0, 10.0, None, None),
    "ground_clutter_zdr": (None, None, 5.0, 10.0),
    "ground_clutter_zdr_texture_min": 2.0,
    "flying_insects_zh": (-7.0, -5.0, 30.0, 35.0),
    "flying_insects_zdr_min": 2.0,
}

FIELD_ALIASES = {
    "velocity": ("VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH"),
    "sqi": ("SQIH", "SQI", "QIND"),
    "rhohv": ("RHOHV", "RHO", "CC"),
    "zdr": ("ZDR", "ZDRH", "ZDRV"),
    "phidp": ("PHIDP", "UPHIDP", "PHI"),
}


def fuzzy_prelabel(
    dbzh: Any,
    companions: Mapping[str, Any],
) -> dict[str, Any]:
    """Return conservative gate regions proposed for human confirmation.

    This is an annotation assistant, not a production clutter mask. Missing
    variables are omitted and weights are renormalised over available evidence.
    """

    np = require_numpy()
    zh = np.asarray(dbzh, dtype="float32")
    if zh.ndim != 2:
        raise ValueError("fuzzy prelabel requires a two-dimensional DBZH field")
    available = {
        key: _field(companions, aliases, zh.shape)
        for key, aliases in FIELD_ALIASES.items()
    }
    textures = {
        key: _local_texture(value, angular=key == "phidp")
        for key, value in available.items()
        if key in {"zdr", "rhohv", "phidp"} and value is not None
    }

    memberships: dict[str, Any] = {}
    if "zdr" in textures:
        memberships["zdr_texture"] = _trapezoid(
            textures["zdr"], WRADLIB_MEMBERSHIPS["zdr_texture"]
        )
    if "rhohv" in textures:
        memberships["rhohv_texture"] = _trapezoid(
            textures["rhohv"], WRADLIB_MEMBERSHIPS["rhohv_texture"]
        )
    if "phidp" in textures:
        memberships["phidp_texture"] = _trapezoid(
            textures["phidp"], WRADLIB_MEMBERSHIPS["phidp_texture"]
        )
    if available["velocity"] is not None:
        memberships["velocity"] = _trapezoid(
            available["velocity"], WRADLIB_MEMBERSHIPS["velocity"]
        )
    if available["rhohv"] is not None:
        memberships["rhohv"] = _trapezoid(
            available["rhohv"], WRADLIB_MEMBERSHIPS["rhohv"]
        )
    nonmet = _weighted_membership(memberships, WRADLIB_WEIGHTS, zh.shape)

    finite = np.isfinite(zh)
    support = _neighbour_support(finite)
    velocity_zero = memberships.get(
        "velocity", np.full(zh.shape, np.nan, dtype="float32")
    )
    zdr_texture = textures.get(
        "zdr", np.full(zh.shape, np.nan, dtype="float32")
    )

    ground_parts = [
        (nonmet, 0.45),
        (
            _trapezoid(zh, LROSE_C_BAND["ground_clutter_zh"]),
            0.20,
        ),
        (
            _trapezoid(
                available["zdr"], LROSE_C_BAND["ground_clutter_zdr"]
            )
            if available["zdr"] is not None
            else None,
            0.10,
        ),
        (
            _ramp_up(
                zdr_texture,
                LROSE_C_BAND["ground_clutter_zdr_texture_min"] - 0.5,
                LROSE_C_BAND["ground_clutter_zdr_texture_min"] + 0.5,
            )
            if available["zdr"] is not None
            else None,
            0.15,
        ),
        (
            velocity_zero if available["velocity"] is not None else None,
            0.10,
        ),
    ]
    ground = _weighted_parts(ground_parts, zh.shape)

    low_zh = _ramp_down(zh, -5.0, 8.0)
    low_sqi = (
        _ramp_down(available["sqi"], 0.20, 0.55)
        if available["sqi"] is not None
        else None
    )
    low_rho = (
        _ramp_down(available["rhohv"], 0.70, 0.95)
        if available["rhohv"] is not None
        else None
    )
    isolated = np.clip(1.0 - support / 5.0, 0.0, 1.0)
    noise = _weighted_parts(
        [
            (low_zh, 0.30),
            (low_sqi, 0.30),
            (low_rho, 0.20),
            (isolated, 0.20),
        ],
        zh.shape,
    )

    insect_zh = _trapezoid(
        zh, LROSE_C_BAND["flying_insects_zh"]
    )
    insect_zdr = (
        _ramp_up(
            available["zdr"],
            LROSE_C_BAND["flying_insects_zdr_min"],
            LROSE_C_BAND["flying_insects_zdr_min"] + 2.0,
        )
        if available["zdr"] is not None
        else None
    )
    biological = _weighted_parts(
        [
            (insect_zh, 0.35),
            (insect_zdr, 0.35),
            (np.clip(support / 6.0, 0.0, 1.0), 0.15),
            (
                _ramp_down(available["rhohv"], 0.75, 0.97)
                if available["rhohv"] is not None
                else None,
                0.15,
            ),
        ],
        zh.shape,
    )

    meteorological = 1.0 - nonmet
    precipitation = _weighted_parts(
        [
            (meteorological, 0.45),
            (
                _ramp_up(available["rhohv"], 0.90, 0.98)
                if available["rhohv"] is not None
                else None,
                0.30,
            ),
            (np.clip(support / 7.0, 0.0, 1.0), 0.15),
            (
                1.0 - np.clip(zdr_texture / 2.0, 0.0, 1.0)
                if available["zdr"] is not None
                else None,
                0.10,
            ),
        ],
        zh.shape,
    )

    scores = {
        "receiver_noise": noise,
        "static_ground_clutter": ground,
        "biological_insects": biological,
        "precipitation": precipitation,
    }
    labels = list(scores)
    score_stack = np.stack([scores[label] for label in labels])
    score_stack[:, ~finite] = -1.0
    order = np.argsort(score_stack, axis=0)
    best_index = order[-1]
    best = np.take_along_axis(
        score_stack, best_index[None, ...], axis=0
    )[0]
    second = np.take_along_axis(
        score_stack, order[-2][None, ...], axis=0
    )[0]
    confident = finite & (best >= 0.68) & ((best - second) >= 0.12)

    classified = np.full(zh.shape, "", dtype="<U24")
    for index, label in enumerate(labels):
        classified[confident & (best_index == index)] = label

    regions = []
    class_counts: dict[str, int] = {}
    for label in labels:
        mask = classified == label
        count = int(np.count_nonzero(mask))
        class_counts[label] = count
        if not count:
            continue
        regions.append(
            {
                "region_id": f"fuzzy-{label}",
                "label": label,
                "action": LABEL_TAXONOMY[label]["action"],
                "confidence": round(float(np.nanmedian(scores[label][mask])), 3),
                "geometry": {
                    "type": "row_major_rle",
                    "runs": mask_to_row_major_rle(mask),
                },
                "notes": f"Proposed by {FUZZY_PRELABEL_ID}; human confirmation required.",
                "source": "fuzzy_prelabel",
            }
        )

    valid_count = int(np.count_nonzero(finite))
    classified_count = sum(class_counts.values())
    parameter_payload = {
        "id": FUZZY_PRELABEL_ID,
        "wradlib_memberships": WRADLIB_MEMBERSHIPS,
        "wradlib_weights": WRADLIB_WEIGHTS,
        "lrose_c_band": LROSE_C_BAND,
        "confidence_min": 0.68,
        "margin_min": 0.12,
    }
    return {
        "schema": "uk_wsr_qc_fuzzy_prelabel",
        "schema_version": 1,
        "model_id": FUZZY_PRELABEL_ID,
        "parameters_sha256": hashlib.sha256(
            json.dumps(
                parameter_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "status": "proposal_only",
        "human_confirmation_required": True,
        "available_fields": [
            key for key, value in available.items() if value is not None
        ],
        "missing_fields": [
            key for key, value in available.items() if value is None
        ],
        "summary": {
            "valid_gate_count": valid_count,
            "classified_gate_count": classified_count,
            "unclassified_gate_count": max(0, valid_count - classified_count),
            "classified_percent": round(
                100.0 * classified_count / max(valid_count, 1), 2
            ),
            "class_counts": class_counts,
        },
        "regions": regions,
        "provenance": {
            "wradlib": "classify_echo_fuzzy default memberships and weights",
            "lrose": "RadxPid pid_thresholds.cband.shv",
            "texture_window": "3x3 finite-gate standard deviation",
            "limitations": [
                "No class is used as ground truth.",
                "Missing evidence is omitted and remaining weights renormalised.",
                "LROSE temperature and KDP evidence are not inferred when absent.",
                "Uncertain and close-score gates are deliberately left unlabelled.",
            ],
        },
    }


def mask_to_row_major_rle(mask: Any) -> list[list[int]]:
    """Encode a boolean polar gate mask as compact row-major runs."""

    np = require_numpy()
    flat = np.asarray(mask, dtype=bool).reshape(-1)
    indices = np.flatnonzero(flat)
    if not len(indices):
        return []
    starts = indices[np.r_[True, np.diff(indices) > 1]]
    ends = indices[np.r_[np.diff(indices) > 1, True]] + 1
    return [
        [int(start), int(end - start)]
        for start, end in zip(starts, ends, strict=True)
    ]


def _field(
    companions: Mapping[str, Any],
    aliases: tuple[str, ...],
    shape: tuple[int, ...],
):
    np = require_numpy()
    normalized = {str(key).upper(): value for key, value in companions.items()}
    for alias in aliases:
        value = normalized.get(alias)
        if value is None:
            continue
        array = np.asarray(value, dtype="float32")
        if array.shape == shape:
            return array
    return None


def _local_texture(values: Any, *, angular: bool = False):
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    if angular:
        radians = np.deg2rad(array)
        sin_texture = _local_std(np.sin(radians))
        cos_texture = _local_std(np.cos(radians))
        return np.rad2deg(np.sqrt(sin_texture**2 + cos_texture**2))
    return _local_std(array)


def _local_std(array: Any):
    np = require_numpy()
    values = np.asarray(array, dtype="float32")
    azimuth_padded = np.concatenate(
        [values[-1:, :], values, values[:1, :]], axis=0
    )
    padded = np.pad(
        azimuth_padded,
        ((0, 0), (1, 1)),
        mode="constant",
        constant_values=np.nan,
    )
    finite = np.isfinite(padded)
    total = np.zeros(values.shape, dtype="float32")
    total_sq = np.zeros(values.shape, dtype="float32")
    count = np.zeros(values.shape, dtype="float32")
    for row in range(3):
        for column in range(3):
            window = padded[
                row : row + values.shape[0],
                column : column + values.shape[1],
            ]
            valid = finite[
                row : row + values.shape[0],
                column : column + values.shape[1],
            ]
            total += np.where(valid, window, 0.0)
            total_sq += np.where(valid, window * window, 0.0)
            count += valid
    mean = total / np.maximum(count, 1.0)
    variance = total_sq / np.maximum(count, 1.0) - mean * mean
    return np.where(count >= 3, np.sqrt(np.maximum(variance, 0.0)), np.nan)


def _neighbour_support(valid: Any):
    np = require_numpy()
    array = np.asarray(valid, dtype="float32")
    azimuth_padded = np.concatenate(
        [array[-1:, :], array, array[:1, :]], axis=0
    )
    padded = np.pad(
        azimuth_padded,
        ((0, 0), (1, 1)),
        mode="constant",
        constant_values=0.0,
    )
    count = np.zeros(array.shape, dtype="float32")
    for row in range(3):
        for column in range(3):
            count += padded[
                row : row + array.shape[0],
                column : column + array.shape[1],
            ]
    return count


def _trapezoid(values: Any, points: tuple[Any, Any, Any, Any]):
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    a, b, c, d = points
    if a is None and b is None:
        return _ramp_down(array, float(c), float(d))
    if c is None and d is None:
        return _ramp_up(array, float(a), float(b))
    result = np.zeros(array.shape, dtype="float32")
    valid = np.isfinite(array)
    if b > a:
        rising = valid & (array >= a) & (array < b)
        result[rising] = (array[rising] - a) / (b - a)
    plateau = valid & (array >= b) & (array <= c)
    result[plateau] = 1.0
    if d > c:
        falling = valid & (array > c) & (array <= d)
        result[falling] = (d - array[falling]) / (d - c)
    result[~valid] = np.nan
    return result


def _ramp_up(values: Any, low: float, high: float):
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    result = np.clip((array - low) / max(high - low, 1.0e-6), 0.0, 1.0)
    result[~np.isfinite(array)] = np.nan
    return result


def _ramp_down(values: Any, low: float, high: float):
    return 1.0 - _ramp_up(values, low, high)


def _weighted_membership(
    memberships: Mapping[str, Any],
    weights: Mapping[str, float],
    shape: tuple[int, ...],
):
    return _weighted_parts(
        [(value, weights[key]) for key, value in memberships.items()],
        shape,
    )


def _weighted_parts(parts: list[tuple[Any | None, float]], shape: tuple[int, ...]):
    np = require_numpy()
    numerator = np.zeros(shape, dtype="float32")
    denominator = np.zeros(shape, dtype="float32")
    for value, weight in parts:
        if value is None:
            continue
        array = np.asarray(value, dtype="float32")
        valid = np.isfinite(array)
        numerator += np.where(valid, array * weight, 0.0)
        denominator += valid * weight
    return np.divide(
        numerator,
        denominator,
        out=np.full(shape, 0.5, dtype="float32"),
        where=denominator > 0,
    )
