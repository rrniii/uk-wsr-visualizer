from pathlib import Path
import importlib.util
import os
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "linux"
LAUNCHER_PATH = LINUX / "UKWSRVisualizer.Qt" / "uk_wsr_visualizer_qt.py"


def load_linux_launcher_module():
    spec = importlib.util.spec_from_file_location("uk_wsr_visualizer_qt_test", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

        self.assertIn("XDG_CACHE_HOME", launcher)
        self.assertIn("XDG_STATE_HOME", launcher)
        self.assertIn("UK_WSR_VISUALIZER_DATA_DIR", launcher)
        self.assertIn("UK_WSR_VISUALIZER_REMOTE_CATALOG_URL", launcher)
        self.assertIn("UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE", launcher)
        self.assertIn("https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public", launcher)
        self.assertIn("ukmo-nimrod/catalog/pvol/catalog.json", launcher)
        self.assertIn("UK_WSR_VISUALIZER_LINUX_PORT", launcher)
        self.assertIn("--self-test", launcher)
        self.assertIn("--software-rendering", launcher)
        self.assertIn("--renderer", launcher)
        self.assertIn("QWebEngineView", launcher)
        self.assertNotIn("xdg-open http://", launcher)

    def test_launcher_has_startup_retry_liveness_and_diagnostics(self):
        launcher = LAUNCHER_PATH.read_text(encoding="utf-8")

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
        self.assertIn("renderer_diagnostics", launcher)
        self.assertIn("qtwebengine_chromium_flags", launcher)
        self.assertIn("started Linux server pid", launcher)
        self.assertIn("No free retry port found in 8766-8785", launcher)

    def test_launcher_configures_software_rendering_for_enterprise_linux(self):
        launcher = load_linux_launcher_module()

        with mock.patch.object(launcher, "_read_os_release", return_value={"ID": "rocky", "ID_LIKE": "rhel fedora"}), \
             mock.patch.object(launcher, "_looks_like_virtual_machine", return_value=False), \
             mock.patch.dict(os.environ, {}, clear=True):
            diagnostics = launcher.configure_linux_renderer("auto")

            self.assertEqual(diagnostics["renderer_mode"], "software")
            self.assertEqual(os.environ["LIBGL_ALWAYS_SOFTWARE"], "1")
            self.assertEqual(os.environ["QT_QUICK_BACKEND"], "software")
            self.assertIn("--disable-gpu", os.environ["QTWEBENGINE_CHROMIUM_FLAGS"])
            self.assertIn("--disable-gpu-compositing", os.environ["QTWEBENGINE_CHROMIUM_FLAGS"])

    def test_launcher_respects_explicit_hardware_override(self):
        launcher = load_linux_launcher_module()

        with mock.patch.object(launcher, "_read_os_release", return_value={"ID": "rocky", "ID_LIKE": "rhel"}), \
             mock.patch.object(launcher, "_looks_like_virtual_machine", return_value=True), \
             mock.patch.dict(os.environ, {}, clear=True):
            diagnostics = launcher.configure_linux_renderer("hardware")

        self.assertEqual(diagnostics["renderer_mode"], "hardware")
        self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", os.environ)
        self.assertNotIn("QTWEBENGINE_CHROMIUM_FLAGS", os.environ)

    def test_launcher_forces_software_rendering_from_short_alias(self):
        launcher = load_linux_launcher_module()

        with mock.patch.dict(os.environ, {}, clear=True):
            diagnostics = launcher.configure_linux_renderer("software-rendering")

            self.assertEqual(diagnostics["renderer_mode"], "software")
            self.assertEqual(os.environ["LIBGL_ALWAYS_SOFTWARE"], "1")

    def test_build_creates_expected_portable_layout(self):
        build = (LINUX / "build.sh").read_text(encoding="utf-8")

        self.assertTrue(build.startswith("#!/usr/bin/env bash"))
        if os.name != "nt":
            self.assertTrue((LINUX / "build.sh").stat().st_mode & 0o111)
        self.assertIn("--onedir", build)
        self.assertIn("uk-wsr-visualizer-server", build)
        self.assertIn(".[dev,video,linux]", build)
        self.assertIn("--hidden-import uk_wsr_visualizer.vpts", build)
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
        self.assertIn("branches: [master]", workflow)


if __name__ == "__main__":
    unittest.main()
