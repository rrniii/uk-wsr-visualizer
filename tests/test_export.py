from pathlib import Path
import json
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.export import (
    ExportJob,
    ExportRequest,
    export_artifact_files,
    export_coordinate_mode,
    export_download_path,
    run_export,
    write_artifact_manifest,
    validate_export_request,
)
from uk_wsr_visualizer.catalog import CatalogItem, QuantityRecord


def write_qc_volume(path: Path) -> None:
    try:
        import h5py
        import numpy as np
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py and numpy are required")

    data = np.full((4, 4), 20.0, dtype="float32")
    sqi = np.ones((4, 4), dtype="float32")
    rhohv = np.ones((4, 4), dtype="float32")
    sqi[1, 1] = 0.1
    rhohv[1, 1] = 0.4
    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.0
        where.attrs["lon"] = -1.0
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 4
        dataset_where.attrs["rscale"] = 1000.0
        for index, (quantity, values) in enumerate((("DBZH", data), ("SQIH", sqi), ("RHOHV", rhohv)), start=1):
            group = dataset.create_group(f"data{index}")
            what = group.create_group("what")
            what.attrs["quantity"] = quantity
            group.create_dataset("data", data=values)


def catalog_item(source: Path) -> CatalogItem:
    return CatalogItem(
        radar="chenies",
        radar_num="05",
        date="20180401",
        path=str(source),
        file_size=source.stat().st_size,
        modified_time=0,
        pulses=["lp"],
        times=["0000"],
        quantities=["DBZH", "SQIH", "RHOHV"],
        quantity_records=[
            QuantityRecord(pulse="lp", time="0000", dataset="1", kind="data", index="1", quantity="DBZH"),
            QuantityRecord(pulse="lp", time="0000", dataset="1", kind="data", index="2", quantity="SQIH"),
            QuantityRecord(pulse="lp", time="0000", dataset="1", kind="data", index="3", quantity="RHOHV"),
        ],
        object_key="uk-radar/source.h5",
    )


