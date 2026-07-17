from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from uk_wsr_visualizer.qc_benchmark import (
    BENCHMARK_ID,
    benchmark_counts,
)
from uk_wsr_visualizer.qc_review import (
    build_review_target_manifest,
    discover_review_sweeps,
    validate_review_target_manifest,
)


def _write_volume(path: Path, elevations: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5:
        for dataset_index, elevation in enumerate(elevations, start=1):
            dataset = h5.create_group(f"dataset{dataset_index}")
            where = dataset.create_group("where")
            where.attrs["elangle"] = elevation
            for data_index, quantity in enumerate(("DBZH", "VRADH", "CI"), start=1):
                group = dataset.create_group(f"data{data_index}")
                what = group.create_group("what")
                what.attrs["quantity"] = quantity
                group.create_dataset("data", data=np.zeros((4, 5), dtype="uint8"))


def _benchmark(tmp_path: Path) -> dict:
    anchors = [
        {
            "anchor_id": "winter-development-0000",
            "target_date": "20240101",
            "target_time": "0000",
            "season": "winter",
            "utc_slot": "overnight",
            "split": "development",
        },
        {
            "anchor_id": "winter-development-1200",
            "target_date": "20240101",
            "target_time": "1200",
            "season": "winter",
            "utc_slot": "midday",
            "split": "development",
        },
    ]
    files = []
    for pulse in ("lp", "sp"):
        for index, anchor in enumerate(anchors):
            case_id = f"test-radar-{pulse}-{index}"
            filename = f"{case_id}.h5"
            item = {
                "case_id": case_id,
                "anchor_id": anchor["anchor_id"],
                "split": anchor["split"],
                "season": anchor["season"],
                "utc_slot": anchor["utc_slot"],
                "target_date": anchor["target_date"],
                "target_time": anchor["target_time"],
                "date": "20240101",
                "time": anchor["target_time"],
                "date_offset_days": 0,
                "time_offset_minutes": 0,
                "radar": "test-radar",
                "radar_num": "99",
                "pulse": pulse,
                "quantity": "DBZH",
                "all_elevations": True,
                "filename": filename,
                "object_key": filename,
                "object_url": f"https://example.test/{filename}",
                "size_bytes": 1,
                "annotation_status": "untriaged",
                "exclude_from_background_training": True,
            }
            files.append(item)
            source = (
                tmp_path
                / item["split"]
                / item["radar"]
                / item["date"]
                / item["pulse"]
                / filename
            )
            _write_volume(source, [0.5, 1.0, 2.0] if pulse == "lp" else [1.0, 2.0, 4.0, 89.9])
    return {
        "schema": "uk_wsr_qc_benchmark_manifest",
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "selection": {
            "anchors": anchors,
            "pulses": ["lp", "sp"],
            "expected_file_count": 4,
            "max_day_offset": 0,
            "max_time_offset_minutes": 0,
        },
        "annotation_contract": {},
        "radar_count": 1,
        "anchor_count": 2,
        "file_count": 4,
        "errors": [],
        "counts": benchmark_counts(files),
        "files": files,
    }


def test_review_sweep_discovery_includes_shape_and_companions(tmp_path: Path) -> None:
    path = tmp_path / "sample.h5"
    _write_volume(path, [0.5, 2.0])

    sweeps = discover_review_sweeps(path)

    assert [item["dataset"] for item in sweeps] == ["dataset1", "dataset2"]
    assert sweeps[0]["shape"] == [4, 5]
    assert sweeps[0]["quantities"] == ["CI", "DBZH", "VRADH"]


def test_review_targets_cover_lowest_and_rotate_other_elevations(tmp_path: Path) -> None:
    benchmark = _benchmark(tmp_path)

    ledger = {
        "files": {
            item["case_id"]: {
                "size_bytes": 2048,
                "catalog_size_match": False,
                "sha256": "a" * 64,
            }
            for item in benchmark["files"]
        }
    }
    review = build_review_target_manifest(
        benchmark,
        source_root=tmp_path,
        download_ledger=ledger,
    )

    assert review["target_count"] == 8
    assert review["error_count"] == 0
    assert review["counts"]["by_selection_role"] == {
        "elevation_coverage": 4,
        "lowest": 4,
    }
    assert all("CI" in item["primary_hidden_fields"] for item in review["targets"])
    assert all(not item["primary_qc_outputs_visible"] for item in review["targets"])
    assert all(item["source_catalog_size_bytes"] == 1 for item in review["targets"])
    assert all(item["source_size_bytes"] == 2048 for item in review["targets"])
    assert all(item["source_catalog_size_match"] is False for item in review["targets"])
    assert all(item["source_sha256"] == "a" * 64 for item in review["targets"])
    assert "source_root" not in review
    assert validate_review_target_manifest(review, benchmark) == []

    lp_coverage = [
        item["dataset"]
        for item in review["targets"]
        if item["pulse"] == "lp" and item["selection_role"] == "elevation_coverage"
    ]
    sp_coverage = [
        item["dataset"]
        for item in review["targets"]
        if item["pulse"] == "sp" and item["selection_role"] == "elevation_coverage"
    ]
    assert lp_coverage == ["dataset2", "dataset3"]
    assert sp_coverage == ["dataset2", "dataset3"]


def test_double_review_is_allocated_inside_every_stratum(tmp_path: Path) -> None:
    benchmark = _benchmark(tmp_path)

    review = build_review_target_manifest(benchmark, source_root=tmp_path)

    for pulse in ("lp", "sp"):
        targets = [item for item in review["targets"] if item["pulse"] == pulse]
        assert len(targets) == 4
        assert sum(item["double_review_required"] for item in targets) == 1
