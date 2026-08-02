from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_visualizer_does_not_own_qc_research_modules():
    package = ROOT / "src" / "uk_wsr_visualizer"
    forbidden = (
        "background_model.py",
        "background_training.py",
        "background_validation_pipeline.py",
        "field_audit.py",
        "qc.py",
        "qc_benchmark.py",
        "qc_evidence.py",
        "receiver_noise_model.py",
        "temporal_corpus.py",
    )

    assert all(not (package / name).exists() for name in forbidden)
    assert not (package / "models" / "background").exists()


def test_visualizer_declares_standalone_qc_runtime_dependency():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    geospatial = (ROOT / "src" / "uk_wsr_visualizer" / "geospatial.py").read_text(
        encoding="utf-8"
    )

    assert '"uk-wsr-qc>=0.1.0"' in pyproject
    assert "from uk_wsr_qc.qc import" in geospatial


def test_visualizer_does_not_contain_a_generated_macos_package():
    assert not (ROOT / "macos" / "UK WSR Visualizer.app").exists()


def test_release_workflows_pin_and_install_the_standalone_qc_runtime():
    expected_ref = "d1764857d462e908bf6444f087ed1d87d3b4adec"
    workflows = (
        "macos-beta.yml",
        "windows-beta.yml",
        "linux-beta.yml",
        "docs.yml",
    )

    for filename in workflows:
        text = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
        assert "repository: rrniii/uk-wsr-qc" in text
        assert f"ref: {expected_ref}" in text
        assert "ssh-key: ${{ secrets.QC_REPO_DEPLOY_KEY }}" in text
        assert "pip install" in text
        assert "./uk-wsr-qc" in text
