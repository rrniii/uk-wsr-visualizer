from __future__ import annotations

from uk_wsr_visualizer.qc_benchmark import (
    BENCHMARK_ID,
    BenchmarkAnchor,
    LABEL_TAXONOMY,
    annotation_template,
    build_benchmark_manifest,
    validate_annotation_document,
    validate_benchmark_manifest,
)


def _catalog_fixture() -> tuple[dict, dict[str, dict]]:
    root = {
        "radars": [
            {
                "radar": "test-radar",
                "radar_num": "99",
                "coverage_keys": [
                    "ukmo-nimrod/catalog/pvol/test-radar/2025/coverage.json",
                ],
            }
        ]
    }
    responses = {
        "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/2025/coverage.json": {
            "days": [
                {
                    "date": "20250109",
                    "catalog_key": "ukmo-nimrod/catalog/pvol/test-radar/2025/01/09/catalog.json",
                }
            ]
        },
        "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/2025/01/09/catalog.json": {
            "files": [
                {
                    "filename": "lp-2355.h5",
                    "object_url": "https://data.test/lp-2355.h5",
                    "pulse": "lp",
                    "time": "2355",
                    "size_bytes": 10,
                },
                {
                    "filename": "sp-0005.h5",
                    "object_url": "https://data.test/sp-0005.h5",
                    "pulse": "sp",
                    "time": "0005",
                    "size_bytes": 8,
                },
            ]
        },
    }
    return root, responses


def test_manifest_selects_both_pulses_with_circular_midnight_distance() -> None:
    root, responses = _catalog_fixture()
    anchor = BenchmarkAnchor(
        anchor_id="winter-development-0000",
        target_date="20250108",
        target_time="0000",
        season="winter",
        utc_slot="overnight",
        split="development",
    )

    manifest = build_benchmark_manifest(
        root,
        responses.__getitem__,
        anchors=(anchor,),
        public_base="https://example.test",
    )

    assert manifest["file_count"] == 2
    assert manifest["errors"] == []
    assert {item["pulse"] for item in manifest["files"]} == {"lp", "sp"}
    assert {item["time_offset_minutes"] for item in manifest["files"]} == {5}
    assert all(item["exclude_from_background_training"] for item in manifest["files"])
    assert validate_benchmark_manifest(manifest) == []


def test_manifest_fails_closed_when_one_pulse_is_missing() -> None:
    root, responses = _catalog_fixture()
    responses[
        "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/2025/01/09/catalog.json"
    ]["files"] = responses[
        "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/2025/01/09/catalog.json"
    ]["files"][:1]
    anchor = BenchmarkAnchor(
        "winter-development-0000",
        "20250108",
        "0000",
        "winter",
        "overnight",
        "development",
    )

    manifest = build_benchmark_manifest(
        root,
        responses.__getitem__,
        anchors=(anchor,),
        public_base="https://example.test",
    )

    assert manifest["file_count"] == 0
    assert manifest["errors"][0]["error"] == "complete_volume_missing"
    assert validate_benchmark_manifest(manifest)


def test_manifest_validator_detects_missing_grid_cell() -> None:
    root, responses = _catalog_fixture()
    anchor = BenchmarkAnchor(
        "winter-development-0000",
        "20250108",
        "0000",
        "winter",
        "overnight",
        "development",
    )
    manifest = build_benchmark_manifest(
        root,
        responses.__getitem__,
        anchors=(anchor,),
        public_base="https://example.test",
    )
    manifest["files"] = manifest["files"][:-1]
    manifest["file_count"] = len(manifest["files"])

    errors = validate_benchmark_manifest(manifest)

    assert any("file count" in error for error in errors)
    assert any("grid mismatch" in error for error in errors)
    assert any("by_pulse is unbalanced" in error for error in errors)


