from pathlib import Path
import os
import unittest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows"


class WindowsAppPackagingTests(unittest.TestCase):
    def test_required_windows_packaging_files_exist(self):
        required = [
            "windows/UKWSRVisualizer.Windows/UKWSRVisualizer.Windows.csproj",
            "windows/UKWSRVisualizer.Windows/Program.cs",
            "windows/pyinstaller/uk_wsr_visualizer_server.py",
            "windows/build.ps1",
            "windows/build-via-github.sh",
            "windows/README.md",
            "windows/README-Windows.txt",
            ".github/workflows/windows-beta.yml",
        ]
        missing = [path for path in required if not (ROOT / path).exists()]
        self.assertEqual(missing, [])

    def test_launcher_uses_local_app_data_and_object_store_defaults(self):
        program = (WINDOWS / "UKWSRVisualizer.Windows" / "Program.cs").read_text(encoding="utf-8")

        self.assertIn("SpecialFolder.LocalApplicationData", program)
        self.assertIn("UK_WSR_VISUALIZER_DATA_DIR", program)
        self.assertIn("UK_WSR_VISUALIZER_REMOTE_CATALOG_URL", program)
        self.assertIn("UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE", program)
        self.assertIn("https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public", program)
        self.assertIn("UK_WSR_VISUALIZER_WINDOWS_PORT", program)
        self.assertIn("--self-test", program)
        self.assertIn("CoreWebView2Environment.GetAvailableBrowserVersionString", program)
        self.assertNotIn("Process.Start(\"http://", program)

    def test_gui_entry_point_is_synchronous_sta_for_webview2(self):
        program = (WINDOWS / "UKWSRVisualizer.Windows" / "Program.cs").read_text(encoding="utf-8")

        self.assertIn("[STAThread]\n    private static int Main(string[] args)", program)
        self.assertNotIn("private static async Task<int> Main", program)
        self.assertIn("return RunSelfTest(config).GetAwaiter().GetResult();", program)

    def test_build_creates_expected_portable_zip_layout(self):
        build = (WINDOWS / "build.ps1").read_text(encoding="utf-8")

        self.assertIn("--onedir", build)
        self.assertNotIn("--onefile", build.lower())
        self.assertIn("uk-wsr-visualizer-server", build)
        self.assertIn(".[dev,video]", build)
        self.assertIn("--hidden-import imageio_ffmpeg", build)
        self.assertIn("UK WSR Visualizer.exe", build)
        self.assertIn("resources/UKWSRVisualizer.png", build)
        self.assertIn("UK WSR Visualizer Windows Beta.zip", build)
        self.assertIn("--self-contained true", build)

    def test_macos_helper_dispatches_windows_github_build(self):
        helper_path = WINDOWS / "build-via-github.sh"
        helper = helper_path.read_text(encoding="utf-8")

        self.assertTrue(helper.startswith("#!/usr/bin/env bash"))
        if os.name != "nt":
            self.assertTrue(helper_path.stat().st_mode & 0o111)
        self.assertIn("gh workflow run", helper)
        self.assertIn("gh run watch", helper)
        self.assertIn("gh run download", helper)
        self.assertIn("windows-beta.yml", helper)
        self.assertIn("uncommitted changes", helper)
        self.assertIn("PyInstaller", helper)
        self.assertIn("does not cross-compile", helper)

    def test_github_action_builds_on_windows(self):
        workflow = (ROOT / ".github" / "workflows" / "windows-beta.yml").read_text(encoding="utf-8")

        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("actions/setup-python", workflow)
        self.assertIn("actions/setup-dotnet", workflow)
        self.assertIn(".[dev,video]", workflow)
        self.assertIn("windows\\build.ps1", workflow)
        self.assertIn("UK WSR Visualizer.exe", workflow)
        self.assertIn("--self-test", workflow)
        self.assertIn("actions/upload-artifact", workflow)


if __name__ == "__main__":
    unittest.main()
