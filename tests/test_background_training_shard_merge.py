from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.merge_background_training_shards import merge_training_shards


def test_training_shards_merge_contract_identical_targets(
    tmp_path: Path,
) -> None:
    first = _write_shard(tmp_path / "one.json", "target-a", "radar-a")
    second = _write_shard(tmp_path / "two.json", "target-b", "radar-b")

    destination = merge_training_shards(
        [first, second],
        tmp_path / "merged.json",
        expected_target_count=2,
    )

    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["complete"] is True
    assert report["target_count"] == 2
    assert report["trained_target_count"] == 2
    assert report["radars"] == ["radar-a", "radar-b"]


def test_training_shards_reject_duplicate_targets(tmp_path: Path) -> None:
    first = _write_shard(tmp_path / "one.json", "target", "radar-a")
    second = _write_shard(tmp_path / "two.json", "target", "radar-a")

    with pytest.raises(ValueError, match="duplicate"):
        merge_training_shards(
            [first, second],
            tmp_path / "merged.json",
        )


def _write_shard(path: Path, target_id: str, radar: str) -> Path:
    payload = {
        "schema": "uk_wsr_background_training_v3_results",
        "schema_version": 1,
        "training_contract": {"schema": "contract"},
        "training_contract_sha256": "a" * 64,
        "source_count": 10,
        "source_date_count": 4,
        "target_count": 1,
        "trained_target_count": 1,
        "error_count": 0,
        "complete": True,
        "promotion_eligible": False,
        "records": [
            {
                "target_id": target_id,
                "radar": radar,
                "pulse": "lp",
            }
        ],
        "errors": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
