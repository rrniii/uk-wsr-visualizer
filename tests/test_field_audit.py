from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from uk_wsr_visualizer.field_audit import (
    SampleAnchor,
    _diagnostic_rows,
    _without_local_paths,
    audit_sweep,
    build_sample_plan,
    discover_reflectivity_sweeps,
)


def test_sample_plan_selects_both_pulses_nearest_date_and_time() -> None:
    root = {
        "radars": [
            {
                "radar": "high-moorsley",
                "radar_num": "23",
                "coverage_keys": ["ukmo-nimrod/catalog/pvol/high-moorsley/2026/coverage.json"],
            }
        ]
    }
    responses = {
        "https://example.test/ukmo-nimrod/catalog/pvol/high-moorsley/2026/coverage.json": {
            "days": [
                {
                    "date": "20260114",
                    "catalog_key": "ukmo-nimrod/catalog/pvol/high-moorsley/2026/01/14/catalog.json",
                },
                {
                    "date": "20260120",
                    "catalog_key": "ukmo-nimrod/catalog/pvol/high-moorsley/2026/01/20/catalog.json",
                },
            ]
        },
        "https://example.test/ukmo-nimrod/catalog/pvol/high-moorsley/2026/01/14/catalog.json": {
            "files": [
                {
                    "filename": "lp-0000.h5",
                    "object_url": "https://data/lp-0000.h5",
                    "pulse": "lp",
                    "time": "0000",
                    "size_bytes": 10,
                },
                {
                    "filename": "sp-0010.h5",
                    "object_url": "https://data/sp-0010.h5",
                    "pulse": "sp",
                    "time": "0010",
                    "size_bytes": 8,
                },
            ]
        },
    }

    plan = build_sample_plan(
        root,
        responses.__getitem__,
        anchors=(SampleAnchor("20260115", "0005"),),
        public_base="https://example.test",
    )

    assert plan["file_count"] == 2
    assert {entry["pulse"] for entry in plan["files"]} == {"lp", "sp"}
    assert {entry["date"] for entry in plan["files"]} == {"20260114"}
    assert {entry["time"] for entry in plan["files"]} == {"0000", "0010"}


def test_real_sweep_audit_separates_calibration_metadata_and_receiver_mask(tmp_path: Path) -> None:
    path = tmp_path / "sample.h5"
    dbzh = np.full((4, 5), -20.0, dtype="float32")
    dbzh[0, 0] = 30.0
    ci = np.full((4, 5), 7.0, dtype="float32")
    sqi = np.zeros((4, 5), dtype="float32")
    rhohv = np.zeros((4, 5), dtype="float32")
    phidp = np.indices((4, 5)).sum(axis=0).astype("float32") * 180.0
    vrad = np.where(np.indices((4, 5)).sum(axis=0) % 2, -20.0, 20.0).astype("float32")
    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 54.8
        where.attrs["lon"] = -1.4
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 5
        dataset_where.attrs["nrays"] = 4
        dataset_where.attrs["rstart"] = 0.0
        dataset_where.attrs["rscale"] = 1000.0
        dataset_how = dataset.create_group("how")
        dataset_how.attrs["RXnoiseH"] = 3.2
        dataset_how.attrs["RXnoiseV"] = 3.8
        for index, (quantity, values) in enumerate(
            (
                ("DBZH", dbzh),
                ("CI", ci),
                ("SQIH", sqi),
                ("RHOHV", rhohv),
                ("PHIDP", phidp),
                ("VRADH", vrad),
            ),
            start=1,
        ):
            group = dataset.create_group(f"data{index}")
            what = group.create_group("what")
            what.attrs["quantity"] = quantity
            what.attrs["gain"] = 1.0
            what.attrs["offset"] = 0.0
            group.create_dataset("data", data=values)
        quality = dataset.create_group("quality1")
        quality_what = quality.create_group("what")
        quality_what.attrs["quantity"] = "LONG_RANGE_NOISE_DBC_H"
        quality_what.attrs["gain"] = 1.0
        quality_what.attrs["offset"] = 0.0
        quality.create_dataset("data", data=np.full((4, 1), 25.0, dtype="float32"))

    targets = discover_reflectivity_sweeps(path)
    row, _ = audit_sweep(
        path,
        {
            "radar": "high-moorsley",
            "date": "20260711",
            "time": "1500",
            "pulse": "lp",
            "object_url": "https://example.test/sample.h5",
        },
        targets[0],
    )

    assert targets == [{"dataset": "dataset1", "quantity": "DBZH", "elevation_deg": 0.5}]
    assert row["receiver_noise_count"] > 0
    assert row["receiver_noise_ge_20_dbz"] == 0
    assert row["receiver_noise_figure_h_db"] == 3.2
    assert row["receiver_noise_figure_role"] == "calibration_only"
    assert row["ambient_noise_h_median"] == 25.0


def test_diagnostic_selection_covers_every_sp_radar_and_limits_lp_comparators() -> None:
    sweeps = []
    for radar_index in range(10):
        radar = f"radar-{radar_index}"
        for pulse in ("lp", "sp"):
            for sweep_index in range(2):
                sweeps.append(
                    {
                        "radar": radar,
                        "pulse": pulse,
                        "dataset": f"dataset{sweep_index + 1}",
                        "receiver_noise_ge_20_dbz": 0,
                        "receiver_noise_ge_10_dbz": radar_index * 10 + sweep_index,
                        "receiver_noise_max_dbz": float(radar_index),
                        "receiver_noise_fraction": 0.1 * sweep_index,
                    }
                )

    selected = _diagnostic_rows(sweeps)

    assert {row["radar"] for row in selected if row["pulse"] == "sp"} == {
        f"radar-{index}" for index in range(10)
    }
    assert len([row for row in selected if row["pulse"] == "lp"]) == 8
    assert all(row["dataset"] == "dataset2" for row in selected)


def test_published_audit_drops_local_paths_without_mutating_runtime_summary() -> None:
    summary = {
        "local_path": "/tmp/root.h5",
        "sweeps": [
            {
                "radar": "high-moorsley",
                "local_path": "/tmp/high-moorsley.h5",
                "nested": {"local_path": "/tmp/other.h5", "source_url": "https://example.test/file.h5"},
            }
        ],
    }

    published = _without_local_paths(summary)

    assert "local_path" not in published
    assert "local_path" not in published["sweeps"][0]
    assert "local_path" not in published["sweeps"][0]["nested"]
    assert published["sweeps"][0]["nested"]["source_url"] == "https://example.test/file.h5"
    assert summary["sweeps"][0]["local_path"] == "/tmp/high-moorsley.h5"