def test_manifest_skips_partial_day_using_coverage_counts() -> None:
    root, responses = _catalog_fixture()
    coverage_url = "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/2025/coverage.json"
    responses[coverage_url]["days"] = [
        {
            "date": "20250108",
            "catalog_key": "ukmo-nimrod/catalog/pvol/test-radar/2025/01/08/catalog.json",
            "pulse_counts": {"lp": 288, "sp": 10},
        },
        {
            "date": "20250109",
            "catalog_key": "ukmo-nimrod/catalog/pvol/test-radar/2025/01/09/catalog.json",
            "pulse_counts": {"lp": 288, "sp": 144},
        },
    ]
    responses[
        "https://example.test/ukmo-nimrod/catalog/pvol/test-radar/2025/01/08/catalog.json"
    ] = {
        "files": [
            {
                "filename": "partial-lp.h5",
                "object_url": "https://data.test/partial-lp.h5",
                "pulse": "lp",
                "time": "0000",
            },
            {
                "filename": "partial-sp.h5",
                "object_url": "https://data.test/partial-sp.h5",
                "pulse": "sp",
                "time": "0000",
            },
        ]
    }
    anchor = BenchmarkAnchor(
        "winter-development-0000",
        "20250108",
        "0000",
        "winter",
        "overnight",
        "development",
    )

    manifest = build_benchmark_manifest(
        root,
        responses.__getitem__,
        anchors=(anchor,),
        public_base="https://example.test",
    )

    assert manifest["file_count"] == 2
    assert {item["date"] for item in manifest["files"]} == {"20250109"}


def test_annotation_contract_rejects_qc_as_truth_and_action_mismatch() -> None:
    root, responses = _catalog_fixture()
    anchor = BenchmarkAnchor(
        "winter-development-0000",
        "20250108",
        "0000",
        "winter",
        "overnight",
        "development",
    )
    manifest = build_benchmark_manifest(
        root,
        responses.__getitem__,
        anchors=(anchor,),
        public_base="https://example.test",
    )
    document = annotation_template(manifest, reviewer="reviewer-a")
    document["items"] = [
        {
            "case_id": manifest["files"][0]["case_id"],
            "dataset": "dataset1",
            "elevation_deg": 0.5,
            "quantity": "DBZH",
            "shape": [360, 425],
            "review_stage": "primary",
            "qc_outputs_visible": True,
            "ci_used_as_ground_truth": True,
            "current_filter_used_as_ground_truth": False,
            "regions": [
                {
                    "region_id": "region-1",
                    "label": "precipitation",
                    "action": "remove",
                    "confidence": 0.95,
                    "geometry": {
                        "type": "polar_gate_polygon",
                        "vertices": [[0, 0], [0, 5], [5, 5]],
                    },
                }
            ],
        }
    ]

    errors = validate_annotation_document(document, manifest)

    assert any("primary review must be blind" in error for error in errors)
    assert any("CI cannot be used as ground truth" in error for error in errors)
    assert any("does not match" in error for error in errors)


def test_annotation_contract_accepts_other_coherent_signal_as_retain() -> None:
    root, responses = _catalog_fixture()
    anchor = BenchmarkAnchor(
        "winter-development-0000",
        "20250108",
        "0000",
        "winter",
        "overnight",
        "development",
    )
    manifest = build_benchmark_manifest(
        root,
        responses.__getitem__,
        anchors=(anchor,),
        public_base="https://example.test",
    )
    document = annotation_template(manifest, reviewer="reviewer-a")
    document["items"] = [
        {
            "case_id": manifest["files"][0]["case_id"],
            "dataset": "dataset1",
            "elevation_deg": 0.5,
            "quantity": "DBZH",
            "shape": [360, 425],
            "review_stage": "primary",
            "qc_outputs_visible": False,
            "ci_used_as_ground_truth": False,
            "current_filter_used_as_ground_truth": False,
            "regions": [
                {
                    "region_id": "region-1",
                    "label": "other_coherent_signal",
                    "action": LABEL_TAXONOMY["other_coherent_signal"]["action"],
                    "confidence": 0.75,
                    "geometry": {"type": "row_major_rle", "runs": [[0, 10]]},
                }
            ],
        }
    ]

    assert document["benchmark_id"] == BENCHMARK_ID
    assert validate_annotation_document(document, manifest) == []
