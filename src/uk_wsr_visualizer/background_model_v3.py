"""Date-balanced learned static-background statistics for qc-v3."""

from __future__ import annotations

import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .background_model import (
    CI_CANDIDATES,
    VRAD_CANDIDATES,
    BackgroundModel,
    BackgroundModelBuildConfig,
    BackgroundScan,
    build_background_model,
    hash_arrays,
)
from .dependencies import require_numpy

BACKGROUND_MODEL_V3_STATISTICS_VERSION = "date-balanced-static-v2"
BACKGROUND_MODEL_V3_ARRAY_NAMES = (
    "dbzh_date_sample_count",
    "low_ci_date_sample_count",
    "low_ci_persistent_echo_date_frequency",
    "low_ci_vrad_date_sample_count",
    "low_ci_near_zero_vrad_date_frequency",
    "low_ci_static_echo_date_sample_count",
    "low_ci_static_echo_date_frequency",
    "low_ci_static_echo_season_count",
    "low_ci_static_echo_time_bucket_count",
    "low_ci_static_dbzh_date_sample_count",
    "low_ci_static_dbzh_p10",
    "low_ci_static_dbzh_median",
    "low_ci_static_dbzh_p90",
)


@dataclass(frozen=True)
class DateBalancedBackgroundConfig:
    """Thresholds for independent date/season/time support."""

    within_date_presence_min: float = 0.80
    minimum_within_date_samples: int = 1
    season_static_frequency_min: float = 0.75
    minimum_supported_dates_per_season: int = 1
    time_bucket_static_frequency_min: float = 0.75
    minimum_supported_dates_per_time_bucket: int = 2
    day_start_hour_utc: int = 6
    night_start_hour_utc: int = 19


