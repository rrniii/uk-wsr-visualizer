import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from uk_wsr_visualizer.api.app import create_app
from uk_wsr_visualizer.config import Settings
from uk_wsr_visualizer.pvol_catalog import PvolCatalogClient, pvol_public_base_from_root_url


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def sample_pvol_tree(root: Path) -> Path:
    public = root / "public"
    root_catalog = public / "ukmo-nimrod" / "catalog" / "pvol" / "catalog.json"
    coverage_key = "ukmo-nimrod/catalog/pvol/chenies/2018/coverage.json"
    day_key = "ukmo-nimrod/catalog/pvol/chenies/2018/04/01/catalog.json"
    object_key = "ukmo-nimrod/pvol/chenies/2018/04/01/lp/20180401_polar_pl_radar05_aggregate_lp_0000.h5"
    write_json(
        root_catalog,
        {
            "schema_version": 1,
            "kind": "pvol-root",
            "product": "pvol",
            "dataset": "ukmo-nimrod",
            "interim": True,
            "upload_complete": False,
            "day_count": 1,
            "file_count": 1,
            "size_bytes": 1234,
            "coverage_csv_key": "ukmo-nimrod/catalog/pvol/coverage.csv",
            "radars": [
                {
                    "radar": "chenies",
                    "radar_num": "05",
                    "years": ["2018"],
                    "coverage_keys": [coverage_key],
                    "date_count": 1,
                    "file_count": 1,
                    "size_bytes": 1234,
                    "first_date": "20180401",
                    "last_date": "20180401",
                }
            ],
        },
    )
    write_json(
        public / coverage_key,
        {
            "schema_version": 1,
            "kind": "pvol-coverage",
            "radar": "chenies",
            "year": "2018",
            "interim": True,
            "upload_complete": False,
            "days": [
                {
                    "date": "20180401",
                    "catalog_key": day_key,
                    "pvol_prefix": "ukmo-nimrod/pvol/chenies/2018/04/01",
                    "file_count": 1,
                    "size_bytes": 1234,
                    "pulse_counts": {"lp": 1},
                }
            ],
        },
    )
    write_json(
        public / day_key,
        {
            "schema_version": 1,
            "kind": "pvol-day",
            "radar": "chenies",
            "radar_num": "05",
            "date": "20180401",
            "interim": True,
            "upload_complete": False,
            "file_count": 1,
            "size_bytes": 1234,
            "pulse_counts": {"lp": 1},
            "pulses": ["lp"],
            "times_by_pulse": {"lp": ["0000"]},
            "pvol_prefix": "ukmo-nimrod/pvol/chenies/2018/04/01",
            "files": [
                {
                    "pulse": "lp",
                    "time": "0000",
                    "filename": "20180401_polar_pl_radar05_aggregate_lp_0000.h5",
                    "size_bytes": 1234,
                    "modified_time": 1.0,
                    "object_key": object_key,
                    "object_url": f"{public.as_uri()}/{object_key}",
                }
            ],
        },
    )
    return root_catalog


class PvolCatalogTests(unittest.TestCase):
    def test_public_base_is_derived_from_root_catalog_url(self):
        root_url = "https://example.invalid/bucket/ukmo-nimrod/catalog/pvol/catalog.json"

        self.assertEqual(
            pvol_public_base_from_root_url(root_url),
            "https://example.invalid/bucket",
        )

    def test_api_uses_root_coverage_and_day_catalog_lazily(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root_catalog = sample_pvol_tree(root)
            app = create_app(
                Settings(
                    data_dir=root / "data",
                    catalog_path=root / "data" / "missing-catalog.json",
                    remote_catalog_url=root_catalog.as_uri(),
                    object_store_external_base=(root / "public").as_uri(),
                    remote_cache_max_bytes=0,
                )
            )
            client = TestClient(app)

            status = client.get("/api/status")
            summary = client.get("/api/catalog/summary")
            search = client.get("/api/catalog?radar=chenies&start=20180401&end=20180401")
            hydrate = client.get("/api/item/chenies/20180401/hydrate")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["catalog_mode"], "interim_pvol")
        self.assertTrue(status.json()["interim"])
        self.assertFalse(status.json()["upload_complete"])
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["by_radar"]["chenies"]["item_count"], 1)
        self.assertEqual(search.status_code, 200)
        items = search.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_type"], "raw_volume_day")
        self.assertEqual(items[0]["raw_volumes"], [])
        self.assertEqual(hydrate.status_code, 200)
        hydrated = hydrate.json()
        self.assertEqual(hydrated["times"], ["0000"])
        self.assertEqual(hydrated["pulses"], ["lp"])
        self.assertEqual(hydrated["raw_volumes"][0]["object_key"], "ukmo-nimrod/pvol/chenies/2018/04/01/lp/20180401_polar_pl_radar05_aggregate_lp_0000.h5")

    def test_client_returns_no_items_for_unbounded_all_radar_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root_catalog = sample_pvol_tree(root)
            client = PvolCatalogClient(root_catalog.as_uri())

            self.assertEqual(client.search(), [])


if __name__ == "__main__":
    unittest.main()
