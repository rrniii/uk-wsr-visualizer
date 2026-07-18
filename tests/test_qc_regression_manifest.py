from __future__ import annotations

import json
from pathlib import Path


MANIFEST = (
    Path(__file__).parents[1]
    / "validation"
    / "qc_regression_cases_v1"
    / "manifest.json"
)


def test_real_qc_regression_manifest_is_complete_and_immutable() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "uk_wsr_qc_regression_manifest"
    assert manifest["case_count"] == len(manifest["cases"]) == 2
    assert {case["pulse"] for case in manifest["cases"]} == {"lp", "sp"}

    for case in manifest["cases"]:
        assert case["review_status"] == "blinded expert review required"
        assert [item["role"] for item in case["files"]] == [
            "previous",
            "current",
            "next",
        ]
        assert case["current_time"] == case["files"][1]["time"]
        assert all(len(item["sha256"]) == 64 for item in case["files"])
        assert all(item["size_bytes"] > 0 for item in case["files"])
        assert all(
            item["url"].endswith(item["filename"])
            for item in case["files"]
        )
