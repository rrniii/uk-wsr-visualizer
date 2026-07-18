from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.download_temporal_context_corpus import _verify_holdout_gate


def test_holdout_gate_rejects_unfrozen_or_empty_policy(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "status": "frozen",
                "holdout_scoring_target_count": 0,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="does not authorise"):
        _verify_holdout_gate(
            ("holdout",),
            open_holdout=True,
            frozen_policy=policy,
        )


def test_holdout_gate_accepts_explicit_authorised_policy(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "status": "frozen",
                "holdout_scoring_target_count": 187,
            }
        ),
        encoding="utf-8",
    )

    _verify_holdout_gate(
        ("holdout",),
        open_holdout=True,
        frozen_policy=policy,
    )
