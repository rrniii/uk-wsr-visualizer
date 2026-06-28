from pathlib import Path
import os
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopReleaseWorkflowTests(unittest.TestCase):
    def test_desktop_beta_smoke_script_documents_release_gate(self):
        script_path = ROOT / "scripts" / "desktop_beta_smoke.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertTrue(script.startswith("#!/usr/bin/env bash"))
        if os.name != "nt":
            self.assertTrue(script_path.stat().st_mode & 0o111)
        self.assertIn('BRANCH" != "master"', script)
        self.assertIn("git status --short", script)
        self.assertIn("node", script)
        self.assertIn("-m pytest", script)
        self.assertIn("sphinx-build", script)
        self.assertIn("uk_wsr_visualizer.citations", script)
        self.assertIn("windows/build-via-github.sh --ref master", script)

    def test_desktop_beta_release_doc_locks_shared_windows_zip_rule(self):
        doc = (ROOT / "docs" / "desktop_beta_release.md").read_text(encoding="utf-8")

        self.assertIn("same pushed `master` commit", doc)
        self.assertIn("windows/build-via-github.sh --ref master", doc)
        self.assertIn("1dhDYp0GCiaNWINbgEYpHWCnXlVeLVjmB", doc)
        self.assertIn("Chris Hassall", doc)
        self.assertIn("Tommy Matthews", doc)
        self.assertIn("iOS branch", doc)
        self.assertIn("Zenodo DOI", doc)

    def test_release_doc_is_in_sphinx_toctree(self):
        index = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("desktop_beta_release", index)
        self.assertIn("scripts/desktop_beta_smoke.sh", checklist)
        self.assertIn("docs/desktop_beta_release.md", readme)


if __name__ == "__main__":
    unittest.main()
