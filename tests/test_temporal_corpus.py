from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from uk_wsr_visualizer.temporal_corpus import (
    TemporalCorpusSelectionConfig,
    build_temporal_context_manifest,
    load_verified_temporal_context_corpus,
    validate_temporal_context_manifest,
)


def test_temporal_manifest_builds_bracketed_day_and_night_sequences() -> None:
    catalog_key = "catalog/day.json"
    catalog = {
        "files": [
            _catalog_file(time, pulse="lp")
            for time in (
                "0050",
                "0100",
                "0110",
                "1150",
                "1200",
                "1210",
            )
        ]
    }
    source_manifest = {
        "manifest_id": "source",
        "errors": [],
        "validation_errors": [],
        "files": [
            _anchor("0100", "night", catalog_key),
            _anchor("1200", "day", catalog_key),
        ],
    }
    config = TemporalCorpusSelectionConfig(
        pulses=("lp",),
        splits=("training",),
        seasons=("winter",),
        time_buckets=("day", "night"),
        sequence_length=3,
        maximum_gap_minutes=20,
    )

    manifest = build_temporal_context_manifest(
        source_manifest,
        lambda url: catalog,
        source_manifest_sha256="a" * 64,
        config=config,
    )

    assert manifest["validation_errors"] == []
    assert manifest["sequence_count"] == 2
    assert manifest["file_count"] == 6
    assert {
        sequence["time_bucket"] for sequence in manifest["sequences"]
    } == {"day", "night"}
    for sequence in manifest["sequences"]:
        assert sequence["anchor_index"] == 1
        assert (
            sequence["eligible_scoring_source_ids"]
            == [sequence["anchor_source_id"]]
        )
        anchor = sequence["members"][1]
        assert anchor["previous_source_id"] == sequence["source_ids"][0]
        assert anchor["next_source_id"] == sequence["source_ids"][2]


def test_temporal_manifest_validation_rejects_shared_sources() -> None:
    catalog_key = "catalog/day.json"
    catalog = {
        "files": [
            _catalog_file(time, pulse="lp")
            for time in ("1150", "1200", "1210")
        ]
    }
    source_manifest = {
        "manifest_id": "source",
        "errors": [],
        "validation_errors": [],
        "files": [_anchor("1200", "day", catalog_key)],
    }
    config = TemporalCorpusSelectionConfig(
        pulses=("lp",),
        splits=("training",),
        seasons=("winter",),
        time_buckets=("day",),
        sequence_length=3,
    )
    manifest = build_temporal_context_manifest(
        source_manifest,
        lambda url: catalog,
        source_manifest_sha256="a" * 64,
        config=config,
    )
    manifest["sequences"].append(dict(manifest["sequences"][0]))
    manifest["sequences"][-1]["sequence_id"] = "duplicate"
    manifest["sequence_count"] = 2

    errors = validate_temporal_context_manifest(manifest)

    assert "sequences share one or more source files" in errors


def test_verified_temporal_loader_requires_exact_selected_partitions(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.h5"
    source_file.write_bytes(b"verified")
    source_id = "source"
    item = {
        "source_id": source_id,
        "split": "training",
        "season": "winter",
        "time_bucket": "day",
        "date": "20250101",
        "time": "1200",
        "radar": "chenies",
        "pulse": "lp",
        "filename": "source.h5",
        "object_key": "objects/source.h5",
        "object_url": "https://example.test/objects/source.h5",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "files": [item],
                "sequences": [
                    {
                        "sequence_id": "sequence",
                        "split": "training",
                        "season": "winter",
                        "time_bucket": "day",
                        "date": "20250101",
                        "radar": "chenies",
                        "pulse": "lp",
                        "anchor_source_id": source_id,
                        "source_ids": [source_id],
                        "eligible_scoring_source_ids": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    selected_hash = sha256(source_id.encode("utf-8")).hexdigest()
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "manifest_sha256": sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
                "selected_splits": ["training"],
                "selected_file_count": 1,
                "validated_file_count": 1,
                "selected_source_ids_sha256": selected_hash,
                "failures": [],
                "files": {
                    source_id: {
                        "local_path": str(source_file),
                        "sha256": sha256(
                            source_file.read_bytes()
                        ).hexdigest(),
                        "size_bytes": source_file.stat().st_size,
                        "hdf5_valid": True,
                        "benchmark_hash_exclusion_checked": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    corpus = load_verified_temporal_context_corpus(
        manifest_path,
        ledger_path,
        splits=("training",),
    )

    assert len(corpus.sources) == 1
    assert len(corpus.sequences) == 1
    assert corpus.sequences[0].source_ids == (source_id,)

    source_file.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="not a verified local HDF5"):
        load_verified_temporal_context_corpus(
            manifest_path,
            ledger_path,
            splits=("training",),
        )


def _anchor(time: str, bucket: str, catalog_key: str) -> dict:
    filename = f"chenies-20250101-{time}-lp.h5"
    return {
        "source_id": f"anchor-{time}",
        "split": "training",
        "season": "winter",
        "utc_slot": bucket,
        "date": "20250101",
        "time": time,
        "radar": "chenies",
        "radar_num": "1",
        "pulse": "lp",
        "quantity": "DBZH",
        "all_elevations": True,
        "joint_companion_fields": ["CI", "VRADH"],
        "filename": filename,
        "object_key": f"objects/{filename}",
        "object_url": f"https://example.test/objects/{filename}",
        "catalog_key": catalog_key,
    }


def _catalog_file(time: str, *, pulse: str) -> dict:
    filename = f"chenies-20250101-{time}-{pulse}.h5"
    return {
        "time": time,
        "pulse": pulse,
        "filename": filename,
        "object_key": f"objects/{filename}",
        "object_url": f"https://example.test/objects/{filename}",
        "size_bytes": 100,
    }
