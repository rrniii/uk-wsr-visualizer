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

    def test_ios_app_wraps_reachable_visualizer_server(self):
        content_view = (IOS / "UKWSRVisualizer" / "ContentView.swift").read_text(encoding="utf-8")
        web_view = (IOS / "UKWSRVisualizer" / "VisualizerWebView.swift").read_text(encoding="utf-8")
        settings = (IOS / "UKWSRVisualizer" / "ServerSettings.swift").read_text(encoding="utf-8")
        plist = (IOS / "UKWSRVisualizer" / "Info.plist").read_text(encoding="utf-8")

        self.assertIn("WKWebView", web_view)
        self.assertIn("allowsBackForwardNavigationGestures", web_view)
        self.assertIn("@AppStorage(\"serverURLString\")", content_view)
        self.assertIn("UKWSRDefaultServerURL", settings)
        self.assertIn("http://130.246.214.121", plist)
        self.assertIn("NSAllowsArbitraryLoadsInWebContent", plist)

    def test_ios_readme_documents_device_install_path(self):
        readme = (IOS / "README.md").read_text(encoding="utf-8")

        self.assertIn("Signing & Capabilities", readme)
        self.assertIn("Team", readme)
        self.assertIn("Developer Mode", readme)
        self.assertIn("xcodebuild", readme)
        self.assertIn("--host 0.0.0.0 --port 8000", readme)
        self.assertIn("Do not use `127.0.0.1` from the iPhone", readme)


if __name__ == "__main__":
    unittest.main()
