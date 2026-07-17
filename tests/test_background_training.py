from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import h5py
import pytest

from uk_wsr_visualizer.background_training import (
    BACKGROUND_TRAINING_MANIFEST_ID,
    BackgroundTrainingExclusions,
    BackgroundTrainingSelectionConfig,
    background_training_exclusions_from_benchmark,
    background_training_local_path,
    build_background_training_manifest,
    validate_background_training_manifest,
)
from uk_wsr_visualizer.background_training_download import (
    download_and_validate_training_source,
)


def _fixture() -> tuple[dict, dict[str, dict]]:
    base = "https://example.test"
    radar = "test-radar"
    root = {
        "radars": [
            {
                "radar": radar,
                "radar_num": "99",
                "coverage_keys": [
                    f"ukmo-nimrod/catalog/pvol/{radar}/2023/coverage.json",
                    f"ukmo-nimrod/catalog/pvol/{radar}/2025/coverage.json",
                ],
            }
        ]
    }
    responses: dict[str, dict] = {}
    for year, dates in (
        (
            "2023",
            (
                "20230105",
                "20230125",
                "20230305",
                "20230325",
                "20230605",
                "20230625",
                "20230905",
                "20230925",
            ),
        ),
        (
            "2025",
            (
                "20250105",
                "20250125",
                "20250305",
                "20250325",
                "20250605",
                "20250625",
                "20250905",
                "20250925",
            ),
        ),
    ):
        days = []
        for date in dates:
            catalog_key = (
                f"ukmo-nimrod/catalog/pvol/{radar}/{year}/"
                f"{date[4:6]}/{date[6:8]}/catalog.json"
            )
            days.append(
                {
                    "date": date,
                    "catalog_key": catalog_key,
                    "pulse_counts": {"lp": 144, "sp": 72},
                }
            )
            files = []
            for target_time in ("0000", "0400", "0800", "1200", "1800", "2200"):
                for pulse in ("lp", "sp"):
                    filename = f"{date}-{pulse}-{target_time}.h5"
                    files.append(
                        {
                            "filename": filename,
                            "object_key": f"data/{filename}",
                            "object_url": f"{base}/data/{filename}",
                            "pulse": pulse,
                            "time": target_time,
                            "size_bytes": 100,
                        }
                    )
            responses[f"{base}/{catalog_key}"] = {"files": files}
        responses[
            f"{base}/ukmo-nimrod/catalog/pvol/{radar}/{year}/coverage.json"
        ] = {"days": days}
    return root, responses


def _small_config() -> BackgroundTrainingSelectionConfig:
    return BackgroundTrainingSelectionConfig(
        training_dates_per_season=1,
        evaluation_dates_per_season=2,
        minimum_training_sources=8,
        minimum_training_dates=4,
        minimum_training_span_days=180,
        minimum_training_dates_per_season=1,
        minimum_training_sources_per_utc_slot=0,
        minimum_validation_dates=4,
        minimum_holdout_dates=4,
    )


def test_manifest_is_date_held_out_and_joint_field_stratified() -> None:
    root, responses = _fixture()

    manifest = build_background_training_manifest(
        root,
        responses.__getitem__,
        config=_small_config(),
        public_base="https://example.test",
    )

    assert manifest["manifest_id"] == BACKGROUND_TRAINING_MANIFEST_ID
    assert manifest["file_count"] == 48
    assert manifest["errors"] == []
    assert manifest["validation_errors"] == []
    assert manifest["counts"]["by_split"] == {
        "holdout": 16,
        "training": 16,
        "validation": 16,
    }
    assert {item["pulse"] for item in manifest["files"]} == {"lp", "sp"}
    assert all(item["all_elevations"] for item in manifest["files"])
    assert all(item["benchmark_exclusion_checked"] for item in manifest["files"])
    dates_by_split = {
        split: {
            item["date"] for item in manifest["files"] if item["split"] == split
        }
        for split in ("training", "validation", "holdout")
    }
    assert dates_by_split["training"].isdisjoint(dates_by_split["validation"])
    assert dates_by_split["training"].isdisjoint(dates_by_split["holdout"])
    assert dates_by_split["validation"].isdisjoint(dates_by_split["holdout"])


