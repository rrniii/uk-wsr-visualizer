from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "macos" / "UK WSR Visualizer.app"


class MacOSAppBundleTests(unittest.TestCase):
    def test_native_window_helper_is_bundled(self):
        helper = APP / "Contents" / "MacOS" / "UKWSRNativeWindow"
        source = APP / "Contents" / "Resources" / "UKWSRNativeWindow.m"
        logo = APP / "Contents" / "Resources" / "UKWSRVisualizer.png"
        server_launcher = APP / "Contents" / "Resources" / "uk-wsr-visualizer-server.zsh"

        self.assertTrue(helper.exists())
        self.assertTrue(helper.stat().st_mode & 0o111)
        self.assertTrue(source.exists())
        self.assertTrue(logo.exists())
        self.assertTrue(server_launcher.exists())
        self.assertTrue(server_launcher.stat().st_mode & 0o111)

    def test_bundle_launches_native_window_directly(self):
        info = (APP / "Contents" / "Info.plist").read_text(encoding="utf-8")
        launcher = APP / "Contents" / "MacOS" / "uk-wsr-visualizer-mac"
        helper_source = (APP / "Contents" / "Resources" / "UKWSRNativeWindow.m").read_text(encoding="utf-8")

        self.assertIn("<string>UKWSRNativeWindow</string>", info)
        self.assertTrue(launcher.exists())
        self.assertIn("startServerTaskIfNeeded", helper_source)
        self.assertIn("uk-wsr-visualizer-server", helper_source)
        self.assertNotIn('/usr/bin/open "$BASE_URL"', launcher.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
