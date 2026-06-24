from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avocet_radar_toolkit.catalog import CatalogItem, QuantityRecord, write_catalog
from avocet_radar_toolkit.cli import main
from avocet_radar_toolkit.object_store_config import ObjectStoreConfig, cors_xml, load_object_store_config
from avocet_radar_toolkit.object_store_manifest import build_publication_plan, load_plan, reconcile_plan_with_manifest, write_plan
from avocet_radar_toolkit.object_store_sync import publish_manifest, sync_plan, verify_plan
import avocet_radar_toolkit.object_store_manifest as manifest_module


def catalog_item(source: Path) -> CatalogItem:
    return CatalogItem(
        radar="thurnham",
        radar_num="20",
        date="20260614",
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


class FakeS3:
    def __init__(self):
        self.objects = {}

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None, Config=None):
        data = Path(Filename).read_bytes()
        self.objects[(Bucket, Key)] = {
            "body": data,
            "acl": (ExtraArgs or {}).get("ACL", ""),
            "content_type": (ExtraArgs or {}).get("ContentType", ""),
            "metadata": (ExtraArgs or {}).get("Metadata", {}),
            "config": Config,
        }

    def put_object(self, Bucket, Key, Body, ContentType=None, ACL=None):
        self.objects[(Bucket, Key)] = {
            "body": Body,
            "acl": ACL,
            "content_type": ContentType,
            "metadata": {},
        }

    def head_object(self, Bucket, Key):
        obj = self.objects[(Bucket, Key)]
        return {"ContentLength": len(obj["body"]), "Metadata": obj["metadata"]}


