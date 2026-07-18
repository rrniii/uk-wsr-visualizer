from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
from fastapi.testclient import TestClient

from uk_wsr_visualizer.qc_benchmark import canonical_json_sha256
from uk_wsr_visualizer.qc_review_app import create_review_app
from uk_wsr_visualizer.qc_temporal_review import (
    TEMPORAL_REVIEW_ID,
    TEMPORAL_REVIEW_SCHEMA,
)
from uk_wsr_visualizer.qc_temporal_review_app import TemporalReviewStore


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
        for index, quantity in enumerate(
            ("DBZH", "VRADH", "CI"),
            start=1,
        ):
            group = dataset.create_group(f"data{index}")
            what = group.create_group("what")
            what.attrs["quantity"] = quantity
            what.attrs["gain"] = 1.0
            what.attrs["offset"] = -30.0 if quantity == "DBZH" else 0.0
            group.create_dataset(
                "data",
                data=np.arange(80, dtype="uint8").reshape(8, 10),
            )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _store(tmp_path: Path) -> TemporalReviewStore:
    source = tmp_path / "source.h5"
    _write_volume(source)
    source_hash = _sha256(source)
    ledger = {
        "schema": "uk_wsr_temporal_context_download_ledger",
        "files": {
            "source-1": {
                "source_id": "source-1",
                "local_path": str(source),
                "sha256": source_hash,
                "size_bytes": source.stat().st_size,
            }
        },
    }
    source_entry = {
        "source_kind": "temporal",
        "source_id": "source-1",
        "sha256": source_hash,
        "size_bytes": source.stat().st_size,
        "filename": source.name,
        "url": "https://example.test/source.h5",
        "date": "20250101",
        "time": "0000",
        "dataset": "dataset1",
    }
    target = {
        "target_id": "temporal-target-1",
        "geometry_id": (
            "high-moorsley_lp_dbzh_e00500_8x10_r0m_s600000mm"
        ),
        "job_id": "job-1",
        "radar": "high-moorsley",
        "pulse": "lp",
        "date": "20250101",
        "time": "0000",
        "dataset": "dataset1",
        "elevation_deg": 0.5,
        "shape": [8, 10],
        "split": "validation",
        "season": "winter",
        "utc_slot": "night",
        "selection_role": "stratified_case",
        "selection_role_internal": "candidate_challenge",
        "double_review_required": True,
        "primary_qc_outputs_visible": False,
        "primary_hidden_fields": ["CI", "QC_MASK"],
        "review_views": [
            {
                "view_id": "current_dbzh",
                "label": "Current DBZH",
                "role": "current",
                "quantity": "DBZH",
                "annotation_primary": True,
                "source": source_entry,
            },
            {
                "view_id": "previous_dbzh",
                "label": "Previous DBZH",
                "role": "previous",
                "quantity": "DBZH",
                "annotation_primary": False,
                "source": source_entry,
            },
            {
                "view_id": "current_vradh",
                "label": "Current VRADH",
                "role": "current",
                "quantity": "VRADH",
                "annotation_primary": False,
                "source": source_entry,
            },
        ],
    }
    review = {
        "schema": TEMPORAL_REVIEW_SCHEMA,
        "schema_version": 1,
        "review_id": TEMPORAL_REVIEW_ID,
        "download_ledger_sha256": canonical_json_sha256(ledger),
        "selection": {"sealed_holdout_opened": False},
        "targets": [target],
    }
    targets_path = tmp_path / "review_targets.json"
    ledger_path = tmp_path / "download_ledger.json"
    targets_path.write_text(json.dumps(review), encoding="utf-8")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    return TemporalReviewStore(
        targets_path=targets_path,
        temporal_ledger_path=ledger_path,
        regression_root=tmp_path / "regressions",
        output_dir=tmp_path / "annotations",
        reviewer="Primary Reviewer",
        stage="primary",
    )


def test_temporal_review_exposes_context_but_not_ci_or_selection(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    state = store.review_state()
    payload = store.target_payload("temporal-target-1")

    assert state["blinding"]["selection_identity_visible"] is False
    assert state["blinding"]["sealed_holdout_opened"] is False
    assert payload["selection_role"] == "stratified_case"
    assert [field["label"] for field in payload["visible_fields"]] == [
        "Current DBZH",
        "Previous DBZH",
        "Current VRADH",
    ]
    assert sum(
        field["annotation_primary"] for field in payload["visible_fields"]
    ) == 1
    assert payload["visible_fields"][0]["palette"] == "homeyer"
    assert payload["visible_fields"][0]["palette_stops"][0] == [
        0.0,
        "#f5f5f5",
    ]
    assert payload["prelabel"]["status"] == "proposal_only"
    assert payload["prelabel"]["human_confirmation_required"] is True
    assert store.field_png(
        "temporal-target-1",
        "previous_dbzh",
    ).startswith(b"\x89PNG")
    try:
        store.field_png("temporal-target-1", "CI")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("CI was exposed by temporal review")


def test_temporal_review_api_saves_blinded_annotation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    client = TestClient(create_review_app(store))

    health = client.get("/api/health").json()
    assert health["review_id"] == TEMPORAL_REVIEW_ID
    response = client.post(
        "/api/targets/temporal-target-1/annotation",
        json={
            "prelabel_decision": "edited",
            "regions": [
                {
                    "region_id": "region-1",
                    "label": "precipitation",
                    "action": "retain",
                    "confidence": 0.95,
                    "geometry": {"type": "full_sweep"},
                }
            ]
        },
    )

    assert response.status_code == 200
    annotation = json.loads(
        store.annotation_path.read_text(encoding="utf-8")
    )
    assert annotation["review_policy"]["selection_identity_visible"] is False
    assert annotation["review_policy"]["sealed_holdout_opened"] is False
    assert annotation["items"][0]["ci_used_as_ground_truth"] is False
    assert annotation["items"][0]["prelabel_decision"] == "edited"
    assert len(
        annotation["items"][0]["prelabel_parameters_sha256"]
    ) == 64
