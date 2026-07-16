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


def test_desktop_defaults_to_raw_data_with_opt_in_cleanup_modes():
    desktop_js = _read("src/uk_wsr_visualizer/static/app.js")
    desktop_html = _read("src/uk_wsr_visualizer/static/index.html")

    assert "Raw decoded data" in desktop_html
    assert "Basic range-dependent noise removal" in desktop_html
    assert "Experimental: noise and clutter cleanup" in desktop_html
    assert "Advanced diagnostics and filters" in desktop_html
    assert 'const DEFAULT_CLEANUP_MODE = "raw"' in desktop_js
    assert "const DEFAULT_CLEANUP_MARGIN_DB = 3" in desktop_js
    assert 'const DEFAULT_QC_MODE = "signal_preserving"' in desktop_js
    assert "cleanupMode === \"basic_noise\"" in desktop_js
    assert "cleanupMode === \"experimental_clutter\"" in desktop_js


def test_desktop_export_and_recent_selection_capabilities_are_available():
    desktop_html = _read("src/uk_wsr_visualizer/static/index.html")
    desktop_js = _read("src/uk_wsr_visualizer/static/app.js")

    assert "Save figure PNG: map view, legend and metadata" in desktop_html
    assert "Advanced: polar PPI PNG (range-azimuth) + manifest" in desktop_html
    assert "Save map animation MP4 + manifest" in desktop_html
    assert "Save georeferenced map overlay KMZ + manifest" in desktop_html
    assert "Save georeferenced GeoTIFF + manifest" in desktop_html
    assert "coordinateModeForExport" in desktop_js
    assert "/api/recent-selections" in desktop_js
