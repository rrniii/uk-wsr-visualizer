from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL_PVOL_CATALOG = "ukmo-nimrod/catalog/pvol/catalog.json"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_desktop_platforms_use_final_pvol_catalog():
    files = {
        "desktop config": "src/uk_wsr_visualizer/config.py",
        "macOS launcher": "macos/UKWSRVisualizerMac/Resources/uk-wsr-visualizer-server.zsh",
        "Windows shell": "windows/UKWSRVisualizer.Windows/Program.cs",
        "Linux Qt shell": "linux/UKWSRVisualizer.Qt/uk_wsr_visualizer_qt.py",
    }

    missing = [label for label, path in files.items() if FINAL_PVOL_CATALOG not in _read(path)]

    assert missing == []


def test_desktop_uses_signal_preserving_cleanup_defaults():
    desktop_js = _read("src/uk_wsr_visualizer/static/app.js")
    desktop_html = _read("src/uk_wsr_visualizer/static/index.html")

    assert "Remove noise, speckle and learned background clutter" in desktop_html
    assert "Advanced diagnostics and filters" in desktop_html
    assert "const DEFAULT_CLEANUP_ENABLED = true" in desktop_js
    assert "const DEFAULT_CLEANUP_MARGIN_DB = 0" in desktop_js
    assert 'const DEFAULT_QC_MODE = "signal_preserving"' in desktop_js
    assert "params.noise_floor_percentile = 10" in desktop_js
    assert "params.noise_floor_window_bins = 11" in desktop_js
    assert "params.noise_floor_texture_enabled = true" in desktop_js
    assert "params.qc_companion_enabled = true" in desktop_js
    assert "params.qc_static_clutter_enabled = true" in desktop_js
    assert "params.qc_background_model_enabled = true" in desktop_js
    assert "params.qc_background_dbzh_excess_max_db = 12" in desktop_js
    assert "params.qc_background_evidence_score_threshold = 1" in desktop_js


def test_desktop_export_and_recent_selection_capabilities_are_available():
    desktop_html = _read("src/uk_wsr_visualizer/static/index.html")
    desktop_js = _read("src/uk_wsr_visualizer/static/app.js")

    assert "Screenshot: as displayed" in desktop_html
    assert "Polar PPI PNG" in desktop_html
    assert "Polar PPI MP4" in desktop_html
    assert "Georeferenced map overlay" in desktop_html
    assert "Georeferenced GeoTIFF" in desktop_html
    assert "coordinateModeForExport" in desktop_js
    assert "/api/recent-selections" in desktop_js
