from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from uk_wsr_visualizer.config import Settings
from uk_wsr_visualizer.recent import load_recent_selections, record_recent_selection


class RecentSelectionStorageTests(unittest.TestCase):
    def test_records_deduplicated_recent_selections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent.json"
            first = {"radar": "chenies", "date": "20180401", "pulse": "lp", "time": "0000", "quantity": "DBZH"}
            second = {**first, "time": "0005"}

            record_recent_selection(path, first)
            record_recent_selection(path, second)
            record_recent_selection(path, first)

            items = load_recent_selections(path)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["time"], "0000")
        self.assertEqual(items[1]["time"], "0005")
        self.assertIn("updated_at", items[0])

    def test_ignores_invalid_existing_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent.json"
            path.write_text(json.dumps({"items": [{"date": "20180401"}, {"radar": "chenies", "date": "20180401"}]}))

            items = load_recent_selections(path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["radar"], "chenies")


@unittest.skipIf(TestClient is None, "fastapi test client is unavailable")
class RecentSelectionApiTests(unittest.TestCase):
    def test_recent_selection_api_persists_under_data_dir(self):
        from uk_wsr_visualizer.api.app import create_app
        from uk_wsr_visualizer.catalog import write_catalog

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            write_catalog(catalog, [])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, recent_selections_path=root / "recent.json"))
            client = TestClient(app)

            saved = client.post(
                "/api/recent-selections",
                json={"radar": "chenies", "date": "20180401", "pulse": "lp", "time": "0000", "quantity": "DBZH"},
            )
            loaded = client.get("/api/recent-selections")
            cleared = client.delete("/api/recent-selections")

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["items"][0]["radar"], "chenies")
        self.assertEqual(loaded.json()["items"][0]["quantity"], "DBZH")
        self.assertEqual(cleared.json()["items"], [])


if __name__ == "__main__":
    unittest.main()
