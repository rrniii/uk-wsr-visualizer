from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from uk_wsr_visualizer.catalog import CatalogItem, QuantityRecord, RawVolumeRecord, write_catalog
from uk_wsr_visualizer.config import Settings
from uk_wsr_visualizer.object_store_config import ObjectStoreConfig
from uk_wsr_visualizer.object_store_manifest import build_publication_plan, write_plan


def catalog_item(source: Path) -> CatalogItem:
    return CatalogItem(
        radar="thurnham",
        radar_num="20",
        date="20260622",
        path=str(source),
        file_size=source.stat().st_size,
        modified_time=0,
        pulses=["lp"],
        times=["0000"],
        quantities=["DBZH"],
        quantity_records=[
            QuantityRecord(
                pulse="lp",
                time="0000",
                dataset="1",
                kind="data",
                index="1",
                quantity="DBZH",
            )
        ],
        object_key="",
    )


def write_root_volume(path: Path) -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.0
        where.attrs["lon"] = -1.0
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 3
        dataset_where.attrs["rscale"] = 1000.0
        data_group = dataset.create_group("data1")
        what = data_group.create_group("what")
        what.attrs["quantity"] = "DBZH"
        data_group.create_dataset("data", data=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])


def write_scaled_root_volume(path: Path) -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.0
        where.attrs["lon"] = -1.0
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 3
        dataset_where.attrs["rscale"] = 1000.0
        data_group = dataset.create_group("data1")
        what = data_group.create_group("what")
        what.attrs["quantity"] = "DBZH"
        what.attrs["gain"] = 0.5
        what.attrs["offset"] = -32.0
        what.attrs["nodata"] = 255
        what.attrs["undetect"] = 0
        data_group.create_dataset("data", data=[[0, 1, 80], [3, 255, 100]], dtype="u1")


def write_pre_vp_root_volume(path: Path) -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.0
        where.attrs["lon"] = -1.0
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 3
        dataset_where.attrs["rscale"] = 1000.0
        for group_name, quantity, values in [
            ("data1", "DBZH", [[0, 40, 42], [18, 45, 43], [22, 46, 44]]),
            ("data2", "VRADH", [[2, 2, 2], [2, 2, 2], [2, 2, 2]]),
            ("quality1", "SQIH", [[0.1, 1, 1], [1, 1, 1], [1, 1, 1]]),
            ("quality2", "NCPH", [[1, 0.1, 1], [1, 1, 1], [1, 1, 1]]),
            ("quality3", "CI", [[7, 7, 7], [7, 4, 7], [7, 7, 7]]),
        ]:
            group = dataset.create_group(group_name)
            what = group.create_group("what")
            what.attrs["quantity"] = quantity
            group.create_dataset("data", data=values)


