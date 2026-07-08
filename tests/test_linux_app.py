from pathlib import Path
import os
import unittest


ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "linux"


class LinuxAppPackagingTests(unittest.TestCase):
    def test_required_linux_packaging_files_exist(self):
        required = [
            "linux/UKWSRVisualizer.Qt/uk_wsr_visualizer_qt.py",
            "linux/pyinstaller/uk_wsr_visualizer_server.py",
            "linux/build.sh",
            "linux/README.md",
            "linux/README-Linux.txt",
            "docs/linux_install_and_use.md",
            ".github/workflows/linux-beta.yml",
        ]
        missing = [path for path in required if not (ROOT / path).exists()]
        self.assertEqual(missing, [])

    def test_launcher_uses_xdg_locations_and_object_store_defaults(self):
        launcher = (LINUX / "UKWSRVisualizer.Qt" / "uk_wsr_visualizer_qt.py").read_text(encoding="utf-8")

        self.assertIn("XDG_CACHE_HOME", launcher)
        self.assertIn("XDG_STATE_HOME", launcher)
        self.assertIn("UK_WSR_VISUALIZER_DATA_DIR", launcher)
        self.assertIn("UK_WSR_VISUALIZER_REMOTE_CATALOG_URL", launcher)
        self.assertIn("UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE", launcher)
        self.assertIn("https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public", launcher)
        self.assertIn("ukmo-nimrod/catalog/pvol/catalog.json", launcher)
        self.assertIn("UK_WSR_VISUALIZER_LINUX_PORT", launcher)
        self.assertIn("--self-test", launcher)
        self.assertIn("QWebEngineView", launcher)
        self.assertNotIn("xdg-open http://", launcher)

    def test_launcher_has_startup_retry_liveness_and_diagnostics(self):
        launcher = (LINUX / "UKWSRVisualizer.Qt" / "uk_wsr_visualizer_qt.py").read_text(encoding="utf-8")

        self.assertIn("start_server_with_retry", launcher)
        self.assertIn("wait_for_ready(active_config, server, timeout_seconds)", launcher)
        self.assertIn("server.has_exited", launcher)
        self.assertIn("The local server exited before it became ready", launcher)
        self.assertIn("kill_and_clear_pid_file", launcher)
        self.assertIn("resolve_fallback_port", launcher)
        self.assertIn("selected_port=", launcher)
        self.assertIn("server_exe=", launcher)
        self.assertIn("working_dir=", launcher)
        self.assertIn("remote_catalog=", launcher)
        self.assertIn("data_dir=", launcher)
        self.assertIn("started Linux server pid", launcher)
        self.assertIn("No free retry port found in 8766-8785", launcher)

    def test_build_creates_expected_portable_layout(self):
        build = (LINUX / "build.sh").read_text(encoding="utf-8")

        self.assertTrue(build.startswith("#!/usr/bin/env bash"))
        if os.name != "nt":
            self.assertTrue((LINUX / "build.sh").stat().st_mode & 0o111)
        self.assertIn("--onedir", build)
        self.assertIn("uk-wsr-visualizer-server", build)
        self.assertIn(".[dev,video,linux]", build)
        self.assertIn("--hidden-import imageio_ffmpeg", build)
        self.assertIn("--hidden-import PySide6.QtWebEngineWidgets", build)
        self.assertIn("UK WSR Visualizer Linux portable.tar.gz", build)
        self.assertIn("UK WSR Visualizer Linux.AppImage", build)
        self.assertIn("resources/UKWSRVisualizer.png", build)
        self.assertIn("appimagetool", build)

    def test_pyproject_exposes_linux_extra(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("linux = [", pyproject)
        self.assertIn("PySide6", pyproject)
        self.assertIn("pyinstaller", pyproject)

    def test_github_action_builds_on_linux_versions(self):
        workflow = (ROOT / ".github" / "workflows" / "linux-beta.yml").read_text(encoding="utf-8")

        self.assertIn("runs-on: ${{ matrix.os }}", workflow)
        self.assertIn("ubuntu-22.04", workflow)
        self.assertIn("ubuntu-24.04", workflow)
        self.assertIn("container: debian:12", workflow)
        self.assertIn(".[dev,video,linux]", workflow)
        self.assertIn("linux/build.sh", workflow)
        self.assertIn("--self-test", workflow)
        self.assertIn("actions/upload-artifact", workflow)


if __name__ == "__main__":
    unittest.main()