def build_date_balanced_background_model(
    scans: list[BackgroundScan],
    *,
    key: dict[str, Any] | None = None,
    base_config: BackgroundModelBuildConfig | None = None,
    date_config: DateBalancedBackgroundConfig | None = None,
) -> BackgroundModel:
    """Build scan statistics plus date-balanced static-clutter support."""

    if not scans:
        raise ValueError("at least one scan is required")
    np = require_numpy()
    base_policy = base_config or BackgroundModelBuildConfig()
    policy = date_config or DateBalancedBackgroundConfig()
    base = build_background_model(
        scans,
        key=key,
        config=base_policy,
    )
    grouped: dict[str, list[BackgroundScan]] = defaultdict(list)
    for scan in scans:
        date = str(getattr(scan.metadata, "date", "") or "")
        if len(date) != 8 or not date.isdigit():
            raise ValueError(
                "date-balanced background scans require YYYYMMDD metadata"
            )
        grouped[date].append(scan)

    shape = base.shape
    date_dbzh: list[Any] = []
    date_static_dbzh: list[Any] = []
    low_ci_date_support = np.zeros(shape, dtype="float32")
    low_ci_echo_positive = np.zeros(shape, dtype="float32")
    low_ci_vrad_date_support = np.zeros(shape, dtype="float32")
    low_ci_static_velocity_positive = np.zeros(
        shape,
        dtype="float32",
    )
    joint_date_support = np.zeros(shape, dtype="float32")
    joint_date_positive = np.zeros(shape, dtype="float32")
    bucket_support = {
        bucket: np.zeros(shape, dtype="float32")
        for bucket in ("day", "night")
    }
    bucket_positive = {
        bucket: np.zeros(shape, dtype="float32")
        for bucket in ("day", "night")
    }
    season_support = {
        season: np.zeros(shape, dtype="float32")
        for season in ("winter", "spring", "summer", "autumn")
    }
    season_positive = {
        season: np.zeros(shape, dtype="float32")
        for season in season_support
    }

    for date, date_scans in sorted(grouped.items()):
        values_stack = np.stack(
            [
                np.asarray(scan.values, dtype="float32")
                for scan in date_scans
            ]
        )
        if values_stack.shape[1:] != shape:
            raise ValueError("date-balanced scan geometry changed")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            date_dbzh.append(
                np.nanmedian(values_stack, axis=0).astype("float32")
            )
        low_ci_stack = []
        low_ci_vrad_stack = []
        echo_stack = []
        static_stack = []
        for scan, values in zip(date_scans, values_stack):
            companions = _normalise_fields(
                scan.companion_fields,
                shape,
            )
            ci = _field(companions, CI_CANDIDATES)
            velocity = _field(companions, VRAD_CANDIDATES)
            if ci is None:
                low_ci = np.zeros(shape, dtype=bool)
            else:
                low_ci = (
                    np.isfinite(ci)
                    & (ci <= base_policy.ci_low_max_db)
                )
            echo = (
                low_ci
                & np.isfinite(values)
                & (values >= base_policy.echo_threshold_dbz)
            )
            low_ci_stack.append(low_ci)
            echo_stack.append(echo)
            if velocity is None:
                low_ci_vrad = np.zeros(shape, dtype=bool)
                static = np.zeros(shape, dtype=bool)
            else:
                low_ci_vrad = low_ci & np.isfinite(velocity)
                static = (
                    echo
                    & low_ci_vrad
                    & (np.abs(velocity) <= base_policy.vrad_abs_max_ms)
                )
            low_ci_vrad_stack.append(low_ci_vrad)
            static_stack.append(static)

        low_ci_count = np.stack(low_ci_stack).sum(axis=0)
        echo_count = np.stack(echo_stack).sum(axis=0)
        low_ci_vrad_count = np.stack(low_ci_vrad_stack).sum(axis=0)
        static_array = np.stack(static_stack)
        static_count = static_array.sum(axis=0)
        low_ci_supported = (
            low_ci_count >= policy.minimum_within_date_samples
        )
        low_ci_vrad_supported = (
            low_ci_vrad_count >= policy.minimum_within_date_samples
        )
        echo_positive = low_ci_supported & (
            _safe_frequency(echo_count, low_ci_count)
            >= policy.within_date_presence_min
        )
        static_velocity_positive = low_ci_vrad_supported & (
            _safe_frequency(static_count, low_ci_vrad_count)
            >= policy.within_date_presence_min
        )
        joint_supported = low_ci_vrad_supported
        joint_positive = echo_positive & static_velocity_positive
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            date_static_median = np.nanmedian(
                np.where(static_array, values_stack, np.nan),
                axis=0,
            ).astype("float32")
        date_static_median[~joint_positive] = np.nan
        date_static_dbzh.append(date_static_median)
        low_ci_date_support += low_ci_supported
        low_ci_echo_positive += echo_positive
        low_ci_vrad_date_support += low_ci_vrad_supported
        low_ci_static_velocity_positive += static_velocity_positive
        joint_date_support += joint_supported
        joint_date_positive += joint_positive

        season = _season(date)
        season_support[season] += joint_supported
        season_positive[season] += joint_positive
        for bucket in {
            _time_bucket(scan.metadata, policy)
            for scan in date_scans
        }:
            bucket_support[bucket] += joint_supported
            bucket_positive[bucket] += joint_positive

    date_stack = np.stack(date_dbzh)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        date_percentiles = np.nanpercentile(
            date_stack,
            (10.0, 50.0, 90.0),
            axis=0,
        ).astype("float32")
        static_date_stack = np.stack(date_static_dbzh)
        static_date_percentiles = np.nanpercentile(
            static_date_stack,
            (10.0, 50.0, 90.0),
            axis=0,
        ).astype("float32")
    arrays = dict(base.arrays)
    arrays.update(
        {
            "dbzh_p10": date_percentiles[0],
            "dbzh_median": date_percentiles[1],
            "dbzh_p90": date_percentiles[2],
            "dbzh_date_sample_count": np.isfinite(date_stack)
            .sum(axis=0)
            .astype("float32"),
            "low_ci_date_sample_count": low_ci_date_support,
            "low_ci_persistent_echo_date_frequency": _safe_frequency(
                low_ci_echo_positive,
                low_ci_date_support,
            ),
            "low_ci_vrad_date_sample_count": low_ci_vrad_date_support,
            "low_ci_near_zero_vrad_date_frequency": _safe_frequency(
                low_ci_static_velocity_positive,
                low_ci_vrad_date_support,
            ),
            "low_ci_static_echo_date_sample_count": joint_date_support,
            "low_ci_static_echo_date_frequency": _safe_frequency(
                joint_date_positive,
                joint_date_support,
            ),
            "low_ci_static_echo_season_count": _qualified_bucket_count(
                season_support,
                season_positive,
                minimum_dates=policy.minimum_supported_dates_per_season,
                minimum_frequency=policy.season_static_frequency_min,
                shape=shape,
            ),
            "low_ci_static_echo_time_bucket_count": (
                _qualified_bucket_count(
                    bucket_support,
                    bucket_positive,
                    minimum_dates=(
                        policy.minimum_supported_dates_per_time_bucket
                    ),
                    minimum_frequency=(
                        policy.time_bucket_static_frequency_min
                    ),
                    shape=shape,
                )
            ),
            "low_ci_static_dbzh_date_sample_count": np.isfinite(
                static_date_stack
            )
            .sum(axis=0)
            .astype("float32"),
            "low_ci_static_dbzh_p10": static_date_percentiles[0],
            "low_ci_static_dbzh_median": static_date_percentiles[1],
            "low_ci_static_dbzh_p90": static_date_percentiles[2],
        }
    )
    metadata = dict(base.metadata) | {
        "generated_at": _now_utc(),
        "statistics_version": BACKGROUND_MODEL_V3_STATISTICS_VERSION,
        "date_balanced_config": asdict(policy),
        "date_balanced_source_dates": sorted(grouped),
        "date_balanced_source_date_count": len(grouped),
        "date_balanced_dbzh_quantiles": (
            "percentiles across per-date median DBZH"
        ),
        "date_balanced_static_dbzh_quantiles": (
            "percentiles across per-date median DBZH conditioned on "
            "low CI, echo presence, near-zero VRAD, and within-date "
            "static qualification"
        ),
        "pseudoreplication_control": (
            "each date contributes at most one persistence/static vote"
        ),
    }
    return BackgroundModel(
        key=base.key,
        shape=base.shape,
        arrays=arrays,
        metadata=metadata,
        array_hash=hash_arrays(arrays),
    )


