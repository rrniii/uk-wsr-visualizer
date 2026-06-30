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


class MacOSXcodeProjectTests(unittest.TestCase):
    def test_xcode_workspace_and_project_are_present(self):
        workspace = ROOT / "apple" / "UKWSRVisualizer.xcworkspace" / "contents.xcworkspacedata"
        project = ROOT / "macos" / "UKWSRVisualizerMac.xcodeproj" / "project.pbxproj"
        scheme = ROOT / "macos" / "UKWSRVisualizerMac.xcodeproj" / "xcshareddata" / "xcschemes" / "UKWSRVisualizerMac.xcscheme"

        self.assertTrue(workspace.exists())
        self.assertIn("UKWSRVisualizerMac.xcodeproj", workspace.read_text(encoding="utf-8"))
        self.assertIn("ios/UKWSRVisualizer.xcodeproj", workspace.read_text(encoding="utf-8"))
        self.assertTrue(project.exists())
        self.assertIn("UKWSRVisualizerMac", project.read_text(encoding="utf-8"))
        self.assertTrue(scheme.exists())

    def test_xcode_mac_shell_has_server_and_diagnostics_hooks(self):
        source_root = ROOT / "macos" / "UKWSRVisualizerMac"
        app_source = (source_root / "UKWSRVisualizerMacApp.swift").read_text(encoding="utf-8")
        controller = (source_root / "ServerController.swift").read_text(encoding="utf-8")
        launcher = (source_root / "Resources" / "uk-wsr-visualizer-server.zsh").read_text(encoding="utf-8")

        self.assertIn("--self-test", app_source)
        self.assertIn("Open Logs", app_source)
        self.assertIn("Clear Raw Cache", app_source)
        self.assertIn("UK_WSR_VISUALIZER_GIT_COMMIT", controller)
        self.assertIn("UK_WSR_VISUALIZER_REPO_ROOT", launcher)
        self.assertIn("uk_wsr_visualizer.cli api", launcher)
        self.assertIn("imageio, imageio_ffmpeg", launcher)
        self.assertIn("imageio imageio-ffmpeg", launcher)

    def test_xcode_build_script_embeds_version_and_repo(self):
        build_script = ROOT / "macos" / "build-xcode-macos.sh"
        version_helper = ROOT / "tools" / "project_version.py"
        script = build_script.read_text(encoding="utf-8")

        self.assertTrue(build_script.exists())
        self.assertTrue(version_helper.exists())
        self.assertIn("xcodebuild", script)
        self.assertIn("UKWSRGitCommit", script)
        self.assertIn("Contents/Resources/repo", script)
        self.assertIn("--exclude 'data/'", script)
        self.assertIn("notarytool submit", script)
        self.assertIn("stapler staple", script)

    def test_github_actions_macos_beta_workflow_exists(self):
        workflow = ROOT / ".github" / "workflows" / "macos-beta.yml"
        text = workflow.read_text(encoding="utf-8")

        self.assertIn("runs-on: macos-latest", text)
        self.assertIn("python -m unittest tests.test_macos_app", text)
        self.assertIn("macos/build-xcode-macos.sh", text)
        self.assertIn("UK WSR Visualizer macOS Xcode Beta.zip", text)
        self.assertIn("MACOS_CERTIFICATE_P12_BASE64", text)
        self.assertIn("DEVELOPER_ID_APPLICATION", text)
        self.assertIn("APPLE_APP_SPECIFIC_PASSWORD", text)


if __name__ == "__main__":
    unittest.main()