def test_manifest_rejects_benchmark_date_before_catalog_selection() -> None:
    root, responses = _fixture()
    exclusions = BackgroundTrainingExclusions(
        radar_dates=frozenset({("test-radar", "20230105")})
    )

    manifest = build_background_training_manifest(
        root,
        responses.__getitem__,
        config=_small_config(),
        exclusions=exclusions,
        public_base="https://example.test",
    )

    assert not any(item["date"] == "20230105" for item in manifest["files"])
    assert manifest["validation_errors"] == []


def test_manifest_backfills_an_excluded_benchmark_source() -> None:
    root, responses = _fixture()
    blocked_url = "https://example.test/data/20230125-lp-0000.h5"
    exclusions = BackgroundTrainingExclusions(urls=frozenset({blocked_url}))

    manifest = build_background_training_manifest(
        root,
        responses.__getitem__,
        config=_small_config(),
        exclusions=exclusions,
        public_base="https://example.test",
    )

    assert manifest["warnings"]
    assert blocked_url not in {item["object_url"] for item in manifest["files"]}
    assert manifest["validation_errors"] == []


def test_validator_detects_split_date_leakage() -> None:
    root, responses = _fixture()
    manifest = build_background_training_manifest(
        root,
        responses.__getitem__,
        config=_small_config(),
        public_base="https://example.test",
    )
    broken = deepcopy(manifest)
    training_date = next(
        item["date"] for item in broken["files"] if item["split"] == "training"
    )
    holdout = next(item for item in broken["files"] if item["split"] == "holdout")
    holdout["date"] = training_date

    errors = validate_background_training_manifest(broken)

    assert any("training/holdout date leakage" in error for error in errors)


def test_evaluation_date_uses_available_common_time_pair() -> None:
    root, responses = _fixture()
    spring_catalog = responses[
        "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/"
        "2025/03/25/catalog.json"
    ]
    spring_catalog["files"] = [
        item
        for item in spring_catalog["files"]
        if item["time"] in {"0800", "1200"}
    ]

    manifest = build_background_training_manifest(
        root,
        responses.__getitem__,
        config=_small_config(),
        public_base="https://example.test",
    )

    spring_holdout = [
        item
        for item in manifest["files"]
        if item["season"] == "spring" and item["split"] == "holdout"
    ]
    assert {item["target_time"] for item in spring_holdout} == {"0800", "1200"}
    assert manifest["validation_errors"] == []


def test_benchmark_exclusions_include_url_date_and_downloaded_hash() -> None:
    exclusions = background_training_exclusions_from_benchmark(
        {
            "files": [
                {
                    "radar": "test-radar",
                    "date": "20240101",
                    "object_url": "https://example.test/benchmark.h5",
                }
            ]
        },
        {"targets": [{"source_sha256": "a" * 64}]},
    )

    assert exclusions.urls == frozenset({"https://example.test/benchmark.h5"})
    assert exclusions.radar_dates == frozenset({("test-radar", "20240101")})
    assert exclusions.source_sha256 == frozenset({"a" * 64})


def test_training_local_path_is_split_and_radar_scoped(tmp_path: Path) -> None:
    path = background_training_local_path(
        tmp_path,
        {
            "split": "training",
            "radar": "test-radar",
            "date": "20230101",
            "pulse": "lp",
            "filename": "source.h5",
        },
    )

    assert path == (
        tmp_path / "training" / "test-radar" / "20230101" / "lp" / "source.h5"
    )


def test_downloader_deletes_content_matching_benchmark_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    with h5py.File(source, "w") as h5:
        dataset = h5.create_group("dataset1")
        data = dataset.create_group("data1")
        data.create_dataset("data", data=[[1]])
        what = data.create_group("what")
        what.attrs["quantity"] = "DBZH"
    digest = sha256(source.read_bytes()).hexdigest()
    item = {
        "source_id": "source-1",
        "split": "training",
        "radar": "test-radar",
        "date": "20230101",
        "time": "0000",
        "pulse": "lp",
        "object_url": "https://example.test/source.h5",
        "size_bytes": source.stat().st_size,
    }
    previous = {
        "source_id": "source-1",
        "local_path": str(source),
        "size_bytes": source.stat().st_size,
        "sha256": digest,
        "hdf5_valid": True,
    }

    with pytest.raises(ValueError, match="excluded QC benchmark"):
        download_and_validate_training_source(
            item,
            source,
            retries=1,
            previous=previous,
            excluded_source_sha256={digest},
        )

    assert not source.exists()
