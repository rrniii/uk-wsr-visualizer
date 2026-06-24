from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avocet_radar_toolkit.catalog import CatalogItem, QuantityRecord, write_catalog
from avocet_radar_toolkit.compat import UTC
from avocet_radar_toolkit.freshness import build_freshness_report
from avocet_radar_toolkit.object_store_config import ObjectStoreConfig
from avocet_radar_toolkit.object_store_manifest import build_publication_plan, write_plan


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


class FreshnessTests(unittest.TestCase):
    def write_validation_report(self, path: Path, parity_status: str = "passed") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"""{{
  "created_at": "2026-06-22T00:00:00Z",
  "execute_wct": true,
  "require_comparison": true,
  "results": [
    {{"case_id": "geotiff", "parity_status": "{parity_status}"}}
  ]
}}
""",
            encoding="utf-8",
        )

    def test_missing_catalog_is_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = build_freshness_report(
                Path(tmp) / "missing.json",
                Path(tmp) / "manifest.json",
                now=datetime(2026, 6, 23, tzinfo=UTC),
            )
            self.assertFalse(report.ok)
            self.assertIn("catalog_exists", [check.name for check in report.checks])

    def test_verified_manifest_and_sanitized_inventory_are_ok(self):
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
                    "public_bucket": "avocet-uk-radar-public",
                    "staging_bucket": "avocet-uk-radar-staging",
                    "public_base_url": "https://example.invalid/avocet-uk-radar-public",
                }
            )
            plan = build_publication_plan([item], catalog, config, root / "staging", run_id="run-1")
            for obj in plan.objects:
                obj.status = "verified"
            manifest = root / "latest-manifest.json"
            write_plan(manifest, plan)

            report = build_freshness_report(
                catalog,
                manifest,
                max_catalog_age_hours=10_000,
                now=datetime(2026, 6, 23, tzinfo=UTC),
                require_object_store=True,
            )
            checks = {check.name: check for check in report.checks}
            self.assertTrue(report.ok)
            self.assertTrue(checks["object_store_manifest_verified"].ok)
            self.assertTrue(checks["public_inventory_sanitized"].ok)

    def test_private_inventory_marker_fails(self):
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
                    "public_bucket": "avocet-uk-radar-public",
                    "staging_bucket": "avocet-uk-radar-staging",
                    "public_base_url": "https://example.invalid/avocet-uk-radar-public",
                }
            )
            plan = build_publication_plan([item], catalog, config, root / "staging", run_id="run-1")
            for obj in plan.objects:
                obj.status = "verified"
            inventory = next(obj for obj in plan.objects if obj.kind == "catalog_inventory")
            Path(inventory.source_path).write_text('{"path": "/gws/private/file.h5"}', encoding="utf-8")
            manifest = root / "latest-manifest.json"
            write_plan(manifest, plan)

            report = build_freshness_report(
                catalog,
                manifest,
                max_catalog_age_hours=10_000,
                now=datetime(2026, 6, 23, tzinfo=UTC),
                require_object_store=True,
            )
            checks = {check.name: check for check in report.checks}
            self.assertFalse(report.ok)
            self.assertFalse(checks["public_inventory_sanitized"].ok)

    def test_required_wct_validation_missing_fails(self):
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
                    "public_bucket": "avocet-uk-radar-public",
                    "staging_bucket": "avocet-uk-radar-staging",
                    "public_base_url": "https://example.invalid/avocet-uk-radar-public",
                }
            )
            plan = build_publication_plan([item], catalog, config, root / "staging", run_id="run-1")
            for obj in plan.objects:
                obj.status = "verified"
            manifest = root / "latest-manifest.json"
            write_plan(manifest, plan)

            report = build_freshness_report(
                catalog,
                manifest,
                max_catalog_age_hours=10_000,
                now=datetime(2026, 6, 23, tzinfo=UTC),
                require_object_store=True,
                require_wct_validation=True,
            )
            checks = {check.name: check for check in report.checks}
            self.assertFalse(report.ok)
            self.assertFalse(checks["wct_validation_reports_present"].ok)

    def test_required_wct_validation_passes_and_fails_by_parity_status(self):
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
                    "public_bucket": "avocet-uk-radar-public",
                    "staging_bucket": "avocet-uk-radar-staging",
                    "public_base_url": "https://example.invalid/avocet-uk-radar-public",
                }
            )
            validation_dir = root / "validation"
            self.write_validation_report(validation_dir / "release" / "report.json", parity_status="passed")
            plan = build_publication_plan(
                [item],
                catalog,
                config,
                root / "staging",
                validation_dir=validation_dir,
                run_id="run-1",
            )
            for obj in plan.objects:
                obj.status = "verified"
            manifest = root / "latest-manifest.json"
            write_plan(manifest, plan)

            report = build_freshness_report(
                catalog,
                manifest,
                max_catalog_age_hours=10_000,
                now=datetime(2026, 6, 23, tzinfo=UTC),
                require_object_store=True,
                require_wct_validation=True,
            )
            checks = {check.name: check for check in report.checks}
            self.assertTrue(report.ok)
            self.assertTrue(checks["wct_validation_parity_passed"].ok)

            report_obj = next(obj for obj in plan.objects if obj.kind == "validation_report")
            self.write_validation_report(Path(report_obj.source_path), parity_status="failed")
            write_plan(manifest, plan)
            failed_report = build_freshness_report(
                catalog,
                manifest,
                max_catalog_age_hours=10_000,
                now=datetime(2026, 6, 23, tzinfo=UTC),
                require_object_store=True,
                require_wct_validation=True,
            )
            failed_checks = {check.name: check for check in failed_report.checks}
            self.assertFalse(failed_report.ok)
            self.assertFalse(failed_checks["wct_validation_parity_passed"].ok)


if __name__ == "__main__":
    unittest.main()
