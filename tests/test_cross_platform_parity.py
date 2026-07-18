from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINAL_PVOL_CATALOG = "ukmo-nimrod/catalog/pvol/catalog.json"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_mac_windows_ios_all_use_final_pvol_catalog():
    files = {
        "desktop config": "src/uk_wsr_visualizer/config.py",
        "macOS launcher": "macos/UKWSRVisualizerMac/Resources/uk-wsr-visualizer-server.zsh",
        "Windows shell": "windows/UKWSRVisualizer.Windows/Program.cs",
        "iPhone settings": "ios/UKWSRVisualizer/ServerSettings.swift",
    }

    missing = [label for label, path in files.items() if FINAL_PVOL_CATALOG not in _read(path)]

    assert missing == []


def test_desktop_and_ios_share_signal_preserving_cleanup_defaults():
    desktop_js = _read("src/uk_wsr_visualizer/static/app.js")
    desktop_html = _read("src/uk_wsr_visualizer/static/index.html")
    ios_core = _read("ios/UKWSRVisualizer/VisualizerWebView.swift")
    ios_view = _read("ios/UKWSRVisualizer/ContentView.swift")

    assert "Remove noise, speckle and learned background clutter" in desktop_html
    assert "Advanced diagnostics and filters" in desktop_html
    assert "const DEFAULT_CLEANUP_ENABLED = true" in desktop_js
    assert "const DEFAULT_CLEANUP_MARGIN_DB = 0" in desktop_js
    assert 'const DEFAULT_QC_MODE = "signal_preserving"' in desktop_js
    assert "params.noise_floor_percentile = 10" in desktop_js
    assert "params.noise_floor_window_bins = 11" in desktop_js
    assert "params.qc_receiver_noise_enabled = true" in desktop_js
    assert "params.qc_receiver_noise_margin_db = 0.25" in desktop_js
    assert "params.qc_receiver_noise_min_bad_moments = 3" in desktop_js
    assert "params.qc_ci_enabled = true" in desktop_js
    assert "params.noise_floor_texture_enabled = true" not in desktop_js
    assert "params.qc_companion_enabled = true" not in desktop_js
    assert "params.qc_static_clutter_enabled = true" not in desktop_js
    assert "params.qc_background_model_enabled = true" in desktop_js
    assert "params.qc_background_persistent_frequency_min = 0.95" in desktop_js
    assert "params.qc_background_dbzh_excess_max_db = 3" in desktop_js
    assert "params.qc_background_evidence_score_threshold = 3" in desktop_js
    assert "params.qc_background_require_training_diversity = true" in desktop_js
    assert "params.qc_background_min_training_dates = 7" in desktop_js
    assert "params.qc_background_min_training_span_days = 14" in desktop_js

    assert "Remove noise/clutter" in ios_view
    assert "NoiseCleanupAdvancedSheet" in ios_view
    assert "case normal" in ios_view
    assert "noiseFloorEnabled: Bool = true" in ios_core
    assert "noiseFloorMarginDb: Double = 0" in ios_core
    assert "noiseFloorPercentile: Double = 10" in ios_core
    assert "noiseFloorWindowBins: Int = 11" in ios_core
    assert "receiverNoiseEnabled: Bool = true" in ios_core
    assert "receiverNoiseMarginDb: Double = 0.25" in ios_core
    assert "receiverNoiseMinBadMoments: Int = 3" in ios_core
    assert "ciEvidenceEnabled: Bool = true" in ios_core
    assert "textureCleanupEnabled: Bool = false" in ios_core
    assert "companionQcEnabled: Bool = false" in ios_core
    assert "staticClutterEnabled: Bool = false" in ios_core
    assert "staticClutterDbzMin: Double = 5" in ios_core
    assert "staticClutterVradAbsMax: Double = 1" in ios_core
    assert "staticClutterMinNeighbors: Int = 3" in ios_core
    # The native renderer currently ships the qualified-model registry but keeps
    # it fail-open until the temporal-context validation runs on device.
    assert "backgroundModelEnabled: Bool = false" in ios_core
    assert "backgroundPersistentFrequencyMin: Double = 0.95" in ios_core
    assert "backgroundDbzhExcessMaxDb: Double = 3" in ios_core
    assert "backgroundEvidenceScoreThreshold: Int = 3" in ios_core
    assert "backgroundRequireTrainingDiversity: Bool = true" in ios_core
    assert "filters.receiverNoiseEnabled = self != .off" in ios_view
    assert "filters.textureCleanupEnabled = false" in ios_view
    assert "filters.companionQcEnabled = false" in ios_view
    assert "filters.staticClutterEnabled = false" in ios_view
    assert "filters.backgroundModelEnabled = false" in ios_view
    assert "String(filters.textureCleanupEnabled)" in ios_view
    assert "String(filters.companionQcEnabled)" in ios_view


def test_export_and_recent_selection_capabilities_are_platform_appropriate():
    desktop_html = _read("src/uk_wsr_visualizer/static/index.html")
    desktop_js = _read("src/uk_wsr_visualizer/static/app.js")
    ios_view = _read("ios/UKWSRVisualizer/ContentView.swift")
    ios_store = _read("ios/UKWSRVisualizer/ServerSettings.swift")

    assert "Screenshot: as displayed" in desktop_html
    assert "Polar PPI PNG" in desktop_html
    assert "Polar PPI MP4" in desktop_html
    assert "Georeferenced map overlay" in desktop_html
    assert "Georeferenced GeoTIFF" in desktop_html
    assert "coordinateModeForExport" in desktop_js
    assert "/api/recent-selections" in desktop_js

    assert "Create PNG" in ios_view
    assert "Share PNG" in ios_view
    assert "Create MP4" in ios_view
    assert "Share MP4" in ios_view
    assert "AVAssetWriter" in ios_view
    assert "UserDefaultsRecentSelectionStore" in ios_store
    assert "MapKit" in ios_store


def test_ios_rejects_unavailable_field_selections():
    store = _read("ios/UKWSRVisualizer/ServerSettings.swift")

    assert 'rejectUnavailableSelection(kind: "pulse", value: pulse)' in store
    assert 'rejectUnavailableSelection(kind: "time", value: time)' in store
    assert 'rejectUnavailableSelection(kind: "variable", value: quantity)' in store
    assert 'rejectUnavailableSelection(kind: "elevation", value: dataset)' in store
    assert 'warningMessage = "Unavailable \\(kind): \\(value)."' in store
