from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import h5py
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from uk_wsr_visualizer.qc_benchmark import (
    BENCHMARK_ID,
    benchmark_local_path,
    canonical_json_sha256,
)
from uk_wsr_visualizer.qc_review_app import (
    ReviewStore,
    create_review_app,
    render_polar_field_png,
)


def _write_volume(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 54.8
        where.attrs["lon"] = -1.4
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nrays"] = 8
        dataset_where.attrs["nbins"] = 10
        dataset_where.attrs["rscale"] = 600.0
        for index, quantity in enumerate(("DBZH", "VRADH", "CI"), start=1):
            group = dataset.create_group(f"data{index}")
            what = group.create_group("what")
            what.attrs["quantity"] = quantity
            what.attrs["gain"] = 1.0
            what.attrs["offset"] = -30.0 if quantity == "DBZH" else 0.0
            group.create_dataset(
                "data",
                data=np.arange(80, dtype="uint8").reshape(8, 10),
            )


def _review_store(tmp_path: Path, *, stage: str = "primary") -> ReviewStore:
    item = {
        "case_id": "high-moorsley-case",
        "split": "development",
        "radar": "high-moorsley",
        "date": "20240101",
        "time": "0000",
        "pulse": "lp",
        "filename": "volume.h5",
    }
    benchmark = {
        "benchmark_id": BENCHMARK_ID,
        "files": [item],
    }
    target = {
        "target_id": "target-1",
        "case_id": item["case_id"],
        "radar": item["radar"],
        "pulse": item["pulse"],
        "date": item["date"],
        "time": item["time"],
        "dataset": "dataset1",
        "elevation_deg": 0.5,
        "shape": [8, 10],
        "split": "development",
        "season": "winter",
        "utc_slot": "overnight",
        "selection_role": "lowest",
        "double_review_required": True,
        "primary_visible_fields": ["DBZH", "VRADH"],
        "primary_hidden_fields": ["CI", "QC_MASK"],
    }
    review = {
        "benchmark_id": BENCHMARK_ID,
        "benchmark_manifest_sha256": canonical_json_sha256(benchmark),
        "errors": [],
        "targets": [target],
    }
    benchmark_path = tmp_path / "manifest.json"
    targets_path = tmp_path / "review_targets.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    targets_path.write_text(json.dumps(review), encoding="utf-8")
    _write_volume(benchmark_local_path(tmp_path / "sources", item))
    return ReviewStore(
        benchmark_path=benchmark_path,
        targets_path=targets_path,
        source_root=tmp_path / "sources",
        output_dir=tmp_path / "annotations",
        reviewer="Independent Reviewer",
        stage=stage,
    )


def test_raw_review_renderer_produces_square_png() -> None:
    values = np.arange(80, dtype="float32").reshape(8, 10)

    content = render_polar_field_png(
        values,
        vmin=-30,
        vmax=70,
        palette="homeyer",
        size=96,
    )

    image = Image.open(BytesIO(content))
    assert image.format == "PNG"
    assert image.size == (96, 96)


def test_review_store_never_exposes_hidden_ci_and_persists_annotation(
    tmp_path: Path,
) -> None:
    store = _review_store(tmp_path)

    state = store.review_state()
    target = store.target_payload("target-1")
    assert state["blinding"]["ci_available_to_reviewer"] is False
    assert [item["quantity"] for item in target["visible_fields"]] == [
        "DBZH",
        "VRADH",
    ]
    assert store.field_png("target-1", "DBZH").startswith(b"\x89PNG")
    assert store.field_png("target-1", "VRADH").startswith(b"\x89PNG")

    try:
        store.field_png("target-1", "CI")
    except KeyError:
        pass
    else:  # pragma: no cover - security regression assertion.
        raise AssertionError("CI was exposed by the blinded review store")

    result = store.save_annotation(
        "target-1",
        {
            "notes": "coherent precipitation throughout",
            "regions": [
                {
                    "region_id": "region-1",
                    "label": "precipitation",
                    "action": "retain",
                    "confidence": 0.95,
                    "geometry": {"type": "full_sweep"},
                }
            ],
        },
    )

    assert result["completed_count"] == 1
    written = json.loads(store.annotation_path.read_text(encoding="utf-8"))
    assert written["reviewer"] == "Independent Reviewer"
    assert written["review_stage"] == "primary"
    assert written["items"][0]["qc_outputs_visible"] is False
    assert written["items"][0]["ci_used_as_ground_truth"] is False


def test_review_store_rejects_label_action_mismatch(tmp_path: Path) -> None:
    store = _review_store(tmp_path)

    try:
        store.save_annotation(
            "target-1",
            {
                "regions": [
                    {
                        "region_id": "region-1",
                        "label": "receiver_noise",
                        "action": "retain",
                        "confidence": 0.9,
                        "geometry": {"type": "full_sweep"},
                    }
                ]
            },
        )
    except ValueError as exc:
        assert "requires action remove" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("label/action mismatch was accepted")


def test_review_api_refuses_ci_and_accepts_valid_polygon(tmp_path: Path) -> None:
    store = _review_store(tmp_path, stage="secondary")
    client = TestClient(create_review_app(store))

    state = client.get("/api/review")
    assert state.status_code == 200
    assert state.json()["target_count"] == 1
    assert client.get("/api/targets/target-1/fields/CI.png").status_code == 404
    assert (
        client.get("/api/targets/target-1/fields/DBZH.png").headers["content-type"]
        == "image/png"
    )

    response = client.post(
        "/api/targets/target-1/annotation",
        json={
            "regions": [
                {
                    "region_id": "region-1",
                    "label": "static_ground_clutter",
                    "action": "remove",
                    "confidence": 0.8,
                    "geometry": {
                        "type": "polar_gate_polygon",
                        "vertices": [[0.0, 0.0], [2.0, 4.0], [4.0, 1.0]],
                    },
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["region_count"] == 1
