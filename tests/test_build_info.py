import json

import pytest

from uk_wsr_visualizer import build_info, citations


def test_packaged_identity_survives_without_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, "__file__", str(tmp_path / "build_info.py"))
    payload = {"schema": "uk-wsr-build-v1", "version": "0.2.4", "git_commit": "a" * 40, "source_dirty": True, "qc_commit": "b" * 40}
    (tmp_path / "build-info.json").write_text(json.dumps(payload))
    monkeypatch.setenv("GITHUB_SHA", "unrelated-parent-checkout")
    assert citations._git_commit() == payload["git_commit"]
    assert citations.citation_payload()["software"]["build"] == payload


def test_source_checkout_needs_no_packaged_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, "__file__", str(tmp_path / "build_info.py"))
    assert build_info.packaged_build_info() == {}
    monkeypatch.setenv("UK_WSR_VISUALIZER_GIT_SHA", "c" * 40)
    assert citations._git_commit() == "c" * 40


def test_bad_manifest_is_not_silently_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, "__file__", str(tmp_path / "build_info.py"))
    (tmp_path / "build-info.json").write_text('{"schema": "unrelated"}')
    with pytest.raises(ValueError, match="Invalid packaged"):
        build_info.packaged_build_info()
