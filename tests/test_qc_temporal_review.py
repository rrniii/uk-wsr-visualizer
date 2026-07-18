from __future__ import annotations

from copy import deepcopy

from uk_wsr_visualizer.qc_temporal_review import (
    build_temporal_review_target_manifest,
    validate_temporal_review_target_manifest,
)


def _fixtures():
    records = []
    files = []
    ledger_files = {}
    for time, score in (("0005", 0.01), ("0010", 0.20), ("0015", 0.02)):
        source_id = f"radar-20250101-{time}-lp-current"
        previous_id = f"radar-20250101-{time}-lp-previous"
        next_id = f"radar-20250101-{time}-lp-next"
        for context_id, context_time in (
            (source_id, time),
            (previous_id, "0000"),
            (next_id, "0020"),
        ):
            if context_id not in ledger_files:
                digest = (context_id.encode().hex() + "0" * 64)[:64]
                files.append(
                    {
                        "source_id": context_id,
                        "split": "validation",
                        "filename": f"{context_id}.h5",
                        "object_url": f"https://example.test/{context_id}.h5",
                        "date": "20250101",
                        "time": context_time,
                    }
                )
                ledger_files[context_id] = {
                    "source_id": context_id,
                    "sha256": digest,
                    "size_bytes": 100,
                }
        records.append(
            {
                "job_id": f"geometry__{source_id}",
                "target_id": "radar_lp_dbzh_e00500_4x5_r0m_s600000mm",
                "radar": "radar",
                "pulse": "lp",
                "elevation_deg": 0.5,
                "shape": [4, 5],
                "split": "validation",
                "companions": ["DBZH", "VRADH", "CI"],
                "configuration_sha256": "c" * 64,
                "artifact_npz": f"/tmp/{source_id}.npz",
                "artifact_sha256": "a" * 64,
                "artifact_array_hash": "b" * 64,
                "source": {
                    "source_id": source_id,
                    "sha256": ledger_files[source_id]["sha256"],
                    "dataset": "dataset1",
                    "date": "20250101",
                    "time": time,
                },
                "context": {
                    "previous": {
                        "source_id": previous_id,
                        "sha256": ledger_files[previous_id]["sha256"],
                        "dataset": "dataset1",
                        "date": "20250101",
                        "time": "0000",
                    },
                    "next": {
                        "source_id": next_id,
                        "sha256": ledger_files[next_id]["sha256"],
                        "dataset": "dataset1",
                        "date": "20250101",
                        "time": "0020",
                    },
                },
                "delta": {
                    "learned_increment_count": int(score * 100),
                    "learned_increment_dbzh": {
                        "linear_reflectivity_fraction": score,
                    },
                },
                "baseline": {
                    "removed_fraction": 0.0,
                    "removed_dbzh": {
                        "linear_reflectivity_fraction": 0.0,
                    },
                },
            }
        )
    validation = {
        "schema": "uk_wsr_background_validation_results",
        "complete": True,
        "split": "validation",
        "configuration_sha256": "c" * 64,
        "summary": {"target_count": 1},
        "records": records,
    }
    policy = {
        "schema": "uk_wsr_background_validation_policy",
        "configuration_sha256": "c" * 64,
        "target_count": 1,
        "targets": [
            {
                "target_id": "radar_lp_dbzh_e00500_4x5_r0m_s600000mm",
                "state": "requires_blinded_review",
                "blockers": [],
            }
        ],
    }
    manifest = {
        "schema": "uk_wsr_temporal_context_manifest",
        "files": files,
    }
    ledger = {
        "schema": "uk_wsr_temporal_context_download_ledger",
        "files": ledger_files,
    }
    return validation, policy, manifest, ledger


def test_builds_hidden_challenge_and_candidate_independent_control():
    validation, policy, manifest, ledger = _fixtures()
    review = build_temporal_review_target_manifest(
        validation,
        policy,
        manifest,
        ledger,
    )

    assert review["target_count"] == 2
    assert review["counts"]["double_review_count"] == 2
    roles = {
        target["selection_role_internal"]: target
        for target in review["targets"]
    }
    assert set(roles) == {
        "candidate_challenge",
        "candidate_independent_control",
    }
    assert roles["candidate_challenge"]["time"] == "0010"
    assert all(
        target["selection_role"] == "stratified_case"
        for target in review["targets"]
    )
    assert all(
        "CI" in target["primary_hidden_fields"]
        for target in review["targets"]
    )
    assert all(
        view["quantity"] != "CI"
        for target in review["targets"]
        for view in target["review_views"]
    )


def test_validation_rejects_holdout_source_and_exposed_role():
    validation, policy, manifest, ledger = _fixtures()
    review = build_temporal_review_target_manifest(
        validation,
        policy,
        manifest,
        ledger,
    )
    broken_manifest = deepcopy(manifest)
    source_id = review["targets"][0]["review_views"][0]["source"][
        "source_id"
    ]
    next(
        item
        for item in broken_manifest["files"]
        if item["source_id"] == source_id
    )["split"] = "holdout"
    review["targets"][0]["selection_role"] = "candidate_challenge"

    errors = validate_temporal_review_target_manifest(
        review,
        validation=validation,
        frozen_policy=policy,
        temporal_manifest=broken_manifest,
        download_ledger=ledger,
    )

    assert any("selection identity is exposed" in error for error in errors)
    assert any("non-validation temporal source" in error for error in errors)