@unittest.skipIf(TestClient is None, "fastapi test client is unavailable")
class ApiPublicMetadataTests(unittest.TestCase):
    def test_rhohv_default_display_range_keeps_low_values_visible(self):
        from uk_wsr_visualizer.api.app import _quantity_display_config

        display = _quantity_display_config("RHOHV", "auto")

        self.assertEqual(display["palette"], "RefDiff")
        self.assertEqual(display["scale_min"], 0.0)
        self.assertEqual(display["scale_max"], 1.05)
        self.assertEqual(display["mask_below_min"], False)

    def test_public_dataset_endpoint_uses_manifest_metadata(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260622_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake")
            item = catalog_item(aggregate)
            catalog = root / "catalog.json"
            write_catalog(catalog, [item])
            config = ObjectStoreConfig.from_mapping(
                {
                    "tenancy": "example",
                    "public_bucket": "uk-wsr-visualizer-public",
                    "staging_bucket": "uk-wsr-visualizer-staging",
                    "public_base_url": "https://example.invalid/uk-wsr-visualizer-public",
                    "dataset_title": "UK Radar Community Release",
                    "dataset_license": "OGL-UK-3.0",
                    "dataset_citation": "Doe et al. 2026",
                    "dataset_contact_email": "radar@example.invalid",
                }
            )
            plan = build_publication_plan([item], catalog, config, root / "staging", run_id="run-1")
            for obj in plan.objects:
                obj.status = "verified"
            manifest = root / "latest-manifest.json"
            write_plan(manifest, plan)
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=catalog,
                    object_store_manifest_path=manifest,
                    object_store_external_base=config.public_base_url,
                )
            )
            client = TestClient(app)

            response = client.get("/api/public/dataset")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["dataset"]["title"], "UK Radar Community Release")
            self.assertEqual(payload["dataset"]["license"], "OGL-UK-3.0")
            self.assertEqual(payload["catalog"]["item_count"], 1)
            self.assertIn("landing", payload["links"])

            landing = client.get("/public")
            self.assertEqual(landing.status_code, 200)
            self.assertIn("UK Radar Community Release", landing.text)
            self.assertIn("OGL-UK-3.0", landing.text)

    def test_public_dataset_endpoint_falls_back_without_manifest(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            write_catalog(catalog, [])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, object_store_manifest_path=root / "missing.json"))
            response = TestClient(app).get("/api/public/dataset")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["dataset"]["title"], "UK WSR aggregate HDF5")

    def test_status_reports_remote_catalog_mode(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260622_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake")
            catalog = root / "remote-catalog.json"
            write_catalog(catalog, [catalog_item(aggregate)])
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=root / "missing-local-catalog.json",
                    remote_catalog_url=catalog.as_uri(),
                )
            )

            response = TestClient(app).get("/api/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["remote_catalog"])
        self.assertEqual(payload["catalog_source"], catalog.as_uri())
        self.assertEqual(payload["item_count"], 1)
        self.assertIn("raw_cache_dir", payload)
        self.assertIn("version", payload)

    def test_diagnostics_endpoint_reports_catalog_cache_and_version(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260622_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake")
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(aggregate)])
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=catalog,
                    remote_aggregate_cache_dir=root / "raw-cache",
                )
            )
            response = TestClient(app).get("/api/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["application"]["name"], "UK WSR Visualizer")
        self.assertIn("version", payload["application"])
        self.assertEqual(payload["catalog"]["mode"], "catalog_items")
        self.assertEqual(payload["catalog"]["summary"]["item_count"], 1)
        self.assertIn("file_count", payload["cache"])

    def test_status_reports_catalog_error_without_failing_readiness(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_catalog = (root / "missing-remote-catalog.json").as_uri()
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=root / "missing-local-catalog.json",
                    remote_catalog_url=missing_catalog,
                )
            )
            client = TestClient(app)

            ready = client.get("/api/ready")
            status = client.get("/api/status")

        self.assertEqual(ready.status_code, 200)
        self.assertTrue(ready.json()["ok"])
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["item_count"], 0)
        self.assertEqual(payload["catalog_source"], missing_catalog)
        self.assertIn("catalog unavailable", payload["catalog_error"])

    def test_raw_cache_endpoints_report_and_clear_temporary_files(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            write_catalog(catalog, [])
            cache_file = root / "raw-cache" / "chenies" / "2018" / "20180101_polar_pl_radar05_aggregate.h5"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"raw")
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=catalog,
                    remote_aggregate_cache_dir=root / "raw-cache",
                )
            )
            client = TestClient(app)

            status = client.get("/api/cache/raw")
            cleared = client.post("/api/cache/raw/clear")
            after = client.get("/api/cache/raw")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["file_count"], 1)
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["removed_count"], 1)
        self.assertEqual(after.json()["file_count"], 0)

    def test_export_manifest_endpoint_returns_completed_manifest(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, export_dir=root / "exports"))
            client = TestClient(app)

            export = client.post(
                "/api/export",
                json={"radar": "thurnham", "date": "20260622", "format": "metadata_json"},
            )
            self.assertEqual(export.status_code, 200)
            job = export.json()
            self.assertEqual(job["status"], "complete")

            manifest = client.get(f"/api/export/{job['job_id']}/manifest")

        self.assertEqual(manifest.status_code, 200)
        payload = manifest.json()
        self.assertEqual(payload["selection"]["radar"], "thurnham")
        self.assertEqual(payload["selection"]["format"], "metadata_json")
        self.assertEqual(payload["source"]["date"], "20260622")
        self.assertIn("software", payload)
        self.assertIn("source_data", payload)

    def test_export_from_raw_volume_day_uses_selected_cached_volume(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            raw_volume_key = "ukmo-nimrod/pvol/thurnham/2026/06/22/lp/20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            item = CatalogItem(
                radar="thurnham",
                radar_num="20",
                date="20260622",
                path="https://example.invalid/day-catalog.json",
                file_size=0,
                modified_time=0,
                pulses=["lp"],
                times=["0000"],
                quantities=["DBZH"],
                quantity_records=[
                    QuantityRecord(
                        pulse="lp",
                        time="0000",
                        dataset="1",
                        kind="data",
                        index="1",
                        quantity="DBZH",
                    )
                ],
                object_key="ukmo-nimrod/catalog/pvol/thurnham/2026/20260622/catalog.json",
                source_type="raw_volume_day",
                raw_volumes=[
                    RawVolumeRecord(
                        pulse="lp",
                        time="0000",
                        path=str(source),
                        filename=source.name,
                        file_size=source.stat().st_size,
                        modified_time=source.stat().st_mtime,
                        object_key=raw_volume_key,
                        object_url="https://example.invalid/source.h5",
                        quantities=["DBZH"],
                    )
                ],
            )
            catalog = root / "catalog.json"
            write_catalog(catalog, [item])
            app = create_app(
                Settings(
                    data_dir=root / "data",
                    catalog_path=catalog,
                    export_dir=root / "exports",
                    remote_aggregate_cache_dir=root / "cache",
                )
            )
            client = TestClient(app)

            export = client.post(
                "/api/export",
                json={
                    "radar": "thurnham",
                    "date": "20260622",
                    "format": "png",
                    "pulse": "lp",
                    "time": "0000",
                    "quantity": "DBZH",
                    "dataset": "1",
                    "palette": "auto",
                    "filters": {},
                },
            )
            self.assertEqual(export.status_code, 200)
            job = export.json()
            self.assertEqual(job["status"], "complete", job.get("error"))

            manifest = client.get(f"/api/export/{job['job_id']}/manifest")

        self.assertEqual(manifest.status_code, 200)
        payload = manifest.json()
        self.assertEqual(payload["source"]["object_key"], raw_volume_key)
        self.assertEqual(payload["source"]["object_url"], "https://example.invalid/source.h5")
        self.assertTrue(payload["source"]["path"].endswith(source.name))
        self.assertEqual(payload["selection"]["quantity"], "DBZH")

    def test_ppi_endpoint_returns_georeferenced_root_volume_payload(self):
        from uk_wsr_visualizer.api.app import create_app

        try:
            import numpy  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get("/api/ppi/thurnham/20260622/lp/0000/DBZH?dataset=1&max_rays=24&max_bins=24")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source_shape"], [2, 3])
        self.assertEqual(payload["metadata"]["dataset"], "dataset1")
        self.assertEqual(payload["metadata"]["latitude"], 51.0)
        self.assertEqual(payload["metadata"]["longitude"], -1.0)
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["columns"], 3)
        self.assertEqual(payload["palette"], "homeyer")
        self.assertEqual(payload["requested_palette"], "auto")
        self.assertEqual(payload["stats"]["scale_min"], -30.0)
        self.assertEqual(payload["stats"]["scale_max"], 75.0)
        self.assertEqual(payload["gate_edges"]["azimuth_deg"], [0.0, 180.0, 360.0])
        self.assertEqual(payload["gate_edges"]["range_m"], [0.0, 1000.0, 2000.0, 3000.0])

    def test_ppi_endpoint_masks_scaled_reflectivity_below_display_minimum(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_scaled_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get("/api/ppi/thurnham/20260622/lp/0000/DBZH?dataset=1&max_rays=24&max_bins=24")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["mask_below_min"])
        self.assertEqual(payload["valid"][0], [0, 0, 1])
        self.assertEqual(payload["valid"][1], [0, 0, 1])

    def test_ppi_endpoint_accepts_display_range_override(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get(
                "/api/ppi/thurnham/20260622/lp/0000/DBZH"
                "?dataset=1&max_rays=24&max_bins=24&display_min=0&display_max=10"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stats"]["scale_min"], 0.0)
        self.assertEqual(payload["stats"]["scale_max"], 10.0)

    def test_ppi_endpoint_can_apply_noise_floor_filter(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get(
                "/api/ppi/thurnham/20260622/lp/0000/DBZH"
                "?dataset=1&max_rays=24&max_bins=24"
                "&noise_floor_enabled=true&noise_floor_method=estimated&noise_floor_margin_db=3"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["noise_floor"]["enabled"])
        self.assertEqual(payload["noise_floor"]["method"], "estimated")
        self.assertEqual(payload["noise_floor"]["operation"], "mask")
        self.assertGreater(payload["noise_floor"]["masked_count"], 0)
        self.assertEqual(len(payload["noise_floor"]["floor_profile"]), 3)
        self.assertIn("noise_floor_enabled", payload["filters"])

    def test_identify_reports_noise_floor_masked_gate(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get(
                "/api/identify/thurnham/20260622/lp/0000/DBZH"
                "?dataset=1&row=0&column=0"
                "&noise_floor_enabled=true&noise_floor_method=estimated&noise_floor_margin_db=3"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["value"])
        self.assertEqual(payload["original_value"], 1.0)
        self.assertTrue(payload["masked_by_noise_floor"])
        self.assertTrue(payload["noise_floor"]["enabled"])

    def test_pre_vp_filter_presets_and_preview_endpoint(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_pre_vp_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            client = TestClient(app)

            presets = client.get("/api/pre-vp-filter/presets")
            preview = client.get(
                "/api/pre-vp-preview/thurnham/20260622/lp/0000"
                "?dataset=1&max_rays=24&max_bins=24&pre_vp_preset=current_ci_le4"
            )

        self.assertEqual(presets.status_code, 200)
        self.assertEqual(presets.json()["default"], "current_ci_le4")
        self.assertIn("aggressive_ci_le4", presets.json()["presets"])
        self.assertEqual(preview.status_code, 200)
        payload = preview.json()
        self.assertEqual(payload["dbzh_quantity"], "DBZH")
        self.assertEqual(payload["settings"]["preset"], "current_ci_le4")
        self.assertEqual(payload["source_shape"], [3, 3])
        self.assertEqual([panel["key"] for panel in payload["panels"]], ["raw", "current_combined", "current_ci_le4", "aggressive_ci_le4", "selected"])
        selected = next(panel for panel in payload["panels"] if panel["key"] == "selected")
        self.assertGreater(selected["masked_gate_count"], 0)
        self.assertIn("components", selected["diagnostics"])


if __name__ == "__main__":
    unittest.main()
