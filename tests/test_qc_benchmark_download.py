from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from uk_wsr_visualizer.qc_benchmark import benchmark_local_path
from uk_wsr_visualizer.qc_benchmark_download import (
    download_and_validate_source,
    load_download_ledger,
    validate_pvol_source,
)


def test_benchmark_local_path_keeps_split_radar_date_and_pulse(tmp_path: Path) -> None:
    item = {
        "split": "holdout",
        "radar": "high-moorsley",
        "date": "20241221",
        "pulse": "sp",
        "filename": "volume.h5",
    }

    assert benchmark_local_path(tmp_path, item) == (
        tmp_path / "holdout/high-moorsley/20241221/sp/volume.h5"
    )


def test_hdf5_validation_requires_dataset_and_data_group(tmp_path: Path) -> None:
    valid = tmp_path / "valid.h5"
    invalid = tmp_path / "invalid.h5"
    with h5py.File(valid, "w") as h5:
        dataset = h5.create_group("dataset1")
        data = dataset.create_group("data1")
        what = data.create_group("what")
        what.attrs["quantity"] = "DBZH"
        data.create_dataset("data", data=np.zeros((2, 2), dtype="uint8"))
    with h5py.File(invalid, "w") as h5:
        h5.create_group("metadata")

    assert validate_pvol_source(valid)
    assert not validate_pvol_source(invalid)


def test_invalid_download_ledger_fails_open_to_empty(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")

    assert load_download_ledger(missing) == {"files": {}}
    assert load_download_ledger(corrupt) == {"files": {}}

    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"files": {"case": {"sha256": "abc"}}}), encoding="utf-8")
    assert load_download_ledger(valid)["files"]["case"]["sha256"] == "abc"


def test_valid_hdf5_is_accepted_with_explicit_catalog_size_drift(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    destination = tmp_path / "downloaded.h5"
    with h5py.File(source, "w") as h5:
        dataset = h5.create_group("dataset1")
        data = dataset.create_group("data1")
        what = data.create_group("what")
        what.attrs["quantity"] = "DBZH"
        data.create_dataset("data", data=np.zeros((2, 2), dtype="uint8"))

    result = download_and_validate_source(
        {
            "case_id": "case-1",
            "object_url": source.as_uri(),
            "size_bytes": 1,
        },
        destination,
        retries=1,
        previous=None,
    )

    assert result["hdf5_valid"]
    assert result["catalog_size_match"] is False
    assert result["catalog_size_bytes"] == 1
    assert result["size_bytes"] == source.stat().st_size
    assert result["status"] == "downloaded_catalog_drift"