class ObjectStorePublicationTests(unittest.TestCase):
    def config(self) -> ObjectStoreConfig:
        return ObjectStoreConfig.from_mapping(
            {
                "tenancy": "example",
                "public_bucket": "avocet-uk-radar-public",
                "staging_bucket": "avocet-uk-radar-staging",
                "public_base_url": "https://example.invalid/avocet-uk-radar-public",
                "allowed_origins": ["https://viewer.example.invalid"],
            }
        )

    def test_config_defaults_and_cors_xml(self):
        config = self.config()
        self.assertEqual(config.external_endpoint, "https://example-o.s3-ext.jc.rl.ac.uk")
        xml = cors_xml(config)
        self.assertIn("<AllowedOrigin>https://viewer.example.invalid</AllowedOrigin>", xml)
        self.assertIn("<AllowedMethod>GET</AllowedMethod>", xml)
        self.assertIn("<AllowedMethod>HEAD</AllowedMethod>", xml)

    def test_build_plan_sync_verify_publish_with_fake_s3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260614_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            item = catalog_item(aggregate)
            catalog_path = root / "catalog.json"
            write_catalog(catalog_path, [item])
            export_dir = root / "exports"
            export_product = export_dir / "animations" / "thurnham_20260614.zip"
            export_product.parent.mkdir(parents=True)
            export_product.write_bytes(b"fake-animation")
            validation_dir = root / "validation" / "wct"
            validation_report = validation_dir / "release-20260614" / "report.json"
            validation_report.parent.mkdir(parents=True)
            validation_report.write_text(
                """{
  "created_at": "2026-06-14T00:00:00Z",
  "execute_wct": true,
  "require_comparison": true,
  "results": [
    {"case_id": "geotiff", "parity_status": "passed"},
    {"case_id": "kmz", "parity_status": "passed"}
  ]
}
""",
                encoding="utf-8",
            )
            tile_dir = root / "tiles"
            tile_product = (
                tile_dir
                / "radar=thurnham"
                / "date=20260614"
                / "pulse=lp"
                / "quantity=DBZH"
                / "time=0000"
                / "tiles"
                / "0"
                / "0"
                / "0.png"
            )
            tile_product.parent.mkdir(parents=True)
            tile_product.write_bytes(b"fake-png")
            config = ObjectStoreConfig.from_mapping(
                {
                    **self.config().__dict__,
                    "publish_exports": True,
                    "dataset_license": "OGL-UK-3.0",
                    "dataset_citation": "Doe et al. 2026",
                    "dataset_contact_email": "radar@example.invalid",
                }
            )

            plan = build_publication_plan(
                items=[item],
                catalog_path=catalog_path,
                config=config,
                staging_dir=root / "staging",
                tile_dir=tile_dir,
                export_dir=export_dir,
                validation_dir=validation_dir,
                run_id="run-1",
            )
            kinds = {obj.kind for obj in plan.objects}
            self.assertIn("aggregate_h5", kinds)
            self.assertIn("checksum", kinds)
            self.assertIn("catalog_inventory", kinds)
            self.assertIn("stac_catalog", kinds)
            self.assertIn("stac_collection", kinds)
            self.assertIn("stac_item", kinds)
            self.assertIn("export_product", kinds)
            self.assertIn("validation_report", kinds)
            self.assertIn("dataset_metadata", kinds)
            self.assertIn("landing_page", kinds)
            self.assertIn("tile", kinds)
            self.assertIn("status", kinds)
            inventory = next(obj for obj in plan.objects if obj.kind == "catalog_inventory")
            inventory_text = Path(inventory.source_path).read_text(encoding="utf-8")
            self.assertIn('"private_paths_redacted": true', inventory_text)
            self.assertNotIn(str(aggregate), inventory_text)
            self.assertIn("uk-radar/exports/animations/thurnham_20260614.zip", {obj.key for obj in plan.objects})
            self.assertIn("uk-radar/validation/wct/release-20260614/report.json", {obj.key for obj in plan.objects})
            status = next(obj for obj in plan.objects if obj.kind == "status")
            status_payload = Path(status.source_path).read_text(encoding="utf-8")
            self.assertIn('"report_count": 1', status_payload)
            self.assertIn('"passed": 2', status_payload)
            self.assertIn('"license": "OGL-UK-3.0"', status_payload)
            self.assertIn('"landing_url"', status_payload)
            dataset_metadata = next(obj for obj in plan.objects if obj.kind == "dataset_metadata")
            dataset_text = Path(dataset_metadata.source_path).read_text(encoding="utf-8")
            self.assertIn('"kind": "avocet_uk_radar_dataset"', dataset_text)
            self.assertIn('"license": "OGL-UK-3.0"', dataset_text)
            landing_page = next(obj for obj in plan.objects if obj.kind == "landing_page")
            landing_text = Path(landing_page.source_path).read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", landing_text)
            self.assertIn("OGL-UK-3.0", landing_text)
            stac_collection = next(obj for obj in plan.objects if obj.kind == "stac_collection")
            stac_text = Path(stac_collection.source_path).read_text(encoding="utf-8")
            self.assertIn('"license": "OGL-UK-3.0"', stac_text)
            self.assertIn('"sci:citation": "Doe et al. 2026"', stac_text)
            checksum = next(obj for obj in plan.objects if obj.kind == "checksum")
            self.assertEqual(checksum.key, "uk-radar/checksums/sha256/2026/thurnham.json")
            checksum_text = Path(checksum.source_path).read_text(encoding="utf-8")
            self.assertIn('"kind": "aggregate_sha256"', checksum_text)
            self.assertIn('"sha256"', checksum_text)
            self.assertIn(
                "uk-radar/tiles/radar=thurnham/date=20260614/pulse=lp/quantity=DBZH/time=0000/tiles/0/0/0.png",
                {obj.key for obj in plan.objects},
            )
            self.assertTrue(all(obj.sha256 for obj in plan.objects))

            plan_path = root / "plan.json"
            write_plan(plan_path, plan)
            loaded = load_plan(plan_path)
            self.assertEqual(loaded.run_id, "run-1")

            fake = FakeS3()
            fake._avocet_transfer_config = object()
            synced = sync_plan(loaded, execute=True, client=fake)
            self.assertTrue(all(obj.status == "uploaded" for obj in synced.objects))
            self.assertTrue(all(obj["config"] is fake._avocet_transfer_config for obj in fake.objects.values()))

            verified = verify_plan(synced, execute=True, client=fake)
            self.assertTrue(all(obj.status == "verified" for obj in verified.objects))

            result = publish_manifest(verified, self.config(), execute=True, client=fake)
            self.assertEqual(result["message"], "published manifest and public status objects")
            self.assertIn(("avocet-uk-radar-public", "uk-radar/manifests/latest.json"), fake.objects)
            self.assertTrue(all(obj["acl"] == "public-read" for obj in fake.objects.values()))

    def test_reconcile_finds_changed_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260614_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            item = catalog_item(aggregate)
            catalog_path = root / "catalog.json"
            write_catalog(catalog_path, [item])
            expected = build_publication_plan([item], catalog_path, self.config(), root / "expected", run_id="run-1")
            actual = build_publication_plan([item], catalog_path, self.config(), root / "actual", run_id="run-2")
            actual.objects[0].sha256 = "different"
            actual.objects[0].status = "verified"
            result = reconcile_plan_with_manifest(expected, actual)
            self.assertFalse(result["ok"])
            self.assertIn(expected.objects[0].key, result["changed"])

    def test_sync_plan_skip_existing_uses_remote_size_and_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260614_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            item = catalog_item(aggregate)
            catalog_path = root / "catalog.json"
            write_catalog(catalog_path, [item])
            plan = build_publication_plan([item], catalog_path, self.config(), root / "staging", run_id="run-1")
            aggregate_obj = next(obj for obj in plan.objects if obj.kind == "aggregate_h5")

            fake = FakeS3()
            fake.upload_file(
                aggregate_obj.source_path,
                aggregate_obj.bucket,
                aggregate_obj.key,
                ExtraArgs={"Metadata": {"sha256": aggregate_obj.sha256}, "ContentType": aggregate_obj.content_type},
            )
            synced = sync_plan(plan, execute=True, client=fake, skip_existing=True)

            skipped = next(obj for obj in synced.objects if obj.key == aggregate_obj.key)
            self.assertEqual(skipped.status, "skipped_existing")
            self.assertTrue([obj for obj in synced.objects if obj.status == "uploaded"])

    def test_publication_plan_reuses_sha256_cache_for_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aggregate = root / "20260614_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            catalog_path = root / "catalog.json"
            item = catalog_item(aggregate)
            write_catalog(catalog_path, [item])
            cache_path = root / "sha256-cache.json"

            build_publication_plan([item], catalog_path, self.config(), root / "staging-1", sha256_cache_path=cache_path)
            self.assertTrue(cache_path.exists())

            calls = []
            original = manifest_module.sha256_file

            def tracking_sha256(path, chunk_size=1024 * 1024):
                calls.append(Path(path))
                return original(path, chunk_size)

            manifest_module.sha256_file = tracking_sha256
            try:
                build_publication_plan([item], catalog_path, self.config(), root / "staging-2", sha256_cache_path=cache_path)
            finally:
                manifest_module.sha256_file = original

            self.assertNotIn(aggregate, calls)

    def test_release_candidate_command_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            aggregate = root / "20260622_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            item = catalog_item(aggregate)
            item.date = "20260622"
            catalog_path = root / "catalog.json"
            write_catalog(catalog_path, [item])
            validation_dir = root / "validation" / "wct"
            report = validation_dir / "release" / "report.json"
            report.parent.mkdir(parents=True)
            report.write_text(
                '{"created_at":"2026-06-22T00:00:00Z","execute_wct":true,"require_comparison":true,'
                '"results":[{"case_id":"geotiff","parity_status":"passed"}]}',
                encoding="utf-8",
            )
            manifest = build_publication_plan(
                [item],
                catalog_path,
                load_object_store_config(config_path),
                root / "manifest-staging",
                validation_dir=validation_dir,
                run_id="run-1",
            )
            for obj in manifest.objects:
                obj.status = "verified"
            manifest_path = root / "latest-manifest.json"
            write_plan(manifest_path, manifest)
            output = root / "release-summary.json"
            plan_output = root / "release-plan.json"

            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "object-store",
                        "release-candidate",
                        "--config",
                        str(config_path),
                        "--catalog",
                        str(catalog_path),
                        "--manifest",
                        str(manifest_path),
                        "--staging-dir",
                        str(root / "candidate-staging"),
                        "--preview-dir",
                        str(root / "empty-previews"),
                        "--tile-dir",
                        str(root / "empty-tiles"),
                        "--export-dir",
                        str(root / "empty-exports"),
                        "--validation-dir",
                        str(validation_dir),
                        "--run-id",
                        "run-1",
                        "--plan-output",
                        str(plan_output),
                        "--output",
                        str(output),
                        "--max-catalog-age-hours",
                        "10000",
                        "--max-data-latency-days",
                        "10000",
                        "--max-manifest-age-hours",
                        "10000",
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                code,
                0,
                json.dumps(
                    {
                        "ok": payload.get("ok"),
                        "missing_source_count": payload.get("missing_source_count"),
                        "reconcile": payload.get("reconcile"),
                        "freshness_ok": payload.get("freshness", {}).get("ok"),
                        "failed_checks": [
                            check for check in payload.get("freshness", {}).get("checks", []) if not check.get("ok")
                        ],
                        "plan_summary": payload.get("plan_summary"),
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["reconcile"]["ok"], True)
            self.assertTrue(payload["freshness"]["ok"])


if __name__ == "__main__":
    unittest.main()
