from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "macos" / "UK WSR Visualizer.app"


class MacOSAppBundleTests(unittest.TestCase):
    def test_native_window_helper_is_bundled(self):
        helper = APP / "Contents" / "MacOS" / "UKWSRNativeWindow"
        source = APP / "Contents" / "Resources" / "UKWSRNativeWindow.m"
        logo = APP / "Contents" / "Resources" / "UKWSRVisualizer.png"

        self.assertTrue(helper.exists())
        self.assertTrue(helper.stat().st_mode & 0o111)
        self.assertTrue(source.exists())
        self.assertTrue(logo.exists())

    def test_launcher_uses_native_window_not_browser(self):
        launcher = APP / "Contents" / "MacOS" / "uk-wsr-visualizer-mac"
        text = launcher.read_text(encoding="utf-8")

        self.assertIn("NATIVE_WINDOW", text)
        self.assertIn("WINDOW_URL", text)
        self.assertIn("show_native_window", text)
        self.assertIn('"$NATIVE_WINDOW" "$WINDOW_URL" "$LOGO_FILE" "$LOG_FILE"', text)
        self.assertNotIn('/usr/bin/open "$BASE_URL"', text)


if __name__ == "__main__":
    unittest.main()
