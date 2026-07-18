from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from uk_wsr_visualizer.background_model import BackgroundScan
from uk_wsr_visualizer.background_model_v3 import (
    BACKGROUND_MODEL_V3_STATISTICS_VERSION,
    build_date_balanced_background_model,
)


def test_date_balancing_prevents_one_event_from_counting_as_many_dates() -> None:
    scans = [
        _scan(10.0, "20250101", f"{index:02d}00")
        for index in range(12)
    ]
    scans.extend(
        _scan(-10.0, f"20250{month}01", "1200")
        for month in range(2, 9)
    )

    model = build_date_balanced_background_model(scans)

    assert model.metadata["statistics_version"] == (
        BACKGROUND_MODEL_V3_STATISTICS_VERSION
    )
    assert model.metadata["date_balanced_source_date_count"] == 8
    assert model.arrays["low_ci_persistent_echo_date_frequency"][
        0,
        0,
    ] == pytest.approx(1 / 8)
    assert model.arrays["low_ci_static_echo_date_frequency"][
        0,
        0,
    ] == pytest.approx(1 / 8)
    assert model.arrays["dbzh_median"][0, 0] == pytest.approx(-10.0)


def test_static_echo_requires_cross_season_and_day_night_support() -> None:
    scans = []
    for date in (
        "20250101",
        "20250201",
        "20250401",
        "20250501",
        "20250701",
        "20250801",
        "20251001",
        "20251101",
    ):
        scans.append(_scan(10.0, date, "0100"))
        scans.append(_scan(10.0, date, "1200"))

    model = build_date_balanced_background_model(scans)

    assert model.arrays["low_ci_static_echo_date_frequency"][
        0,
        0,
    ] == 1.0
    assert model.arrays["low_ci_static_echo_season_count"][0, 0] == 4
    assert model.arrays["low_ci_static_echo_time_bucket_count"][
        0,
        0,
    ] == 2


def test_static_dbzh_quantiles_exclude_high_ci_weather() -> None:
    scans = []
    for month in range(1, 9):
        date = f"2025{month:02d}01"
        scans.append(_scan(10.0, date, "0000", ci=1.0))
        scans.append(_scan(40.0, date, "1200", ci=8.0))

    model = build_date_balanced_background_model(scans)

    assert model.arrays["dbzh_median"][0, 0] == pytest.approx(25.0)
    assert model.arrays["low_ci_static_dbzh_median"][
        0,
        0,
    ] == pytest.approx(10.0)
    assert model.arrays["low_ci_static_dbzh_date_sample_count"][
        0,
        0,
    ] == 8


def _scan(
    dbzh: float,
    date: str,
    time: str,
    *,
    ci: float = 1.0,
) -> BackgroundScan:
    shape = (3, 4)
    return BackgroundScan(
        values=np.full(shape, dbzh, dtype="float32"),
        metadata=SimpleNamespace(date=date, time=time),
        companion_fields={
            "CI": np.full(shape, ci, dtype="float32"),
            "VRADH": np.zeros(shape, dtype="float32"),
        },
    )
