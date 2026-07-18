from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from uk_wsr_visualizer.background_model_v3 import (
    BACKGROUND_MODEL_V3_STATISTICS_VERSION,
)
from uk_wsr_visualizer.qc_evidence import EvidenceContext, classify_nuisance_echoes


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "validation"
    / "candidate6e_parity_fixtures.json"
)


def _array(values: list[float | None], rows: int, columns: int) -> np.ndarray:
    return np.asarray([np.nan if value is None else value for value in values], dtype="float32").reshape(rows, columns)


def test_candidate6e_shared_parity_fixtures_match_python_reference() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    assert fixture["schema"] == "uk_wsr_candidate6e_parity"

    for case in fixture["cases"]:
        rows, columns = case["rows"], case["columns"]
        dbzh = _array(case["values"], rows, columns)
        companions = {
            name: _array(values, rows, columns)
            for name, values in case["companions"].items()
        }
        context = EvidenceContext(
            previous_dbzh=_array(case["previous_dbzh"], rows, columns),
            next_dbzh=_array(case["next_dbzh"], rows, columns),
            previous_vrad=_array(case["previous_vrad"], rows, columns),
            next_vrad=_array(case["next_vrad"], rows, columns),
            temporal_context_required=True,
            upper_elevation_dbzh=(
                _array(case["upper_elevation_dbzh"], rows, columns)
                if case["upper_elevation_dbzh"] is not None
                else None
            ),
            upper_elevation_required=case["upper_elevation_required"],
            background_statistics_version=BACKGROUND_MODEL_V3_STATISTICS_VERSION,
            background_distinct_date_count=np.full((rows, columns), 8, dtype="float32"),
            background_static_echo_date_frequency=np.full((rows, columns), 0.9, dtype="float32"),
            background_static_echo_season_count=np.full((rows, columns), 4, dtype="float32"),
            background_static_echo_time_bucket_count=np.full((rows, columns), 2, dtype="float32"),
            background_static_dbzh_p10=dbzh - 1,
            background_static_dbzh_median=dbzh,
            background_static_dbzh_p90=dbzh + 2,
        )
        result = classify_nuisance_echoes(dbzh, companions, pulse="sp", context=context)
        assert result.remove_mask.ravel().tolist() == case["expected_remove"], case["id"]