class ExportValidationTests(unittest.TestCase):
    def test_valid_metadata_export(self):
        validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="metadata_json"))

    def test_png_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "png export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="png"))

    def test_mp4_requires_field_context_and_accepts_frame_times(self):
        with self.assertRaisesRegex(ValueError, "mp4 export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="mp4"))
        validate_export_request(
            ExportRequest(
                radar="thurnham",
                date="20260614",
                format="mp4",
                pulse="lp",
                quantity="DBZH",
                times=["0000", "0005"],
                frame_delay_ms=250,
            )
        )

    def test_mp4_rejects_too_fast_frame_delay(self):
        with self.assertRaisesRegex(ValueError, "frame_delay_ms"):
            validate_export_request(
                ExportRequest(
                    radar="thurnham",
                    date="20260614",
                    format="mp4",
                    pulse="lp",
                    quantity="DBZH",
                    times=["0000"],
                    frame_delay_ms=10,
                )
            )

    def test_kmz_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "kmz export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="kmz"))

    def test_batch_config_does_not_require_field_context(self):
        validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="wct_batch_config"))

    def test_qc_mask_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "qc_mask export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="qc_mask"))

    def test_rejects_unknown_format(self):
        with self.assertRaisesRegex(ValueError, "unsupported format"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="not_a_format"))

    def test_geotiff_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "geotiff export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="geotiff"))

    def test_cf_netcdf_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "cf_netcdf export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="cf_netcdf"))

    def test_geojson_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "geojson export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="geojson"))

    def test_export_coordinate_modes_are_explicit(self):
        self.assertEqual(export_coordinate_mode(ExportRequest(radar="thurnham", date="20260614", format="png")), "polar_ppi")
        self.assertEqual(export_coordinate_mode(ExportRequest(radar="thurnham", date="20260614", format="mp4")), "polar_ppi_animation")
        self.assertEqual(export_coordinate_mode(ExportRequest(radar="thurnham", date="20260614", format="kmz")), "georeferenced_map_overlay")
        self.assertEqual(export_coordinate_mode(ExportRequest(radar="thurnham", date="20260614", format="geotiff")), "georeferenced_cartesian")
        self.assertEqual(export_coordinate_mode(ExportRequest(radar="thurnham", date="20260614", format="metadata_json")), "catalog_metadata")
        self.assertEqual(
            export_coordinate_mode(ExportRequest(radar="thurnham", date="20260614", format="png", coordinate_mode="screen_view")),
            "screen_view",
        )

    def test_artifact_manifest_records_single_output_and_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "job-1"
            job_dir.mkdir()
            output = job_dir / "metadata.json"
            output.write_text("{}", encoding="utf-8")
            job = ExportJob(
                job_id="job-1",
                status="complete",
                request=ExportRequest(radar="thurnham", date="20260614", format="metadata_json"),
                created_at="2026-06-23T00:00:00Z",
                updated_at="2026-06-23T00:00:00Z",
                output_path=str(output),
            )
            manifest = write_artifact_manifest(root, job)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_count"], 1)
            self.assertEqual(payload["coordinate_mode"], "catalog_metadata")
            self.assertEqual(payload["selection"]["coordinate_mode"], "catalog_metadata")
            self.assertEqual(payload["request"]["coordinate_mode"], "catalog_metadata")
            self.assertEqual(payload["artifacts"][0]["coordinate_mode"], "catalog_metadata")
            self.assertIn("sha256", payload["artifacts"][0])
            self.assertIn("software", payload)
            self.assertIn("source_data", payload)
            self.assertIn("infrastructure", payload)
            self.assertEqual(export_download_path(root, job), output)

    def test_artifact_manifest_records_mp4_frame_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "job-mp4"
            job_dir.mkdir()
            output = job_dir / "animation.mp4"
            output.write_bytes(b"fake-mp4")
            sidecar = output.with_suffix(output.suffix + ".json")
            sidecar.write_text("{}", encoding="utf-8")
            job = ExportJob(
                job_id="job-mp4",
                status="complete",
                request=ExportRequest(
                    radar="thurnham",
                    date="20260614",
                    format="mp4",
                    pulse="lp",
                    quantity="DBZH",
                    times=["0000", "0005"],
                    frame_delay_ms=250,
                ),
                created_at="2026-06-23T00:00:00Z",
                updated_at="2026-06-23T00:00:00Z",
                output_path=str(output),
            )
            manifest = write_artifact_manifest(root, job)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["selection"]["format"], "mp4")
            self.assertEqual(payload["selection"]["coordinate_mode"], "polar_ppi_animation")
            self.assertEqual(payload["request"]["times"], ["0000", "0005"])
            self.assertEqual(payload["request"]["frame_delay_ms"], 250)
            self.assertEqual(payload["timing"]["frame_times"], ["0000", "0005"])
            self.assertEqual(payload["timing"]["frame_count"], 2)
            self.assertEqual(payload["timing"]["frame_delay_ms"], 250)
            self.assertEqual(payload["timing"]["fps"], 4.0)
            self.assertEqual(payload["timing"]["expected_duration_seconds"], 0.5)
            self.assertEqual(payload["timing"]["skipped_frames"], [])
            self.assertEqual(payload["artifact_count"], 2)
            self.assertEqual(sorted(path.name for path in export_artifact_files(job)), ["animation.mp4", "animation.mp4.json"])

    def test_download_path_bundles_shapefile_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "job-2"
            job_dir.mkdir()
            output = job_dir / "contours.shp"
            for suffix in (".shp", ".shx", ".dbf", ".prj"):
                output.with_suffix(suffix).write_text(suffix, encoding="utf-8")
            job = ExportJob(
                job_id="job-2",
                status="complete",
                request=ExportRequest(radar="thurnham", date="20260614", format="shapefile"),
                created_at="2026-06-23T00:00:00Z",
                updated_at="2026-06-23T00:00:00Z",
                output_path=str(output),
            )
            self.assertEqual(len(export_artifact_files(job)), 4)
            archive = export_download_path(root, job)
            self.assertIsNotNone(archive)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(sorted(bundle.namelist()), ["contours.dbf", "contours.prj", "contours.shp", "contours.shx"])

    def test_qc_mask_export_writes_mask_and_sidecar(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is required")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.h5"
            write_qc_volume(source)
            job = run_export(
                ExportRequest(
                    radar="chenies",
                    date="20180401",
                    format="qc_mask",
                    pulse="lp",
                    time="0000",
                    quantity="DBZH",
                    dataset="1",
                    filters={
                        "qc_mode": "signal_preserving",
                        "noise_floor_margin_db": 0.0,
                        "qc_companion_enabled": True,
                    },
                ),
                catalog_item(source),
                root / "exports",
            )

            self.assertEqual(job.status, "complete", job.error)
            output = Path(job.output_path)
            self.assertTrue(output.exists())
            with np.load(output) as archive:
                self.assertEqual(archive["mask"].dtype, np.dtype("uint16"))
                self.assertEqual(list(archive["mask"].shape), [4, 4])
            sidecar = json.loads(output.with_suffix(output.suffix + ".json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["qc"]["flag_counts"]["DUALPOL_QC"], 1)
            self.assertIn("RHOHV", sidecar["qc"]["companion_quantities"])
            artifacts = sorted(Path(record["path"]).name for record in json.loads(Path(job.artifact_manifest_path).read_text(encoding="utf-8"))["artifacts"])
            self.assertEqual(artifacts, [output.name, output.name + ".json"])


if __name__ == "__main__":
    unittest.main()
