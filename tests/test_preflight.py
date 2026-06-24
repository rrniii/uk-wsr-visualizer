from pathlib import Path
import contextlib
import io
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avocet_radar_toolkit.catalog import CatalogItem, QuantityRecord, write_catalog
from avocet_radar_toolkit.cli import main
from avocet_radar_toolkit.config import Settings
from avocet_radar_toolkit.object_store_config import ObjectStoreConfig
from avocet_radar_toolkit.object_store_manifest import build_publication_plan, write_plan
from avocet_radar_toolkit.preflight import build_preflight_report


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


class PreflightTests(unittest.TestCase):
    def write_validation_report(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"created_at":"2026-06-22T00:00:00Z","results":[{"case_id":"geotiff","parity_status":"passed"}]}',
            encoding="utf-8",
        )

    def test_missing_required_paths_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = build_preflight_report(
                Settings(
                    aggregate_base=root / "missing-aggregate",
                    data_dir=root,
                    catalog_path=root / "missing-catalog.json",
                    object_store_manifest_path=root / "missing-manifest.json",
                ),
                require_object_store=True,
                require_wct_validation=True,
            )
            checks = {check.name: check for check in report.checks}
            self.assertFalse(report.ok)
            self.assertFalse(checks["aggregate_base_exists"].ok)
            self.assertFalse(checks["catalog_readable"].ok)
            self.assertFalse(checks["object_store_manifest"].ok)
            self.assertFalse(checks["wct_validation_reports"].ok)

    def test_strict_preflight_passes_with_verified_manifest_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate_base = root / "aggregates"
            aggregate_base.mkdir()
            aggregate = aggregate_base / "20260622_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake")
            item = catalog_item(aggregate)
            catalog = root / "catalog.json"
            write_catalog(catalog, [item])
            validation_dir = root / "validation" / "wct"
            self.write_validation_report(validation_dir / "release" / "report.json")
            config = ObjectStoreConfig.from_mapping(
                {
                    "tenancy": "example",
                    "public_bucket": "avocet-uk-radar-public",
                    "staging_bucket": "avocet-uk-radar-staging",
                    "public_base_url": "https://example.invalid/avocet-uk-radar-public",
                }
            )
            config_path = root / "object_store.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[object_store]",
                        'tenancy = "example"',
                        'public_bucket = "avocet-uk-radar-public"',
                        'staging_bucket = "avocet-uk-radar-staging"',
                        'public_base_url = "https://example.invalid/avocet-uk-radar-public"',
                    ]
                ),
                encoding="utf-8",
            )
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
            manifest = root / "manifest.json"
            write_plan(manifest, plan)
            report = build_preflight_report(
                Settings(
                    aggregate_base=aggregate_base,
                    data_dir=root,
                    catalog_path=catalog,
                    object_store_manifest_path=manifest,
                ),
                object_store_config_path=config_path,
                validation_dir=validation_dir,
                require_object_store=True,
                require_wct_validation=True,
            )
            self.assertTrue(report.ok)

    def test_cli_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["deployment", "preflight", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--require-wct-validation", output.getvalue())
        self.assertIn("--base-url", output.getvalue())


if __name__ == "__main__":
    unittest.main()
