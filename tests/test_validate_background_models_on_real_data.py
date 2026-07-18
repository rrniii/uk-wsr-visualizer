import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


_MODULE_PATH = Path(__file__).parents[1] / "tools" / "validate_background_models_on_real_data.py"
_SPEC = importlib.util.spec_from_file_location("validate_background_models_on_real_data", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_stratified_jobs = _MODULE._stratified_jobs
_verify_frozen_policy = _MODULE._verify_frozen_policy


def _job(radar: str, target_id: str, date: str, time: str):
    return SimpleNamespace(
        target=SimpleNamespace(radar=radar, target_id=target_id),
        sweep=SimpleNamespace(date=date, time=time),
    )


def test_stratified_jobs_rotates_across_radars_before_repeating() -> None:
    jobs = [
        _job("alpha", "alpha-a", "20250101", "1200"),
        _job("alpha", "alpha-b", "20250401", "0000"),
        _job("bravo", "bravo-a", "20250701", "1200"),
        _job("bravo", "bravo-b", "20251001", "0000"),
        _job("charlie", "charlie-a", "20250101", "1200"),
        _job("charlie", "charlie-b", "20250401", "0000"),
    ]

    selected = _stratified_jobs(jobs, 4)

    assert [job.target.radar for job in selected[:3]] == [
        "alpha",
        "bravo",
        "charlie",
    ]
    assert {job.target.radar for job in selected} == {
        "alpha",
        "bravo",
        "charlie",
    }
    assert len({job.target.target_id for job in selected}) == 4


def test_holdout_policy_allows_only_blinded_review_targets(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "status": "frozen",
                "configuration_sha256": "a" * 64,
                "holdout_scoring_target_count": 1,
                "targets": [
                    {
                        "target_id": "allowed",
                        "state": "requires_blinded_review",
                    },
                    {"target_id": "blocked", "state": "quarantined"},
                ],
            }
        ),
        encoding="utf-8",
    )

    digest, allowed = _verify_frozen_policy(
        policy_path,
        split="holdout",
        configuration_sha256="a" * 64,
    )

    assert digest is not None
    assert allowed == frozenset({"allowed"})


def test_holdout_policy_rejects_mismatched_target_count(tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "status": "frozen",
                "configuration_sha256": "a" * 64,
                "holdout_scoring_target_count": 2,
                "targets": [
                    {
                        "target_id": "allowed",
                        "state": "requires_blinded_review",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="holdout target count"):
        _verify_frozen_policy(
            policy_path,
            split="holdout",
            configuration_sha256="a" * 64,
        )
