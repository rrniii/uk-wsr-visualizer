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
    export_download_path,
    write_artifact_manifest,
    validate_export_request,
)


class ExportValidationTests(unittest.TestCase):
    def test_valid_metadata_export(self):
        validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="metadata_json"))

    def test_png_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "png export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="png"))

    def test_kmz_requires_field_context(self):
        with self.assertRaisesRegex(ValueError, "kmz export requires"):
            validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="kmz"))

    def test_batch_config_does_not_require_field_context(self):
        validate_export_request(ExportRequest(radar="thurnham", date="20260614", format="wct_batch_config"))

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
            self.assertIn("sha256", payload["artifacts"][0])
            self.assertIn("software", payload)
            self.assertIn("source_data", payload)
            self.assertIn("infrastructure", payload)
            self.assertEqual(export_download_path(root, job), output)

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


if __name__ == "__main__":
    unittest.main()