def _qualified_bucket_count(
    support: dict[str, Any],
    positive: dict[str, Any],
    *,
    minimum_dates: int,
    minimum_frequency: float,
    shape: tuple[int, int],
) -> Any:
    np = require_numpy()
    output = np.zeros(shape, dtype="float32")
    for name in sorted(support):
        supported = support[name] >= int(minimum_dates)
        frequency = _safe_frequency(positive[name], support[name])
        output += (
            supported & (frequency >= float(minimum_frequency))
        ).astype("float32")
    return output


def _normalise_fields(
    fields: dict[str, Any],
    shape: tuple[int, int],
) -> dict[str, Any]:
    np = require_numpy()
    return {
        str(quantity).strip().upper(): array
        for quantity, values in fields.items()
        if (array := np.asarray(values, dtype="float32")).shape == shape
    }


def _field(
    fields: dict[str, Any],
    candidates: tuple[str, ...],
) -> Any | None:
    return next(
        (
            fields[candidate]
            for candidate in candidates
            if candidate in fields
        ),
        None,
    )


def _safe_frequency(count: Any, support: Any) -> Any:
    np = require_numpy()
    numerator = np.asarray(count, dtype="float32")
    denominator = np.asarray(support, dtype="float32")
    output = np.zeros(numerator.shape, dtype="float32")
    np.divide(
        numerator,
        denominator,
        out=output,
        where=denominator > 0,
    )
    return output


def _season(date: str) -> str:
    month = int(date[4:6])
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _time_bucket(
    metadata: Any,
    policy: DateBalancedBackgroundConfig,
) -> str:
    text = str(getattr(metadata, "time", "") or "").zfill(4)
    if len(text) != 4 or not text.isdigit():
        raise ValueError(
            "date-balanced background scans require HHMM metadata"
        )
    minutes = int(text[:2]) * 60 + int(text[2:])
    day_start = policy.day_start_hour_utc * 60
    night_start = policy.night_start_hour_utc * 60
    return "day" if day_start <= minutes < night_start else "night"


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
