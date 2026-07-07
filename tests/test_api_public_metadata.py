from pathlib import Path
import base64
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

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
    base_item = CatalogItem(
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
    if "_aggregate_" not in source.name:
        return base_item
    raw_volume = RawVolumeRecord(
        pulse="lp",
        time="0000",
        path=str(source),
        filename=source.name,
        file_size=source.stat().st_size,
        modified_time=source.stat().st_mtime,
        object_key="ukmo-nimrod/pvol/thurnham/2026/06/22/lp/" + source.name,
    )
    return CatalogItem(
        **{
            **base_item.__dict__,
            "source_type": "raw_volume_day",
            "raw_volumes": [raw_volume],
            "quantities_by_pulse": {"lp": ["DBZH"]},
            "times_by_pulse": {"lp": ["0000"]},
        }
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


def write_pvol_catalog_fixture(root: Path) -> tuple[Path, str]:
    base = root / "public"
    catalog = base / "ukmo-nimrod" / "catalog" / "pvol" / "catalog.json"
    coverage = base / "ukmo-nimrod" / "catalog" / "pvol" / "castor-bay" / "2026" / "coverage.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    coverage.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        json.dumps(
            {
                "interim": True,
                "upload_complete": False,
                "spatial_source": "fixture",
                "spatial_updated_at": "2026-07-01T18:34:22Z",
                "radars": [
                    {
                        "radar": "castor-bay",
                        "radar_num": "07",
                        "years": ["2026"],
                        "coverage_keys": ["ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json"],
                        "first_date": "20260601",
                        "last_date": "20260602",
                        "date_count": 2,
                        "file_count": 864,
                        "size_bytes": 123,
                        "spatial": {
                            "latitude": 54.50194444444445,
                            "longitude": -6.342777777777777,
                            "height_m": 41.0,
                            "source": "fixture",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    coverage.write_text(
        json.dumps(
            {
                "radar": "castor-bay",
                "year": "2026",
                "days": [
                    {
                        "date": "20260601",
                        "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/01/catalog.json",
                        "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/01",
                        "file_count": 432,
                        "size_bytes": 1000,
                        "pulse_counts": {"lp": 288, "sp": 144},
                    },
                    {
                        "date": "20260602",
                        "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/02/catalog.json",
                        "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/02",
                        "file_count": 432,
                        "size_bytes": 1000,
                        "pulse_counts": {"lp": 288, "sp": 144},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return catalog, base.as_uri()


@unittest.skipIf(TestClient is None, "fastapi test client is unavailable")
class ApiPublicMetadataTests(unittest.TestCase):
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

    def test_pvol_remote_catalog_summary_radars_availability_and_freshness(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, public_base = write_pvol_catalog_fixture(root)
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=root / "missing-local-catalog.json",
                    remote_catalog_url=catalog.as_uri(),
                    object_store_external_base=public_base,
                )
            )
            client = TestClient(app)

            status = client.get("/api/status")
            summary = client.get("/api/catalog/summary")
            radars = client.get("/api/radars")
            availability = client.get("/api/catalog/availability?radar=castor-bay")
            search = client.get("/api/catalog?radar=castor-bay&start=20260601&end=20260602")
            freshness = client.get("/api/freshness")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["catalog_type"], "pvol")
        self.assertEqual(status.json()["item_count"], 2)
        self.assertEqual(summary.json()["by_radar"]["castor-bay"]["latest_plot_ready_date"], "20260602")
        self.assertEqual(radars.json()["radars"][0]["latitude"], 54.50194444444445)
        self.assertEqual(radars.json()["radars"][0]["longitude"], -6.342777777777777)
        self.assertEqual(availability.json()["first_plot_ready_date"], "20260601")
        self.assertEqual(len(search.json()["items"]), 2)
        self.assertTrue(freshness.json()["ok"])
        self.assertEqual(freshness.json()["checks"][0]["name"], "remote_catalog_loaded")

    def test_pvol_hydration_uses_field_index_sidecar_without_raw_download(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, public_base = write_pvol_catalog_fixture(root)
            day_dir = root / "public" / "ukmo-nimrod" / "catalog" / "pvol" / "castor-bay" / "2026" / "06" / "01"
            day_dir.mkdir(parents=True, exist_ok=True)
            day_catalog = day_dir / "catalog.json"
            day_catalog.write_text(
                json.dumps(
                    {
                        "radar": "castor-bay",
                        "radar_num": "07",
                        "date": "20260601",
                        "files": [
                            {
                                "pulse": "lp",
                                "time": "0000",
                                "filename": "20260601_polar_pl_radar07_aggregate_lp_0000.h5",
                                "size_bytes": 123,
                                "object_key": "ukmo-nimrod/pvol/castor-bay/2026/06/01/lp/file.h5",
                                "object_url": "https://example.invalid/file.h5",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (day_dir / "field-index.json").write_text(
                json.dumps(
                    {
                        "radar": "castor-bay",
                        "date": "20260601",
                        "files": [
                            {
                                "pulse": "lp",
                                "time": "0000",
                                "filename": "20260601_polar_pl_radar07_aggregate_lp_0000.h5",
                                "datasets": [
                                    {
                                        "dataset": "1",
                                        "elevation_deg": 0.5,
                                        "shape": [360, 425],
                                        "quantities": ["DBZH", "RHOHV"],
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            app = create_app(
                Settings(
                    data_dir=root,
                    catalog_path=root / "missing-local-catalog.json",
                    remote_catalog_url=catalog.as_uri(),
                    object_store_external_base=public_base,
                )
            )
            response = TestClient(app).get("/api/item/castor-bay/20260601/hydrate")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["quantities"], ["DBZH", "RHOHV"])
        self.assertEqual(payload["quantities_by_pulse"], {"lp": ["DBZH", "RHOHV"]})
        self.assertEqual(payload["times_by_pulse"], {"lp": ["0000"]})
        self.assertTrue(payload["root_attrs"]["field_index_loaded"])
        self.assertEqual(payload["quantity_records"][0]["shape"], [360, 425])

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
        self.assertEqual(payload["selection"]["coordinate_mode"], "catalog_metadata")
        self.assertEqual(payload["request"]["coordinate_mode"], "catalog_metadata")
        self.assertEqual(payload["source"]["date"], "20260622")
        self.assertIn("software", payload)
        self.assertIn("source_data", payload)

    def test_export_save_to_downloads_copies_completed_artifact(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
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

            with patch.dict("os.environ", {"UK_WSR_VISUALIZER_DOWNLOAD_DIR": str(downloads)}):
                saved = client.post(f"/api/export/{job['job_id']}/save-to-downloads")

            self.assertEqual(saved.status_code, 200)
            payload = saved.json()
            self.assertTrue(payload["ok"])
            self.assertTrue(Path(payload["path"]).exists())
            self.assertEqual(Path(payload["path"]).parent, downloads.resolve())
            self.assertEqual(Path(payload["path"]).read_text(encoding="utf-8"), Path(job["output_path"]).read_text(encoding="utf-8"))

    def test_local_download_endpoint_writes_client_generated_file(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
            catalog = root / "catalog.json"
            write_catalog(catalog, [])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, export_dir=root / "exports"))
            client = TestClient(app)

            with patch.dict("os.environ", {"UK_WSR_VISUALIZER_DOWNLOAD_DIR": str(downloads)}):
                saved = client.post(
                    "/api/local-download",
                    json={
                        "filename": "../project.json",
                        "content_base64": base64.b64encode(b'{"ok": true}').decode("ascii"),
                    },
                )

            self.assertEqual(saved.status_code, 200)
            payload = saved.json()
            self.assertEqual(payload["filename"], "project.json")
            self.assertEqual(Path(payload["path"]).parent, downloads.resolve())
            self.assertEqual(Path(payload["path"]).read_text(encoding="utf-8"), '{"ok": true}')

    def test_export_endpoint_can_create_mp4_with_manifest_when_video_extra_available(self):
        from uk_wsr_visualizer.api.app import create_app

        try:
            import imageio  # noqa: F401
            import imageio_ffmpeg  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("video export dependencies are unavailable")

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
                json={
                    "radar": "thurnham",
                    "date": "20260622",
                    "format": "mp4",
                    "pulse": "lp",
                    "time": "0000",
                    "quantity": "DBZH",
                    "dataset": "dataset1",
                    "frame_delay_ms": 250,
                },
            )

            self.assertEqual(export.status_code, 200)
            job = export.json()
            self.assertEqual(job["status"], "complete", job.get("error"))
            output = Path(job["output_path"])
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)
            manifest = client.get(f"/api/export/{job['job_id']}/manifest").json()
            self.assertEqual(manifest["selection"]["format"], "mp4")
            self.assertEqual(manifest["selection"]["coordinate_mode"], "polar_ppi_animation")
            self.assertEqual(manifest["request"]["frame_delay_ms"], 250)
            self.assertTrue(any(artifact["filename"].endswith(".mp4") for artifact in manifest["artifacts"]))

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

    def test_preview_meta_endpoint_reports_resolved_dataset_and_elevation(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get("/api/preview-meta/thurnham/20260622/lp/0000/DBZH?dataset=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dataset"], "dataset1")
        self.assertEqual(payload["elevation_deg"], 0.5)

    def test_preview_endpoint_accepts_qc_and_noise_query_controls(self):
        from uk_wsr_visualizer.api.app import create_app

        try:
            import PIL  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("Pillow is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get(
                "/api/preview/thurnham/20260622/lp/0000/DBZH"
                "?dataset=1&palette=homeyer&noise_floor_enabled=true"
                "&noise_floor_method=estimated&noise_floor_margin_db=3"
                "&qc_mode=conservative&noise_floor_percentile=0.05"
                "&noise_floor_window_bins=30&noise_floor_texture_enabled=true"
                "&noise_floor_texture_db=6&noise_floor_texture_near_margin_db=2"
                "&noise_floor_texture_support_db=12&noise_floor_texture_max_db=30"
                "&noise_floor_texture_min_similar_neighbors=2"
                "&qc_companion_enabled=true&qc_static_clutter_enabled=true"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_ppi_image_endpoint_returns_polar_png_with_coordinate_header(self):
        from uk_wsr_visualizer.api.app import create_app

        try:
            import PIL  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("Pillow is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            app = create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews"))
            response = TestClient(app).get("/api/ppi-image/thurnham/20260622/lp/0000/DBZH?dataset=1&palette=homeyer")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["x-uk-wsr-coordinate-mode"], "polar-ppi")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        self.assertGreater(len(response.content), 0)

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
                "&noise_floor_window_bins=1&noise_floor_texture_db=0"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["noise_floor"]["enabled"])
        self.assertEqual(payload["noise_floor"]["method"], "estimated")
        self.assertEqual(payload["noise_floor"]["operation"], "mask")
        self.assertGreater(payload["noise_floor"]["masked_count"], 0)
        self.assertEqual(len(payload["noise_floor"]["floor_profile"]), 3)
        self.assertEqual(payload["qc"]["version"], "qc-v1")
        self.assertGreater(payload["qc"]["flag_counts"]["NOISE_FLOOR"], 0)
        self.assertEqual(payload["qc"]["config"]["texture_threshold_db"], 0.0)
        self.assertIn("noise_floor_enabled", payload["filters"])
        self.assertIn("noise_floor_texture_db", payload["filters"])

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
        self.assertTrue(payload["masked_by_qc"])
        self.assertTrue(payload["noise_floor"]["enabled"])
        self.assertEqual(payload["qc"]["version"], "qc-v1")

    def test_performance_endpoint_reports_recent_api_timings(self):
        from uk_wsr_visualizer.api.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20260622_polar_pl_radar20_aggregate_lp_0000.h5"
            write_root_volume(source)
            catalog = root / "catalog.json"
            write_catalog(catalog, [catalog_item(source)])
            client = TestClient(create_app(Settings(data_dir=root, catalog_path=catalog, preview_dir=root / "previews")))

            status = client.get("/api/status")
            report = client.get("/api/performance")

        self.assertEqual(status.status_code, 200)
        self.assertIn("x-uk-wsr-elapsed-ms", status.headers)
        self.assertEqual(report.status_code, 200)
        payload = report.json()
        self.assertTrue(payload["ok"])
        self.assertIn("cache", payload)
        self.assertTrue(any(event["path"] == "/api/status" for event in payload["events"]))


if __name__ == "__main__":
    unittest.main()
