"""Exact-mask synthetic and semi-synthetic QC validation scenes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag
from typing import Any

from .dependencies import require_numpy


class SyntheticTruthFlag(IntFlag):
    RECEIVER_NOISE = 1
    STATIC_CLUTTER = 2
    ANOMALOUS_PROPAGATION = 4
    RADIAL_INTERFERENCE = 8
    ISOLATED_SPECKLE = 16


@dataclass(frozen=True)
class SyntheticConfig:
    pulse: str = "lp"
    nrays: int = 360
    nbins: int = 425
    rstart_km: float = 0.0
    rscale_m: float = 600.0
    dynamic_geometry: bool = False


@dataclass
class SyntheticScene:
    dbzh: Any
    companions: dict[str, Any]
    truth_mask: Any
    retain_mask: Any
    metadata: dict[str, Any]

    @property
    def remove_mask(self) -> Any:
        return self.truth_mask != 0

    @property
    def score_mask(self) -> Any:
        return self.remove_mask | self.retain_mask


def generate_synthetic_scene(
    config: SyntheticConfig | None = None,
    *,
    seed: int = 0,
) -> SyntheticScene:
    """Generate coherent retained echoes, then inject disjoint artifacts."""

    np = require_numpy()
    config = config or SyntheticConfig()
    rng = np.random.default_rng(seed)
    shape = (int(config.nrays), int(config.nbins))
    dbzh = np.full(shape, np.nan, dtype="float32")
    companions = {
        quantity: np.full(shape, np.nan, dtype="float32")
        for quantity in ("VRADH", "SQIH", "RHOHV", "ZDR", "PHIDP", "CI")
    }
    retain = np.zeros(shape, dtype=bool)
    ray, gate, azimuth = _coordinate_grids(shape)
    gate_fraction = gate / max(1.0, shape[1] - 1)

    weather_azimuth = rng.uniform(0.0, 360.0) if config.dynamic_geometry else 305.0
    weather_gate = rng.uniform(0.34, 0.68) if config.dynamic_geometry else 0.52
    weather_width = rng.uniform(19.0, 31.0) if config.dynamic_geometry else 27.0
    weather_strength = np.exp(
        -0.5 * (_angular_distance(azimuth, weather_azimuth) / weather_width) ** 2
        -0.5 * ((gate_fraction - weather_gate) / 0.15) ** 2
    )
    weather = weather_strength >= 0.055
    _apply_retained_signal(
        dbzh,
        companions,
        retain,
        weather,
        dbzh_values=4.0 + 46.0 * weather_strength + rng.normal(0.0, 1.2, shape),
        vrad_values=13.0 * np.sin(np.deg2rad(azimuth - 250.0)) + rng.normal(0.0, 0.5, shape),
        sqi_values=0.78 + 0.18 * weather_strength,
        rhohv_values=0.94 + 0.05 * weather_strength,
        zdr_values=0.4 + 1.2 * weather_strength,
        phidp_values=(0.25 * gate + 8.0 * np.sin(np.deg2rad(azimuth))) % 180.0,
        ci_values=5.2 + 2.0 * weather_strength + rng.normal(0.0, 0.35, shape),
    )

    ring_gate = rng.uniform(0.16, 0.38) if config.dynamic_geometry else 0.25
    ring_phase = rng.uniform(0.0, 360.0) if config.dynamic_geometry else 30.0
    ring_strength = np.exp(-0.5 * ((gate_fraction - ring_gate) / 0.075) ** 2) * (
        0.72 + 0.28 * np.cos(np.deg2rad(2.0 * azimuth - ring_phase))
    )
    biological = (ring_strength >= 0.28) & ~retain
    _apply_retained_signal(
        dbzh,
        companions,
        retain,
        biological,
        dbzh_values=-7.0 + 23.0 * ring_strength + rng.normal(0.0, 0.9, shape),
        vrad_values=7.0 * np.cos(np.deg2rad(azimuth - 210.0)) + rng.normal(0.0, 0.35, shape),
        sqi_values=0.32 + 0.35 * ring_strength,
        rhohv_values=0.42 + 0.30 * ring_strength,
        zdr_values=1.2 + 3.0 * ring_strength,
        phidp_values=35.0 * np.sin(np.deg2rad(azimuth)) + 0.08 * gate,
        ci_values=4.8 + 2.2 * ring_strength + rng.normal(0.0, 0.45, shape),
    )

    clear_air_base = rng.uniform(0.58, 0.84) if config.dynamic_geometry else 0.73
    clear_air_phase = rng.uniform(0.0, 360.0) if config.dynamic_geometry else 0.0
    clear_air_center = clear_air_base + 0.05 * np.sin(
        np.deg2rad(3.0 * azimuth + clear_air_phase)
    )
    clear_air = (np.abs(gate_fraction - clear_air_center) <= 0.02) & ~retain
    _apply_retained_signal(
        dbzh,
        companions,
        retain,
        clear_air,
        dbzh_values=-10.0 + 6.0 * np.cos(np.deg2rad(4.0 * azimuth)),
        vrad_values=4.0 * np.sin(np.deg2rad(azimuth + 15.0)),
        sqi_values=np.full(shape, 0.42),
        rhohv_values=np.full(shape, 0.68),
        zdr_values=np.full(shape, 0.4),
        phidp_values=12.0 * np.sin(np.deg2rad(2.0 * azimuth)),
        ci_values=np.full(shape, 6.1),
    )

    truth = np.zeros(shape, dtype="uint16")
    artifact_counts = _inject_artifacts(
        dbzh,
        companions,
        truth,
        protected=retain,
        pulse=config.pulse,
        rng=rng,
        ray=ray,
        gate=gate,
        azimuth=azimuth,
        dynamic_geometry=config.dynamic_geometry,
        rstart_km=config.rstart_km,
        rscale_m=config.rscale_m,
    )
    return SyntheticScene(
        dbzh=dbzh,
        companions=companions,
        truth_mask=truth,
        retain_mask=retain,
        metadata={
            "schema": "uk_wsr_qc_synthetic_scene",
            "schema_version": 2 if config.dynamic_geometry else 1,
            "seed": seed,
            "pulse": config.pulse.lower(),
            "nrays": shape[0],
            "nbins": shape[1],
            "rstart_km": float(config.rstart_km),
            "rscale_m": float(config.rscale_m),
            "artifact_counts": artifact_counts,
            "retain_count": int(retain.sum()),
            "dynamic_geometry": bool(config.dynamic_geometry),
            "generator": "coherent-weather-biology-clear-air-plus-disjoint-artifacts",
        },
    )


def inject_artifacts_into_base(
    base_dbzh: Any,
    base_companions: dict[str, Any] | None = None,
    *,
    pulse: str,
    seed: int,
    protected_mask: Any | None = None,
    artifact_exclusion_mask: Any | None = None,
    rstart_km: float = 0.0,
    rscale_m: float = 600.0,
) -> SyntheticScene:
    """Overlay exact-mask artifacts while preserving nominated real signal."""

    np = require_numpy()
    dbzh = np.asarray(base_dbzh, dtype="float32").copy()
    if dbzh.ndim != 2:
        raise ValueError("base DBZH must be a two-dimensional polar sweep")
    companions = {
        quantity: np.asarray(values, dtype="float32").copy()
        for quantity, values in (base_companions or {}).items()
        if np.asarray(values).shape == dbzh.shape
    }
    for quantity in ("VRADH", "SQIH", "RHOHV", "ZDR", "PHIDP", "CI"):
        companions.setdefault(quantity, np.full(dbzh.shape, np.nan, dtype="float32"))
    protected = (
        np.asarray(protected_mask, dtype=bool)
        if protected_mask is not None
        else np.isfinite(dbzh)
    )
    if protected.shape != dbzh.shape:
        raise ValueError("protected mask shape does not match DBZH")
    artifact_exclusion = (
        np.asarray(artifact_exclusion_mask, dtype=bool)
        if artifact_exclusion_mask is not None
        else protected
    )
    if artifact_exclusion.shape != dbzh.shape:
        raise ValueError(
            "artifact exclusion mask shape does not match DBZH"
        )
    if np.any(protected & ~artifact_exclusion):
        raise ValueError(
            "artifact exclusion mask must include every protected gate"
        )
    truth = np.zeros(dbzh.shape, dtype="uint16")
    ray, gate, azimuth = _coordinate_grids(dbzh.shape)
    counts = _inject_artifacts(
        dbzh,
        companions,
        truth,
        protected=artifact_exclusion,
        pulse=pulse,
        rng=np.random.default_rng(seed),
        ray=ray,
        gate=gate,
        azimuth=azimuth,
        dynamic_geometry=False,
        rstart_km=rstart_km,
        rscale_m=rscale_m,
    )
    return SyntheticScene(
        dbzh=dbzh,
        companions=companions,
        truth_mask=truth,
        retain_mask=protected,
        metadata={
            "schema": "uk_wsr_qc_semi_synthetic_scene",
            "schema_version": 1,
            "seed": seed,
            "pulse": pulse.lower(),
            "nrays": dbzh.shape[0],
            "nbins": dbzh.shape[1],
            "rstart_km": float(rstart_km),
            "rscale_m": float(rscale_m),
            "artifact_counts": counts,
            "retain_count": int(protected.sum()),
            "artifact_exclusion_count": int(artifact_exclusion.sum()),
            "generator": "artifact-overlay-on-protected-base",
        },
    )


def evaluate_predicted_removal(
    predicted_remove_mask: Any,
    scene: SyntheticScene,
) -> dict[str, Any]:
    """Score artifact removal and coherent-signal retention independently."""

    np = require_numpy()
    predicted = np.asarray(predicted_remove_mask, dtype=bool)
    if predicted.shape != scene.truth_mask.shape:
        raise ValueError("predicted mask shape does not match synthetic truth")
    truth_remove = np.asarray(scene.remove_mask, dtype=bool)
    truth_retain = np.asarray(scene.retain_mask, dtype=bool)
    true_positive = int((predicted & truth_remove).sum())
    false_positive = int((predicted & truth_retain).sum())
    false_negative = int((~predicted & truth_remove).sum())
    retained = int((~predicted & truth_retain).sum())
    predicted_scored = true_positive + false_positive
    artifact_count = int(truth_remove.sum())
    retain_count = int(truth_retain.sum())
    union = int((predicted & (truth_remove | truth_retain) | truth_remove).sum())
    per_artifact = {}
    for flag in SyntheticTruthFlag:
        flag_mask = (scene.truth_mask & int(flag)) != 0
        count = int(flag_mask.sum())
        per_artifact[flag.name.lower()] = {
            "count": count,
            "recall": _fraction((predicted & flag_mask).sum(), count),
        }
    high_signal = truth_retain & np.isfinite(scene.dbzh) & (scene.dbzh >= 20.0)
    high_signal_count = int(high_signal.sum())
    high_signal_removed = int((predicted & high_signal).sum())
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": retained,
        "artifact_count": artifact_count,
        "retain_count": retain_count,
        "precision": _fraction(true_positive, predicted_scored),
        "artifact_recall": _fraction(true_positive, artifact_count),
        "retain_recall": _fraction(retained, retain_count),
        "coherent_signal_removal_fraction": _fraction(false_positive, retain_count),
        "high_signal_retain_recall": _fraction(
            high_signal_count - high_signal_removed,
            high_signal_count,
        ),
        "high_signal_count": high_signal_count,
        "high_signal_removed": high_signal_removed,
        "intersection_over_union": _fraction(true_positive, union),
        "per_artifact": per_artifact,
    }


def _inject_artifacts(
    dbzh: Any,
    companions: dict[str, Any],
    truth: Any,
    *,
    protected: Any,
    pulse: str,
    rng: Any,
    ray: Any,
    gate: Any,
    azimuth: Any,
    dynamic_geometry: bool,
    rstart_km: float,
    rscale_m: float,
) -> dict[str, int]:
    np = require_numpy()
    available = ~np.asarray(protected, dtype=bool)
    shape = dbzh.shape
    gate_fraction = gate / max(1.0, shape[1] - 1)

    static_score = np.zeros(shape, dtype="float32")
    for ray_center, gate_center, ray_width, gate_width in (
        (18.0, 0.08, 5.0, 0.035),
        (112.0, 0.15, 7.0, 0.045),
        (251.0, 0.11, 4.0, 0.030),
    ):
        static_score = np.maximum(
            static_score,
            np.exp(
                -0.5 * ((_angular_distance(azimuth, ray_center) / ray_width) ** 2)
                -0.5 * (((gate_fraction - gate_center) / gate_width) ** 2)
            ),
        )
    static = available & (truth == 0) & (static_score >= 0.20)
    _apply_artifact(
        dbzh,
        companions,
        truth,
        static,
        SyntheticTruthFlag.STATIC_CLUTTER,
        dbzh_values=12.0 + 38.0 * static_score + rng.normal(0.0, 1.0, shape),
        vrad_values=rng.normal(0.0, 0.12, shape),
        sqi_values=0.55 + 0.35 * static_score,
        rhohv_values=0.48 + 0.38 * static_score,
        zdr_values=rng.normal(1.5, 1.0, shape),
        phidp_values=rng.normal(15.0, 8.0, shape),
        ci_values=0.4 + 1.2 * static_score,
    )

    ap_azimuth = rng.uniform(0.0, 360.0) if dynamic_geometry else 175.0
    ap_phase = rng.uniform(0.0, 360.0) if dynamic_geometry else 40.0
    ap_gate = rng.uniform(0.40, 0.64) if dynamic_geometry else 0.48
    ap_center = ap_gate + 0.08 * np.sin(np.deg2rad(2.0 * azimuth - ap_phase))
    ap = (
        available
        & (truth == 0)
        & (_angular_distance(azimuth, ap_azimuth) <= 58.0)
        & (np.abs(gate_fraction - ap_center) <= 0.035)
    )
    _apply_artifact(
        dbzh,
        companions,
        truth,
        ap,
        SyntheticTruthFlag.ANOMALOUS_PROPAGATION,
        dbzh_values=8.0
        + 20.0 * np.cos((gate_fraction - ap_center) / 0.07) ** 2
        + rng.normal(0.0, 1.5, shape),
        vrad_values=rng.normal(0.0, 0.28, shape),
        sqi_values=rng.uniform(0.15, 0.65, shape),
        rhohv_values=rng.uniform(0.25, 0.85, shape),
        zdr_values=rng.normal(1.0, 2.0, shape),
        phidp_values=rng.normal(25.0, 35.0, shape),
        ci_values=rng.uniform(0.2, 2.1, shape),
    )

    spoke = np.zeros(shape, dtype=bool)
    spoke_half_width = max(0.65, 0.8 * 360.0 / shape[0])
    spoke_centers = (
        tuple(float(value) for value in rng.uniform(0.0, 360.0, size=3))
        if dynamic_geometry
        else (58.0, 184.0, 332.0)
    )
    for center in spoke_centers:
        spoke |= _angular_distance(azimuth, center) <= spoke_half_width
    interference = (
        available
        & (truth == 0)
        & spoke
        & (gate_fraction >= 0.06)
        & (rng.random(shape) >= 0.08)
    )
    _apply_artifact(
        dbzh,
        companions,
        truth,
        interference,
        SyntheticTruthFlag.RADIAL_INTERFERENCE,
        dbzh_values=-5.0 + 23.0 * gate_fraction + rng.normal(0.0, 2.0, shape),
        vrad_values=rng.uniform(-28.0, 28.0, shape),
        sqi_values=rng.uniform(0.0, 0.18, shape),
        rhohv_values=rng.uniform(0.0, 0.45, shape),
        zdr_values=rng.uniform(-5.0, 10.0, shape),
        phidp_values=rng.uniform(-180.0, 180.0, shape),
        ci_values=rng.uniform(4.0, 8.0, shape),
    )

    pulse_key = str(pulse).lower()
    ranges_km = (
        float(rstart_km)
        + (gate + 0.5) * float(rscale_m) / 1000.0
    )
    range_law = 20.0 * np.log10(np.maximum(ranges_km, 0.1))
    floor = (
        np.maximum(range_law - 27.5, -18.0)
        if pulse_key == "sp"
        else np.maximum(range_law - 45.0, -32.0)
    )
    noise_probability = (
        0.46 + 0.26 * gate / max(1.0, shape[1] - 1)
        if pulse_key == "sp"
        else 0.28 + 0.16 * gate / max(1.0, shape[1] - 1)
    )
    noise = (
        available
        & (truth == 0)
        & (gate >= 8)
        & (rng.random(shape) < noise_probability)
    )
    _apply_artifact(
        dbzh,
        companions,
        truth,
        noise,
        SyntheticTruthFlag.RECEIVER_NOISE,
        dbzh_values=floor + rng.normal(0.0, 0.9, shape),
        vrad_values=rng.uniform(-30.0, 30.0, shape),
        sqi_values=rng.uniform(0.0, 0.045, shape),
        rhohv_values=rng.uniform(0.0, 0.18, shape),
        zdr_values=rng.uniform(-6.0, 11.0, shape),
        phidp_values=rng.uniform(-180.0, 180.0, shape),
        ci_values=rng.uniform(6.0, 8.0, shape),
    )

    available_points = np.argwhere(available & (truth == 0))
    speckle_count = min(max(32, shape[0] // 2), len(available_points))
    if speckle_count:
        chosen = available_points[
            rng.choice(len(available_points), size=speckle_count, replace=False)
        ]
        speckle = np.zeros(shape, dtype=bool)
        speckle[chosen[:, 0], chosen[:, 1]] = True
        _apply_artifact(
            dbzh,
            companions,
            truth,
            speckle,
            SyntheticTruthFlag.ISOLATED_SPECKLE,
            dbzh_values=rng.uniform(-8.0, 22.0, shape),
            vrad_values=rng.uniform(-20.0, 20.0, shape),
            sqi_values=rng.uniform(0.0, 0.3, shape),
            rhohv_values=rng.uniform(0.0, 0.7, shape),
            zdr_values=rng.uniform(-4.0, 8.0, shape),
            phidp_values=rng.uniform(-180.0, 180.0, shape),
            ci_values=rng.uniform(3.0, 8.0, shape),
        )

    return {
        flag.name.lower(): int(((truth & int(flag)) != 0).sum())
        for flag in SyntheticTruthFlag
    }


def _apply_retained_signal(
    dbzh: Any,
    companions: dict[str, Any],
    retain: Any,
    mask: Any,
    **values: Any,
) -> None:
    dbzh[mask] = values["dbzh_values"][mask]
    for quantity, key in (
        ("VRADH", "vrad_values"),
        ("SQIH", "sqi_values"),
        ("RHOHV", "rhohv_values"),
        ("ZDR", "zdr_values"),
        ("PHIDP", "phidp_values"),
        ("CI", "ci_values"),
    ):
        companions[quantity][mask] = values[key][mask]
    retain[mask] = True


def _apply_artifact(
    dbzh: Any,
    companions: dict[str, Any],
    truth: Any,
    mask: Any,
    flag: SyntheticTruthFlag,
    **values: Any,
) -> None:
    dbzh[mask] = values["dbzh_values"][mask]
    for quantity, key in (
        ("VRADH", "vrad_values"),
        ("SQIH", "sqi_values"),
        ("RHOHV", "rhohv_values"),
        ("ZDR", "zdr_values"),
        ("PHIDP", "phidp_values"),
        ("CI", "ci_values"),
    ):
        companions[quantity][mask] = values[key][mask]
    truth[mask] |= int(flag)


def _coordinate_grids(shape: tuple[int, int]) -> tuple[Any, Any, Any]:
    np = require_numpy()
    ray = np.arange(shape[0], dtype="float32")[:, None]
    gate = np.arange(shape[1], dtype="float32")[None, :]
    azimuth = ray * (360.0 / shape[0])
    return (
        np.broadcast_to(ray, shape),
        np.broadcast_to(gate, shape),
        np.broadcast_to(azimuth, shape),
    )


def _angular_distance(first: Any, second: float) -> Any:
    np = require_numpy()
    return np.abs((np.asarray(first) - second + 180.0) % 360.0 - 180.0)


def _fraction(numerator: Any, denominator: Any) -> float:
    denominator_value = int(denominator or 0)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0
