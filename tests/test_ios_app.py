from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"


class IOSAppProjectTests(unittest.TestCase):
    def test_required_ios_project_files_exist(self):
        required = [
            "ios/UKWSRVisualizer.xcodeproj/project.pbxproj",
            "ios/UKWSRVisualizer.xcodeproj/xcshareddata/xcschemes/UKWSRVisualizer.xcscheme",
            "ios/UKWSRVisualizer/UKWSRVisualizerApp.swift",
            "ios/UKWSRVisualizer/ContentView.swift",
            "ios/UKWSRVisualizer/VisualizerWebView.swift",
            "ios/UKWSRVisualizer/ServerSettings.swift",
            "ios/UKWSRVisualizer/Info.plist",
            "ios/UKWSRVisualizer/Assets.xcassets/AppIcon.appiconset/Contents.json",
            "ios/README.md",
        ]
        missing = [path for path in required if not (ROOT / path).exists()]
        self.assertEqual(missing, [])

    def test_ios_app_is_native_not_a_webview_wrapper(self):
        content_view = (IOS / "UKWSRVisualizer" / "ContentView.swift").read_text(encoding="utf-8")
        core = (IOS / "UKWSRVisualizer" / "VisualizerWebView.swift").read_text(encoding="utf-8")
        plist = (IOS / "UKWSRVisualizer" / "Info.plist").read_text(encoding="utf-8")

        self.assertNotIn("WKWebView", core)
        self.assertNotIn("WebKit", core)
        self.assertNotIn("@AppStorage(\"serverURLString\")", content_view)
        self.assertNotIn("UKWSRDefaultServerURL", plist)
        self.assertNotIn("http://130.246.214.121", plist)
        self.assertIn("PPIPlotView", content_view)
        self.assertIn("Canvas", content_view)

    def test_ios_app_has_native_catalog_cache_and_rendering_core(self):
        core = (IOS / "UKWSRVisualizer" / "VisualizerWebView.swift").read_text(encoding="utf-8")
        store = (IOS / "UKWSRVisualizer" / "ServerSettings.swift").read_text(encoding="utf-8")

        self.assertIn("https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json", store)
        self.assertIn("RadarCache", store)
        self.assertIn("fetchRawVolumeCatalog", store)
        self.assertIn("downloadSelectedSource", store)
        self.assertIn("existingSourceURL", store)
        self.assertIn("expandedRawVolumeRecords", core)
        self.assertIn("selectedSourceSizeText", store)
        self.assertIn("downloadSizeMismatch", core)
        self.assertIn("NativeHDF5VolumeReader", core)
        self.assertIn("RadarVolumeReader", core)
        self.assertIn("RadarRenderer", core)
        self.assertIn("PPIFrame", core)
        self.assertIn("NoiseFloorResult", core)
        self.assertIn("DisplayConfig.forQuantity", core)
        self.assertIn("applyNoiseFloor", core)
        self.assertNotIn("SyntheticRadarVolumeReader", core)
        self.assertNotIn("catalog-derived sample data", store)

    def test_ios_readme_documents_device_install_path(self):
        readme = (IOS / "README.md").read_text(encoding="utf-8")

        self.assertIn("Signing & Capabilities", readme)
        self.assertIn("Team", readme)
        self.assertIn("Developer Mode", readme)
        self.assertIn("xcodebuild", readme)
        self.assertIn("public catalog", readme)
        self.assertIn("HDF5", readme)
        self.assertIn("native renderer", readme)


if __name__ == "__main__":
    unittest.main()
