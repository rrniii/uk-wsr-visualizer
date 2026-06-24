from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.object_store import (
    aggregate_object_key,
    catalog_inventory_object_key,
    checksum_object_key,
    export_product_object_key,
    export_object_prefix,
    join_object_url,
    latest_manifest_object_key,
    manifest_object_key,
    public_dataset_metadata_object_key,
    public_landing_object_key,
    public_status_object_key,
    relative_aggregate_path,
    stac_catalog_object_key,
    stac_collection_object_key,
    stac_object_key,
    validation_report_object_key,
)


class ObjectStoreTests(unittest.TestCase):
    def test_aggregate_object_key(self):
        self.assertEqual(
            aggregate_object_key("thurnham", "20260614"),
            "uk-radar/aggregate-h5/radar=thurnham/year=2026/20260614_polar_pl_radar20_aggregate.h5",
        )

    def test_join_object_url(self):
        self.assertEqual(
            join_object_url("https://example.invalid/base/", "/uk-radar/file.h5"),
            "https://example.invalid/base/uk-radar/file.h5",
        )

    def test_relative_aggregate_path(self):
        self.assertEqual(
            relative_aggregate_path(Path("/base"), "chenies", "20240102"),
            Path("chenies/2024/20240102_polar_pl_radar05_aggregate.h5"),
        )

    def test_catalog_manifest_and_status_keys(self):
        self.assertEqual(catalog_inventory_object_key(), "uk-radar/catalog/inventory/catalog.json")
        self.assertEqual(stac_catalog_object_key(), "uk-radar/catalog/stac/catalog.json")
        self.assertEqual(
            stac_collection_object_key("uk-wsr-aggregate-h5"),
            "uk-radar/catalog/stac/uk-wsr-aggregate-h5/collection.json",
        )
        self.assertEqual(
            stac_object_key("uk-wsr-aggregate-h5", "thurnham-20260614"),
            "uk-radar/catalog/stac/uk-wsr-aggregate-h5/thurnham-20260614.json",
        )
        self.assertEqual(manifest_object_key("run-1"), "uk-radar/manifests/sync-runs/run-1.json")
        self.assertEqual(latest_manifest_object_key(), "uk-radar/manifests/latest.json")
        self.assertEqual(checksum_object_key("2026", "thurnham"), "uk-radar/checksums/sha256/2026/thurnham.json")
        self.assertEqual(public_status_object_key(), "uk-radar/status.json")
        self.assertEqual(public_landing_object_key(), "uk-radar/index.html")
        self.assertEqual(public_dataset_metadata_object_key(), "uk-radar/dataset.json")
        self.assertEqual(
            validation_report_object_key(Path("release/report.json")),
            "uk-radar/validation/wct/release/report.json",
        )

    def test_export_product_object_key(self):
        self.assertEqual(export_object_prefix("abc123"), "uk-radar/exports/job=abc123")
        self.assertEqual(
            export_product_object_key(Path("0123456789abcdef/output.geojson")),
            "uk-radar/exports/job=0123456789abcdef/output.geojson",
        )
        self.assertEqual(export_product_object_key(Path("animations/run.zip")), "uk-radar/exports/animations/run.zip")


if __name__ == "__main__":
    unittest.main()
