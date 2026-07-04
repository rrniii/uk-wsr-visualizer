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

    def test_checked_in_bundle_uses_final_pvol_catalog(self):
        config = APP / "Contents" / "Resources" / "repo" / "src" / "uk_wsr_visualizer" / "config.py"
        launcher = APP / "Contents" / "Resources" / "uk-wsr-visualizer-server.zsh"
        config_text = config.read_text(encoding="utf-8")
        launcher_text = launcher.read_text(encoding="utf-8")

        self.assertIn("ukmo-nimrod/catalog/pvol/catalog.json", config_text)
        self.assertIn("ukmo-nimrod/catalog/pvol/catalog.json", launcher_text)
        self.assertNotIn("uk-radar/catalog/inventory/catalog.json", config_text)

    def test_checked_in_bundle_defaults_to_signal_preserving_qc_cleanup(self):
        static_root = APP / "Contents" / "Resources" / "repo" / "src" / "uk_wsr_visualizer" / "static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        js = (static_root / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="noiseFloorInput" type="checkbox" checked', html)
        self.assertIn('id="noiseFloorMarginInput" type="number" step="0.5" value="0"', html)
        self.assertIn('const DEFAULT_QC_MODE = "signal_preserving"', js)
        self.assertIn("params.qc_companion_enabled = true", js)
        self.assertIn("params.qc_static_clutter_enabled = true", js)


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
        main_source = (source_root / "main.swift").read_text(encoding="utf-8")
        delegate_source = (source_root / "AppDelegate.swift").read_text(encoding="utf-8")
        window_source = (source_root / "AccessibleWindow.swift").read_text(encoding="utf-8")
        controller = (source_root / "ServerController.swift").read_text(encoding="utf-8")
        launcher = (source_root / "Resources" / "uk-wsr-visualizer-server.zsh").read_text(encoding="utf-8")

        self.assertIn("--self-test", main_source)
        self.assertIn("SelfTest.run()", main_source)
        self.assertIn("NSApplication.shared", main_source)
        self.assertIn("app.delegate = delegate", main_source)
        self.assertIn("app.run()", main_source)
        self.assertNotIn("@NSApplicationMain", delegate_source)
        self.assertNotIn("@NSApplicationDelegateAdaptor(AppDelegate.self)", delegate_source)
        self.assertIn("server.start()", delegate_source)
        self.assertIn("configureMenu()", delegate_source)
        self.assertIn("showMainWindow()", delegate_source)
        self.assertIn("private var mainWindowController: NSWindowController?", delegate_source)
        self.assertIn("AccessibleWindow(", delegate_source)
        self.assertIn("contentRect:", delegate_source)
        self.assertIn("backing: .buffered", delegate_source)
        self.assertIn("window.contentViewController = hostingController", delegate_source)
        self.assertIn('window.title = "UK WSR Visualizer"', delegate_source)
        self.assertIn('accessibilityIdentifier("UKWSRVisualizerMainContent")', delegate_source)
        self.assertIn('setAccessibilityIdentifier("UKWSRVisualizerMainWindow")', delegate_source)
        self.assertIn('setAccessibilityTitle("UK WSR Visualizer")', delegate_source)
        self.assertIn('setAccessibilityIdentifier("UKWSRVisualizerMainContentView")', delegate_source)
        self.assertIn('setAccessibilityLabel("UK WSR Visualizer main content")', delegate_source)
        self.assertIn('setFrameAutosaveName("UKWSRVisualizerMainWindow")', delegate_source)
        self.assertNotIn("setAccessibilityRole(.window)", delegate_source)
        self.assertNotIn("setAccessibilityElement(true)", delegate_source)
        self.assertIn("setActivationPolicy(.regular)", delegate_source)
        self.assertIn("NSWindowController(window: window)", delegate_source)
        self.assertIn("windowController.showWindow(nil)", delegate_source)
        self.assertIn("window.makeMain()", delegate_source)
        self.assertIn("NSApp.activate(ignoringOtherApps: true)", delegate_source)
        self.assertIn("Open Logs", delegate_source)
        self.assertIn("Clear Raw Cache", delegate_source)
        self.assertIn("final class AccessibleWindow: NSWindow", window_source)
        self.assertIn("override var canBecomeKey: Bool", window_source)
        self.assertIn("override var canBecomeMain: Bool", window_source)
        self.assertNotIn("isAccessibilityElement() -> Bool", window_source)
        self.assertNotIn("accessibilityRole()", window_source)
        self.assertNotIn("accessibilitySubrole()", window_source)
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
        self.assertIn("Contents/Resources/repo/src", script)
        self.assertIn("PYTHONDONTWRITEBYTECODE", (ROOT / "macos" / "UKWSRVisualizerMac" / "Resources" / "uk-wsr-visualizer-server.zsh").read_text(encoding="utf-8"))
        self.assertIn("notarytool submit", script)
        self.assertIn("stapler staple", script)

    def test_xcode_mac_project_builds_explicit_window_shell(self):
        project = ROOT / "macos" / "UKWSRVisualizerMac.xcodeproj" / "project.pbxproj"
        text = project.read_text(encoding="utf-8")

        self.assertIn("AppDelegate.swift", text)
        self.assertIn("AppDelegate.swift in Sources", text)
        self.assertIn("main.swift", text)
        self.assertIn("main.swift in Sources", text)
        self.assertIn("AccessibleWindow.swift", text)
        self.assertIn("AccessibleWindow.swift in Sources", text)
        delegate_source = (ROOT / "macos" / "UKWSRVisualizerMac" / "AppDelegate.swift").read_text(encoding="utf-8")
        self.assertIn("NSHostingController", delegate_source)
        self.assertIn("AppShell", delegate_source)

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
