from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"


class IOSAppProjectTests(unittest.TestCase):
    def test_required_ios_project_files_exist(self):
        required = [
            "ios/UKWSRVisualizer.xcodeproj/project.pbxproj",
            "ios/UKWSRVisualizer.xcodeproj/xcshareddata/xcschemes/UKWSRVisualizer.xcscheme",
            "ios/UKWSRVisualizer.xcodeproj/xcshareddata/xcschemes/UKWSRVisualizerUITests.xcscheme",
            "ios/UKWSRVisualizer/UKWSRVisualizerApp.swift",
            "ios/UKWSRVisualizer/ContentView.swift",
            "ios/UKWSRVisualizer/LaunchScreen.storyboard",
            "ios/UKWSRVisualizer/VisualizerWebView.swift",
            "ios/UKWSRVisualizer/ServerSettings.swift",
            "ios/UKWSRVisualizer/UKHDF5Reader.c",
            "ios/UKWSRVisualizer/UKHDF5Reader.h",
            "ios/UKWSRVisualizer/UKWSRVisualizer-Bridging-Header.h",
            "ios/UKWSRVisualizer/Info.plist",
            "ios/UKWSRVisualizer/Assets.xcassets/AppIcon.appiconset/Contents.json",
            "ios/UKWSRVisualizer/Assets.xcassets/LaunchIcon.imageset/Contents.json",
            "ios/UKWSRVisualizer/Assets.xcassets/LaunchIcon.imageset/Icon-1024.png",
            "ios/UKWSRVisualizer/Assets.xcassets/LaunchBackground.colorset/Contents.json",
            "ios/UKWSRVisualizerTests/CatalogServiceTests.swift",
            "ios/UKWSRVisualizerUITests/UKWSRVisualizerUITests.swift",
            "ios/ThirdParty/HDF5/include/hdf5.h",
            "ios/ThirdParty/HDF5/lib/iphoneos/libhdf5.a",
            "ios/ThirdParty/HDF5/lib/iphonesimulator/libhdf5.a",
            "ios/README.md",
            "ios/ACCEPTANCE_CHECKLIST.md",
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
        self.assertIn("NSLocationWhenInUseUsageDescription", plist)
        self.assertIn("nearest radar", plist)
        self.assertIn("UILaunchStoryboardName", plist)
        self.assertIn("LaunchScreen", plist)
        self.assertNotIn("UILaunchScreen", plist)
        self.assertIn("PPIPlotView", content_view)
        self.assertIn("Canvas", content_view)
        self.assertIn("LightweightPPIPlotView", content_view)
        self.assertIn("AppRuntime.isUITesting", content_view)
        self.assertIn("LaunchLoadingView", content_view)
        self.assertIn("Image(\"LaunchIcon\")", content_view)
        self.assertIn("Color(\"LaunchBackground\")", content_view)
        self.assertIn("LaunchLoadingView", content_view)
        self.assertIn("accessibilityIdentifier(\"LaunchLoadingView\")", content_view)
        self.assertIn("accessibilityIdentifier(\"StatusStrip\")", content_view)
        self.assertIn("accessibilityIdentifier(\"PPIPlotView\")", content_view)

        storyboard = (IOS / "UKWSRVisualizer" / "LaunchScreen.storyboard").read_text(encoding="utf-8")
        self.assertIn("launchScreen=\"YES\"", storyboard)
        self.assertIn("contentMode=\"scaleAspectFit\"", storyboard)
        self.assertIn("image=\"LaunchIcon\"", storyboard)
        self.assertIn("name=\"LaunchBackground\"", storyboard)
        self.assertIn("multiplier=\"0.78\"", storyboard)

        launch_icon = json.loads(
            (IOS / "UKWSRVisualizer" / "Assets.xcassets" / "LaunchIcon.imageset" / "Contents.json").read_text(encoding="utf-8")
        )
        launch_icon_image = next(image for image in launch_icon["images"] if image.get("filename") == "Icon-1024.png")
        self.assertEqual(launch_icon_image["scale"], "3x")

    def test_ios_app_has_native_catalog_cache_and_rendering_core(self):
        content_view = (IOS / "UKWSRVisualizer" / "ContentView.swift").read_text(encoding="utf-8")
        core = (IOS / "UKWSRVisualizer" / "VisualizerWebView.swift").read_text(encoding="utf-8")
        store = (IOS / "UKWSRVisualizer" / "ServerSettings.swift").read_text(encoding="utf-8")

        self.assertIn("https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json", store)
        self.assertIn("RadarCache", store)
        self.assertIn("CoreLocation", store)
        self.assertIn("DeviceLocationProvider", store)
        self.assertIn("StaticDeviceLocationProvider", store)
        self.assertIn("requestCurrentLocation", store)
        self.assertIn("-UKWSRUITesting", store)
        self.assertIn("uiTestFixtures", store)
        self.assertIn("autoRenderEnabled", store)
        self.assertIn("applyLaunchDefaultSelectionIfNeeded", store)
        self.assertIn("hasCompletedInitialLoad", store)
        self.assertIn("shouldShowLaunchLoadingScreen", store)
        self.assertIn("nearestRadar", store)
        self.assertIn("latestCatalogItem", store)
        self.assertIn("preferLatestTime", store)
        self.assertIn("spatialLocation", store)
        self.assertIn("fetchCoverageDays", store)
        self.assertIn("fetchRawVolumeCatalog", store)
        self.assertIn("fetchLatestPVOLDays", store)
        self.assertIn("objectStoreURL", store)
        self.assertIn("loadCoverageForCurrentSearch", store)
        self.assertIn("loadedCoverageYears", store)
        self.assertIn("downloadSelectedSource", store)
        self.assertIn("existingSourceURL", store)
        self.assertIn("cachedOrDownloadSource", store)
        self.assertIn("renderRequestID", store)
        self.assertIn("prune(preserving", store)
        self.assertIn("expandedRawVolumeRecords", core)
        self.assertIn("selectedSourceSizeText", store)
        self.assertIn("downloadSizeMismatch", core)
        self.assertIn("NativeHDF5VolumeReader", core)
        self.assertIn("CatalogSpatialMetadata", core)
        self.assertIn("CatalogRootAttributes", core)
        self.assertIn("InterimPVOLRootCatalog", core)
        self.assertIn("InterimPVOLCoverage", core)
        self.assertIn("InterimPVOLDayCatalog", core)
        self.assertIn("InterimPVOLFile", core)
        self.assertIn("coverage_keys", core)
        self.assertIn("spatial", core)
        self.assertIn("spatialMetadata: radar.spatial", core)
        self.assertIn("radar_spatial_source", core)
        self.assertIn("height_m", core)
        self.assertIn("object_url", core)
        self.assertIn("size_bytes", core)
        self.assertIn("uk_wsr:spatial", core)
        self.assertIn("spatialMetadata", core)
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
        self.assertIn("loadCoverageForCurrentSearch", content_view)
        self.assertIn("catalogCoverageStatusText", content_view)
        self.assertIn("accessibilityIdentifier(\"CatalogItemButton\")", content_view)
        self.assertIn("accessibilityIdentifier(\"CatalogSearchList\")", content_view)
        self.assertIn("accessibilityIdentifier(\"CatalogSearchDoneButton\")", content_view)
        self.assertIn("First day", content_view)
        self.assertIn("Latest day", content_view)
        self.assertIn("CatalogSearchCriteria", store)
        self.assertIn("filteredCatalogItems", store)
        self.assertIn("CatalogDataLoader", store)
        self.assertIn("catalogRadarOptions", store)
        self.assertIn("catalogPulseOptions", store)
        self.assertIn("catalogCoverageStatusText", store)
        self.assertIn("selectCatalogItem", store)
        self.assertIn("prepareForSelectionChange", store)
        self.assertIn("selectedFieldAvailabilityText", store)
        self.assertIn("requestID == renderRequestID", store)
        self.assertIn("SourceDiagnosticRow", store)
        self.assertIn("selectedSourceDiagnosticRows", store)
        self.assertIn("selectedSourceURLString", store)
        self.assertIn("selectedTimePositionText", store)
        self.assertIn("stepTime", store)
        self.assertIn("Radar site", store)
        self.assertIn("Catalog unavailable", store)
        self.assertIn("Coverage unavailable", store)
        self.assertIn("Day scan catalog unavailable", store)
        self.assertIn("Source download failed", store)
        self.assertIn("HDF5 decode failed", store)
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
        self.assertIn("No pulses", content_view)
        self.assertIn("No times", content_view)
        self.assertIn("No variables", content_view)

        self.assertIn("rawVolumeCatalogKey", core)
        self.assertIn("sourceType", core)
        self.assertIn("objectKey", core)
        self.assertIn("No downloadable HDF5 source URL", core)

        bridge = (IOS / "UKWSRVisualizer" / "UKHDF5Reader.c").read_text(encoding="utf-8")
        self.assertIn("H5Fopen", bridge)
        self.assertIn("H5Dread", bridge)
        self.assertIn("gain", bridge)
        self.assertIn("undetect", bridge)
        self.assertIn("nodata", bridge)

    def test_ios_readme_documents_device_install_path(self):
        readme = (IOS / "README.md").read_text(encoding="utf-8")
        checklist = (IOS / "ACCEPTANCE_CHECKLIST.md").read_text(encoding="utf-8")

        self.assertIn("Signing & Capabilities", readme)
        self.assertIn("Team", readme)
        self.assertIn("Developer Mode", readme)
        self.assertIn("xcodebuild", readme)
        self.assertIn("public catalog", readme)
        self.assertIn("interim uploaded-only catalog", readme)
        self.assertIn("ukmo-nimrod/catalog/pvol/catalog.json", readme)
        self.assertIn("spatial.latitude", readme)
        self.assertIn("nearest-radar", readme)
        self.assertIn("coverage.json", readme)
        self.assertIn("lazily", readme)
        self.assertIn("object_url", readme)
        self.assertIn("HDF5", readme)
        self.assertIn("DEFLATE/zlib", readme)
        self.assertIn("native renderer", readme)
        self.assertIn("search/filter radar days", readme)
        self.assertIn("phone location", readme)
        self.assertIn("latest day from the", readme)
        self.assertIn("nearest available radar", readme)
        self.assertIn("source metadata", readme)
        self.assertIn("PNG sharing", readme)
        self.assertIn("downloads and caches", readme)
        self.assertIn("Clear Raw Cache", readme)
        self.assertIn("ACCEPTANCE_CHECKLIST.md", readme)
        self.assertIn("missing source URLs", readme)
        self.assertIn("keychain prompt", readme)
        self.assertIn("codesign", readme)
        self.assertIn("UKWSRVisualizerTests", readme)
        self.assertIn("UKWSRVisualizerUITests", readme)
        self.assertIn("fixture JSON", readme)

        self.assertIn("Overman", checklist)
        self.assertIn("build", checklist)
        self.assertIn("14", checklist)
        self.assertIn("Swift unit tests", checklist)
        self.assertIn("UI smoke tests", checklist)
        self.assertIn("launch screen shows the full-screen UK WSR icon", checklist)
        self.assertIn("first in-app screen keeps the full-screen UK WSR icon", checklist)
        self.assertIn("radars[].spatial", checklist)
        self.assertIn("loaded lazily", checklist)
        self.assertIn("No pulses", checklist)
        self.assertIn("No times", checklist)
        self.assertIn("No variables", checklist)
        self.assertIn("Selecting Castor after a Chenies error", checklist)
        self.assertIn("Missing source URLs are reported as data availability issues", checklist)
        self.assertIn("Create PNG", checklist)
        self.assertIn("Share PNG", checklist)

    def test_ios_xcode_project_has_unit_test_target_and_beta_build_number(self):
        project = (IOS / "UKWSRVisualizer.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
        scheme = (
            IOS
            / "UKWSRVisualizer.xcodeproj"
            / "xcshareddata"
            / "xcschemes"
            / "UKWSRVisualizer.xcscheme"
        ).read_text(encoding="utf-8")
        ui_scheme = (
            IOS
            / "UKWSRVisualizer.xcodeproj"
            / "xcshareddata"
            / "xcschemes"
            / "UKWSRVisualizerUITests.xcscheme"
        ).read_text(encoding="utf-8")
        install = (IOS / "install_to_device.sh").read_text(encoding="utf-8")
        tests = (IOS / "UKWSRVisualizerTests" / "CatalogServiceTests.swift").read_text(encoding="utf-8")
        ui_tests = (IOS / "UKWSRVisualizerUITests" / "UKWSRVisualizerUITests.swift").read_text(encoding="utf-8")

        self.assertIn("UKWSRVisualizerTests", project)
        self.assertIn("UKWSRVisualizerUITests", project)
        self.assertIn("com.apple.product-type.bundle.unit-test", project)
        self.assertIn("com.apple.product-type.bundle.ui-testing", project)
        self.assertIn("CatalogServiceTests.swift in Sources", project)
        self.assertIn("UKWSRVisualizerUITests.swift in Sources", project)
        self.assertIn("TEST_HOST", project)
        self.assertIn("TEST_TARGET_NAME = UKWSRVisualizer", project)
        self.assertIn("CURRENT_PROJECT_VERSION = 14;", project)
        self.assertNotIn("CURRENT_PROJECT_VERSION = 13;", project)
        self.assertIn("UKWSRVisualizerTests.xctest", scheme)
        self.assertIn("<Testables>", scheme)
        self.assertIn("UKWSRVisualizerUITests.xctest", ui_scheme)
        self.assertIn("UKWSRVisualizer.app", ui_scheme)
        self.assertIn("<Testables>", ui_scheme)
        self.assertIn("--bundle-id \"$BUNDLE_ID\"", install)
        self.assertIn("--columns '*'", install)
        self.assertIn("Built app metadata", install)

        self.assertIn("FixtureResponses", tests)
        self.assertIn("testInterimPVOLRootDecodesSpatialAndLoadsOnlyLatestCoverageAtStartup", tests)
        self.assertIn("testFetchCoverageDaysLoadsRequestedYearAndCarriesRootSpatialMetadata", tests)
        self.assertIn("testDayCatalogHydratesRawVolumeFilesWithObjectURLsAndSizes", tests)
        self.assertIn("testLaunchDefaultSelectsNearestRadarFromSpatialMetadata", tests)
        self.assertIn("testSelectingNewItemClearsStaleWarningImmediately", tests)
        self.assertIn("testLaunchShellAndCatalogSearchSmokeFlow", ui_tests)
        self.assertIn("-UKWSRUITesting", ui_tests)
        self.assertIn("Location Permission", ui_tests)
        self.assertIn("CatalogItemButton", ui_tests)
        self.assertIn("CatalogSearchList", ui_tests)


if __name__ == "__main__":
    unittest.main()
