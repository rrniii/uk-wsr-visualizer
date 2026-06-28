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
            "ios/UKWSRVisualizer/UKHDF5Reader.c",
            "ios/UKWSRVisualizer/UKHDF5Reader.h",
            "ios/UKWSRVisualizer/UKWSRVisualizer-Bridging-Header.h",
            "ios/UKWSRVisualizer/Info.plist",
            "ios/UKWSRVisualizer/Assets.xcassets/AppIcon.appiconset/Contents.json",
            "ios/ThirdParty/HDF5/include/hdf5.h",
            "ios/ThirdParty/HDF5/lib/iphoneos/libhdf5.a",
            "ios/ThirdParty/HDF5/lib/iphonesimulator/libhdf5.a",
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
        content_view = (IOS / "UKWSRVisualizer" / "ContentView.swift").read_text(encoding="utf-8")
        core = (IOS / "UKWSRVisualizer" / "VisualizerWebView.swift").read_text(encoding="utf-8")
        store = (IOS / "UKWSRVisualizer" / "ServerSettings.swift").read_text(encoding="utf-8")

        self.assertIn("https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json", store)
        self.assertIn("RadarCache", store)
        self.assertIn("fetchRawVolumeCatalog", store)
        self.assertIn("downloadSelectedSource", store)
        self.assertIn("existingSourceURL", store)
        self.assertIn("cachedOrDownloadSource", store)
        self.assertIn("renderRequestID", store)
        self.assertIn("prune(preserving", store)
        self.assertIn("expandedRawVolumeRecords", core)
        self.assertIn("selectedSourceSizeText", store)
        self.assertIn("downloadSizeMismatch", core)
        self.assertIn("NativeHDF5VolumeReader", core)
        self.assertIn("UKHDF5ReadODIMField", core)
        self.assertIn("hdf5ReadFailed", core)
        self.assertIn("RadarVolumeReader", core)
        self.assertIn("RadarRenderer", core)
        self.assertIn("PPIFrame", core)
        self.assertIn("NoiseFloorResult", core)
        self.assertIn("DisplayConfig.forQuantity", core)
        self.assertIn("applyNoiseFloor", core)
        self.assertNotIn("hdf5RuntimeMissing", core)
        self.assertNotIn("runtime is not linked", core)
        self.assertNotIn("SyntheticRadarVolumeReader", core)
        self.assertNotIn("catalog-derived sample data", store)
        self.assertNotIn("Cache a scan to render", content_view)
        self.assertNotIn("Cache Scan", content_view)
        self.assertIn("Radar Controls", content_view)
        self.assertIn("Clear Raw Cache", content_view)
        self.assertIn("Display min", content_view)
        self.assertIn("Remove range-dependent noise floor", content_view)
        self.assertIn("CatalogSearchView", content_view)
        self.assertIn(".searchable", content_view)
        self.assertIn("Catalog Search", content_view)
        self.assertIn("First day", content_view)
        self.assertIn("Latest day", content_view)
        self.assertIn("CatalogSearchCriteria", store)
        self.assertIn("filteredCatalogItems", store)
        self.assertIn("catalogRadarOptions", store)
        self.assertIn("catalogPulseOptions", store)
        self.assertIn("selectCatalogItem", store)
        self.assertIn("SourceDiagnosticRow", store)
        self.assertIn("selectedSourceDiagnosticRows", store)
        self.assertIn("selectedSourceURLString", store)
        self.assertIn("selectedTimePositionText", store)
        self.assertIn("stepTime", store)
        self.assertIn("Auto by variable", core)
        self.assertIn("static func rgba", core)
        self.assertIn("MetadataSection", content_view)
        self.assertIn("Copy Source URL", content_view)
        self.assertIn("ExportSection", content_view)
        self.assertIn("ShareLink", content_view)
        self.assertIn("PPIImageExporter", content_view)
        self.assertIn("Create PNG", content_view)
        self.assertIn("chevron.left", content_view)
        self.assertIn("chevron.right", content_view)

        bridge = (IOS / "UKWSRVisualizer" / "UKHDF5Reader.c").read_text(encoding="utf-8")
        self.assertIn("H5Fopen", bridge)
        self.assertIn("H5Dread", bridge)
        self.assertIn("gain", bridge)
        self.assertIn("undetect", bridge)
        self.assertIn("nodata", bridge)

    def test_ios_readme_documents_device_install_path(self):
        readme = (IOS / "README.md").read_text(encoding="utf-8")

        self.assertIn("Signing & Capabilities", readme)
        self.assertIn("Team", readme)
        self.assertIn("Developer Mode", readme)
        self.assertIn("xcodebuild", readme)
        self.assertIn("public catalog", readme)
        self.assertIn("HDF5", readme)
        self.assertIn("DEFLATE/zlib", readme)
        self.assertIn("native renderer", readme)
        self.assertIn("search/filter radar days", readme)
        self.assertIn("source metadata", readme)
        self.assertIn("PNG sharing", readme)
        self.assertIn("downloads and caches", readme)
        self.assertIn("Clear Raw Cache", readme)


if __name__ == "__main__":
    unittest.main()
