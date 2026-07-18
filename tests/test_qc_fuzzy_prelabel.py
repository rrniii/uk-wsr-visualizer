from __future__ import annotations

import numpy as np

from uk_wsr_visualizer.qc_fuzzy_prelabel import (
    FUZZY_PRELABEL_ID,
    fuzzy_prelabel,
    mask_to_row_major_rle,
)


def test_row_major_rle_round_trip_shape_independent() -> None:
    mask = np.zeros((3, 6), dtype=bool)
    mask[0, 2:5] = True
    mask[1, :2] = True
    mask[2, 5] = True

    assert mask_to_row_major_rle(mask) == [[2, 3], [6, 2], [17, 1]]


def test_fuzzy_prelabel_separates_synthetic_c_band_evidence() -> None:
    shape = (24, 30)
    dbzh = np.full(shape, 20.0, dtype="float32")
    rhohv = np.full(shape, 0.99, dtype="float32")
    zdr = np.full(shape, 1.0, dtype="float32")
    phidp = np.zeros(shape, dtype="float32")
    velocity = np.full(shape, 5.0, dtype="float32")
    sqi = np.full(shape, 0.95, dtype="float32")

    clutter = (slice(4, 12), slice(5, 14))
    row, column = np.indices((8, 9))
    alternating = (row + column) % 2 == 0
    dbzh[clutter] = 25.0
    zdr[clutter] = np.where(alternating, 6.0, -1.0)
    rhohv[clutter] = np.where(alternating, 0.50, 0.95)
    phidp[clutter] = np.where(alternating, 40.0, -40.0)
    velocity[clutter] = 0.0

    insects = (slice(14, 21), slice(8, 22))
    dbzh[insects] = 10.0
    zdr[insects] = 4.5
    rhohv[insects] = 0.75
    velocity[insects] = 3.0
    sqi[insects] = 0.80

    dbzh[1, 25] = -10.0
    rhohv[1, 25] = 0.30
    sqi[1, 25] = 0.10
    velocity[1, 25] = 0.0

    result = fuzzy_prelabel(
        dbzh,
        {
            "RHOHV": rhohv,
            "ZDR": zdr,
            "PHIDP": phidp,
            "VRADH": velocity,
            "SQIH": sqi,
        },
    )

    assert result["model_id"] == FUZZY_PRELABEL_ID
    assert result["human_confirmation_required"] is True
    assert set(result["summary"]["class_counts"]) == {
        "receiver_noise",
        "static_ground_clutter",
        "biological_insects",
        "precipitation",
    }
    assert result["summary"]["class_counts"]["receiver_noise"] == 1
    assert result["summary"]["class_counts"]["static_ground_clutter"] > 0
    assert result["summary"]["class_counts"]["biological_insects"] > 0
    assert result["summary"]["class_counts"]["precipitation"] > 0


def test_fuzzy_prelabel_renormalises_missing_fields() -> None:
    dbzh = np.full((8, 10), 12.0, dtype="float32")
    velocity = np.full((8, 10), 4.0, dtype="float32")

    result = fuzzy_prelabel(dbzh, {"VRADH": velocity})

    assert result["available_fields"] == ["velocity"]
    assert "rhohv" in result["missing_fields"]
    assert result["summary"]["valid_gate_count"] == 80
