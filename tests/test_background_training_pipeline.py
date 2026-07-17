from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import h5py
import numpy as np
import pytest

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_training_pipeline import (
    SweepDescriptor,
    VerifiedTrainingSource,
    build_sweep_inventory,
    cluster_training_targets,
    load_verified_training_sources,
    target_training_summary,
    train_background_target,
)


def test_verified_sources_require_matching_complete_ledger(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.h5"
    _write_volume(source_path, dataset="dataset1", elevation=1.0)
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "file_count": 1,
        "files": [
            {
                "source_id": "source-1",
                "radar": "chenies",
                "pulse": "lp",
                "split": "training",
                "date": "20230101",
                "time": "0000",
                "object_url": "https://example.test/source.h5",
                "object_key": "source.h5",
                "season": "winter",
                "utc_slot": "overnight",
            }
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    ledger_path = tmp_path / "ledger.json"
    ledger = {
        "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "validated_file_count": 1,
        "failures": [],
        "files": {
            "source-1": {
                "local_path": str(source_path),
                "sha256": sha256(source_path.read_bytes()).hexdigest(),
                "size_bytes": source_path.stat().st_size,
                "hdf5_valid": True,
                "benchmark_hash_exclusion_checked": True,
            }
        },
    }
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    sources = load_verified_training_sources(
        manifest_path,
        ledger_path,
    )

    assert len(sources) == 1
    assert sources[0].source_id == "source-1"
    broken = dict(ledger) | {"manifest_sha256": "0" * 64}
    ledger_path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_verified_training_sources(manifest_path, ledger_path)


def test_inventory_clusters_dataset_aliases_by_geometry(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.h5"
    second_path = tmp_path / "second.h5"
    _write_volume(first_path, dataset="dataset1", elevation=3.95)
    _write_volume(second_path, dataset="dataset5", elevation=4.0)
    sources = (
        _source(first_path, "first", "training", "20230101", "dataset1"),
        _source(second_path, "second", "validation", "20250101", "dataset5"),
    )

    sweeps = build_sweep_inventory(sources)
    targets = cluster_training_targets(sweeps)

    assert len(sweeps) == 2
    assert len(targets) == 1
    assert targets[0].dataset_aliases == ("dataset1", "dataset5")
    assert targets[0].elevation_deg == pytest.approx(3.975)
    assert len(targets[0].split_sweeps("training")) == 1
    assert len(targets[0].split_sweeps("validation")) == 1
    assert set(sweeps[0].companion_quantities) >= {
        "DBZH",
        "CI",
        "VRADH",
        "SQIH",
        "RHOHV",
        "ZDR",
        "PHIDP",
    }


def test_training_persists_geometry_sources_and_conditioned_counts(
    tmp_path: Path,
) -> None:
    sources = []
    for index, dataset in enumerate(
        ("dataset1", "dataset5", "dataset1", "dataset5")
    ):
        path = tmp_path / f"source-{index}.h5"
        _write_volume(
            path,
            dataset=dataset,
            elevation=3.95 if index % 2 == 0 else 4.0,
            dbzh=12.0 + index,
        )
        sources.append(
            _source(
                path,
                f"source-{index}",
                "training",
                f"202301{index + 1:02d}",
                dataset,
            )
        )
    target = cluster_training_targets(build_sweep_inventory(sources))[0]

    model, npz_path, json_path = train_background_target(
        target,
        tmp_path / "models",
        source_manifest_sha256="a" * 64,
        ledger_sha256="b" * 64,
    )
    loaded = load_background_model(json_path)
    summary = target_training_summary(
        target,
        model,
        npz_path,
        json_path,
    )

    assert npz_path.is_file()
    assert json_path.is_file()
    assert loaded.shape == (4, 5)
    assert loaded.key["dataset_aliases"] == ["dataset1", "dataset5"]
    assert loaded.metadata["source_manifest_sha256"] == "a" * 64
    assert loaded.metadata["source_date_count"] == 4
    assert np.all(loaded.arrays["low_ci_sample_count"] == 4)
    assert np.all(
        loaded.arrays["low_ci_near_zero_vrad_frequency"] == 1
    )
    assert summary["training_source_count"] == 4
    assert summary["promotion_eligible"] is False


def test_duplicate_matching_sweeps_in_one_source_are_rejected() -> None:
    base = SweepDescriptor(
        source_id="duplicate",
        radar="chenies",
        pulse="lp",
        split="training",
        date="20230101",
        time="0000",
        local_path="/tmp/unused.h5",
        sha256="a" * 64,
        dataset="dataset1",
        field_group="dataset1/data1",
        quantity="DBZH",
        elevation_deg=1.0,
        nrays=360,
        nbins=425,
        rstart_km=0.0,
        rscale_m=600.0,
        companion_quantities=("CI", "VRADH"),
    )
    duplicate = SweepDescriptor(
        **(
            base.__dict__
            | {
                "dataset": "dataset2",
                "field_group": "dataset2/data1",
                "elevation_deg": 1.02,
            }
        )
    )

    with pytest.raises(ValueError, match="multiple matching sweeps"):
        cluster_training_targets((base, duplicate))


def _source(
    path: Path,
    source_id: str,
    split: str,
    date: str,
    dataset: str,
) -> VerifiedTrainingSource:
    del dataset
    return VerifiedTrainingSource(
        source_id=source_id,
        radar="chenies",
        pulse="lp",
        split=split,
        date=date,
        time="0000",
        local_path=str(path),
        object_url=f"https://example.test/{path.name}",
        object_key=path.name,
        sha256=sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
    )


def _write_volume(
    path: Path,
    *,
    dataset: str,
    elevation: float,
    dbzh: float = 12.0,
) -> None:
    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.69
        where.attrs["lon"] = -0.53
        where.attrs["height"] = 140.0
        sweep = h5.create_group(dataset)
        sweep_where = sweep.create_group("where")
        sweep_where.attrs["elangle"] = elevation
        sweep_where.attrs["nrays"] = 4
        sweep_where.attrs["nbins"] = 5
        sweep_where.attrs["rstart"] = 0.0
        sweep_where.attrs["rscale"] = 600.0
        fields = {
            "DBZH": np.full((4, 5), dbzh, dtype="float32"),
            "CI": np.full((4, 5), 1.0, dtype="float32"),
            "VRADH": np.full((4, 5), 0.1, dtype="float32"),
            "SQIH": np.full((4, 5), 0.5, dtype="float32"),
            "RHOHV": np.full((4, 5), 0.7, dtype="float32"),
            "ZDR": np.full((4, 5), 1.0, dtype="float32"),
            "PHIDP": np.full((4, 5), 5.0, dtype="float32"),
        }
        for index, (quantity, values) in enumerate(fields.items(), start=1):
            field = sweep.create_group(f"data{index}")
            what = field.create_group("what")
            what.attrs["quantity"] = quantity
            what.attrs["gain"] = 1.0
            what.attrs["offset"] = 0.0
            what.attrs["nodata"] = -9999.0
            what.attrs["undetect"] = -9998.0
            field.create_dataset("data", data=values)
