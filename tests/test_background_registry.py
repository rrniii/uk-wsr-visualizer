from __future__ import annotations

import json
from pathlib import Path

from uk_wsr_visualizer.background_registry import (
    BACKGROUND_MODEL_REGISTRY_SCHEMA_VERSION,
    audit_background_model_registry,
    eligible_registry_entries,
    load_background_model_registry,
)


def _write_model(
    path: Path,
    *,
    source_dates: list[str],
    qc_version: str = "qc-v2",
    include_ci: bool = True,
) -> None:
    arrays = {
        "sample_count": {},
        "persistent_echo_frequency": {},
        "dbzh_p90": {},
        "near_zero_vrad_frequency": {},
    }
    if include_ci:
        arrays |= {"ci_sample_count": {}, "low_ci_frequency": {}}
    path.write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_model",
                "schema_version": 1,
                "key": {
                    "radar": "test-radar",
                    "pulse": "lp",
                    "quantity": "DBZH",
                    "dataset": "dataset1",
                    "elevation_deg": 0.5,
                },
                "metadata": {
                    "qc_version": qc_version,
                    "source_dates": source_dates,
                    "source_date_count": len(source_dates),
                    "source_start_date": source_dates[0],
                    "source_end_date": source_dates[-1],
                    "training_span_days": 18,
                },
                "inline_arrays": arrays,
            }
        ),
        encoding="utf-8",
    )


def test_registry_audit_quarantines_same_day_legacy_model(tmp_path: Path) -> None:
    _write_model(
        tmp_path / "legacy.json",
        source_dates=["20260703"],
        qc_version="qc-v1-legacy",
        include_ci=False,
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_model_manifest",
                "schema_version": 1,
                "models": [
                    {
                        "filename": "legacy.json",
                        "radar": "test-radar",
                        "pulse": "lp",
                        "quantity": "DBZH",
                        "dataset": "dataset1",
                        "training_date": "20260703",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = audit_background_model_registry(tmp_path)

    assert registry["schema_version"] == BACKGROUND_MODEL_REGISTRY_SCHEMA_VERSION
    assert registry["eligible_model_count"] == 0
    entry = registry["models"][0]
    assert entry["status"] == "quarantined"
    assert "insufficient_training_dates:1<7" in entry["qualification_reasons"]
    assert "validation_design:same_day_within_sequence" in entry["qualification_reasons"]
    assert any(reason.startswith("missing_runtime_arrays:") for reason in entry["qualification_reasons"])


def test_registry_audit_qualifies_only_date_held_out_qc_v2_model(tmp_path: Path) -> None:
    dates = ["20260701", "20260704", "20260707", "20260710", "20260713", "20260716", "20260719"]
    _write_model(tmp_path / "qualified.json", source_dates=dates)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_model_manifest",
                "schema_version": 2,
                "models": [
                    {
                        "filename": "qualified.json",
                        "radar": "test-radar",
                        "pulse": "lp",
                        "quantity": "DBZH",
                        "dataset": "dataset1",
                        "validation_design": "date_held_out",
                        "validation_dates": ["20260722", "20260725"],
                        "validation_date_count": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = audit_background_model_registry(tmp_path)
    manifest_path = tmp_path / "audited.json"
    manifest_path.write_text(json.dumps(registry), encoding="utf-8")
    loaded = load_background_model_registry(manifest_path)

    assert registry["eligible_model_count"] == 1
    assert registry["models"][0]["status"] == "qualified"
    assert eligible_registry_entries(loaded) == (registry["models"][0],)


def test_registry_loader_rejects_schema_v1(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_model_manifest",
                "schema_version": 1,
                "models": [],
            }
        ),
        encoding="utf-8",
    )

    assert load_background_model_registry(path) is None
