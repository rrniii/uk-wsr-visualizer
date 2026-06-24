from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.session import (
    import_project,
    list_sessions,
    load_session,
    project_from_dict,
    project_to_dict,
    read_project_file,
    save_session,
    session_to_project,
    validate_session_id,
    write_project_file,
)


class SessionTests(unittest.TestCase):
    def test_save_load_and_list_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            saved = save_session(session_dir, "default", {"radar": "thurnham"}, title="Default")
            loaded = load_session(session_dir, "default")
            self.assertIsNotNone(loaded)
            self.assertEqual(saved.session_id, "default")
            self.assertEqual(loaded.state["radar"], "thurnham")
            self.assertEqual([session.session_id for session in list_sessions(session_dir)], ["default"])

    def test_rejects_unsafe_session_id(self):
        with self.assertRaisesRegex(ValueError, "session_id"):
            validate_session_id("../bad")

    def test_project_roundtrip_and_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sessions"
            project_path = Path(tmp) / "project.json"
            session = save_session(session_dir, "default", {"radar": "thurnham"}, title="Default")
            project = write_project_file(project_path, session)
            loaded = read_project_file(project_path)
            self.assertEqual(loaded.type, "uk-wsr-visualizer-project")
            self.assertEqual(project.session.session_id, "default")
            imported = import_project(session_dir, loaded, session_id="copy")
            self.assertEqual(imported.session_id, "copy")
            self.assertEqual(load_session(session_dir, "copy").state["radar"], "thurnham")

    def test_project_validation_rejects_wrong_type(self):
        with self.assertRaisesRegex(ValueError, "project type"):
            project_from_dict({"type": "bad", "version": 1, "session": {}})

    def test_project_to_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = save_session(Path(tmp) / "sessions", "default", {"radar": "thurnham"})
            payload = project_to_dict(session_to_project(session))
            self.assertEqual(payload["type"], "uk-wsr-visualizer-project")
            self.assertEqual(payload["session"]["state"]["radar"], "thurnham")


if __name__ == "__main__":
    unittest.main()
