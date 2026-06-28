from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.catalog import CatalogItem, QuantityRecord, RawVolumeRecord, write_catalog
import uk_wsr_visualizer.catalog as catalog_module
import uk_wsr_visualizer.cli as cli_module
from uk_wsr_visualizer.cli import main
from uk_wsr_visualizer.object_store_manifest import load_plan
from uk_wsr_visualizer.object_store_config import ObjectStoreConfig
from uk_wsr_visualizer.object_store_manifest import build_publication_plan


class FakeBucketClient:
    def __init__(self, non_empty_buckets=None):
        self.non_empty_buckets = set(non_empty_buckets or [])
        self.deleted = []
        self.created = []
        self.existing = set()

    def list_objects_v2(self, Bucket, MaxKeys=1):
        if Bucket in self.non_empty_buckets:
            return {"KeyCount": 1, "Contents": [{"Key": "example-object"}]}
        return {"KeyCount": 0}

    def delete_bucket(self, Bucket):
        self.deleted.append(Bucket)

    def head_bucket(self, Bucket):
        if Bucket not in self.existing:
            error = Exception("not found")
            error.response = {"Error": {"Code": "404"}}
            raise error

    def create_bucket(self, Bucket):
        self.created.append(Bucket)
        self.existing.add(Bucket)


class ObjectStoreCliTests(unittest.TestCase):
    def test_catalog_stac_writes_root_collection_and_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            aggregate = root / "20260614_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            write_catalog(
                catalog,
                [
                    CatalogItem(
                        radar="thurnham",
                        radar_num="20",
                        date="20260614",
                        path=str(aggregate),
                        file_size=aggregate.stat().st_size,
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
                        object_key="ukmo-nimrod/source.h5",
                    )
                ],
            )
            output_dir = root / "stac"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--catalog", str(catalog), "catalog", "stac", "--output-dir", str(output_dir)])
            self.assertEqual(code, 0)
            self.assertTrue((output_dir / "catalog.json").exists())
            self.assertTrue((output_dir / "uk-wsr-aggregate-h5" / "collection.json").exists())
            self.assertTrue((output_dir / "uk-wsr-aggregate-h5" / "thurnham-20260614.json").exists())

    def test_catalog_build_accepts_date_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "aggregates"
            day1 = base / "chenies" / "2018" / "20180101_polar_pl_radar05_aggregate.h5"
            day2 = base / "chenies" / "2018" / "20180401_polar_pl_radar05_aggregate.h5"
            day1.parent.mkdir(parents=True)
            day1.write_bytes(b"fake")
            day2.write_bytes(b"fake")

            calls = []
            original = catalog_module.scan_aggregate

            def fake_scan(path, aggregate_base, object_store_base=""):
                calls.append(path.name)
                return CatalogItem(
                    radar="chenies",
                    radar_num="05",
                    date=path.name[:8],
                    path=str(path),
                    file_size=path.stat().st_size,
                    modified_time=0,
                    pulses=[],
                    times=[],
                    quantities=[],
                    quantity_records=[],
                    object_key="ukmo-nimrod/source.h5",
                )

            catalog_module.scan_aggregate = fake_scan
            try:
                output = root / "catalog.json"
                catalog_module.build_catalog(base, output, radar="chenies", year="2018", date="20180401")
            finally:
                catalog_module.scan_aggregate = original

            self.assertEqual(calls, ["20180401_polar_pl_radar05_aggregate.h5"])

    def test_catalog_build_fast_mode_uses_filename_and_stat_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "aggregates"
            aggregate = base / "chenies" / "2018" / "20180401_polar_pl_radar05_aggregate.h5"
            aggregate.parent.mkdir(parents=True)
            aggregate.write_bytes(b"fake")

            output = root / "catalog.json"
            items = catalog_module.build_catalog(
                base,
                output,
                radar="chenies",
                year="2018",
                metadata_mode="fast",
                object_store_base="https://example.test/bucket",
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].radar, "chenies")
            self.assertEqual(items[0].date, "20180401")
            self.assertEqual(items[0].file_size, 4)
            self.assertEqual(items[0].quantity_records, [])
            self.assertEqual(items[0].root_attrs["uk_wsr:catalog_mode"], "fast")
            self.assertTrue(output.exists())

    def test_publication_plan_includes_raw_volume_h5_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20180401_polar_pl_radar05_aggregate_lp_0000.h5"
            source.write_bytes(b"volume")
            catalog = root / "catalog.json"
            item = CatalogItem(
                radar="chenies",
                radar_num="05",
                date="20180401",
                path=str(source),
                file_size=source.stat().st_size,
                modified_time=0,
                pulses=["lp"],
                times=["0000"],
                quantities=["DBZH"],
                quantity_records=[
                    QuantityRecord(pulse="lp", time="0000", dataset="1", kind="data", index="1", quantity="DBZH")
                ],
                object_key="",
                source_type="raw_volume_day",
                raw_volumes=[
                    RawVolumeRecord(
                        pulse="lp",
                        time="0000",
                        path=str(source),
                        filename=source.name,
                        file_size=source.stat().st_size,
                        modified_time=0,
                        object_key="",
                        quantities=["DBZH"],
                    )
                ],
            )
            write_catalog(catalog, [item])
            config = ObjectStoreConfig.from_mapping(
                {
                    "tenancy": "example",
                    "public_bucket": "public",
                    "staging_bucket": "staging",
                    "public_base_url": "https://example.invalid/public",
                    "publish_aggregate_h5": True,
                }
            )

            plan = build_publication_plan([item], catalog, config, root / "staging", run_id="run-raw")

        raw_objects = [obj for obj in plan.objects if obj.kind == "raw_volume_h5"]
        aggregate_objects = [obj for obj in plan.objects if obj.kind == "aggregate_h5"]
        self.assertEqual(len(raw_objects), 1)
        self.assertEqual(aggregate_objects, [])
        self.assertIn("ukmo-nimrod/pvol/chenies/2018/04/01/lp/", raw_objects[0].key)

    def test_preview_batch_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["preview", "batch", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--cappi-height-m", output.getvalue())
        self.assertIn("--palette-stops", output.getvalue())

    def test_catalog_build_raw_volume_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["catalog", "build-raw-volume", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--raw-volume-base", output.getvalue())

    def test_math_help(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["math", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_animation_build_help(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["animation", "build", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_validate_wct_help_includes_cappi_filter(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["validate", "wct", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--cappi-height-m", output.getvalue())
        self.assertIn("--require-comparison", output.getvalue())
        self.assertIn("--max-rmse", output.getvalue())

    def test_validate_wct_suite_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["validate", "wct-suite", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--cases-json", output.getvalue())
        self.assertIn("--formats", output.getvalue())
        self.assertIn("--require-comparison", output.getvalue())

    def test_object_store_plan_help_includes_validation_dir(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["object-store", "plan", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--validation-dir", output.getvalue())
        self.assertIn("--sha256-cache", output.getvalue())

    def test_object_store_sync_help_includes_skip_existing(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["object-store", "sync", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--skip-existing", output.getvalue())

    def test_object_store_backfill_status_summarizes_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backfill = root / "backfill"
            backfill.mkdir()
            (backfill / "catalog-20180101.json").write_text(
                json.dumps({"version": 1, "items": [{"file_size": 100}, {"file_size": 50}]}),
                encoding="utf-8",
            )
            (backfill / "catalog-20180102.json").write_text(
                json.dumps({"version": 1, "items": [{"file_size": 25}]}),
                encoding="utf-8",
            )
            (backfill / "verified-20180101.json").write_text(
                json.dumps({"objects": [{"status": "verified", "size": 100}, {"status": "planned", "size": 50}]}),
                encoding="utf-8",
            )
            (backfill / "synced-20180102.json").write_text(json.dumps({"objects": []}), encoding="utf-8")
            (backfill / "sha256-cache.json").write_text(
                json.dumps({"version": 1, "entries": {"a": {"size": 100}, "b": {"size": 25}}}),
                encoding="utf-8",
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["object-store", "backfill-status", "--backfill-dir", str(backfill)])

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["catalog_batches"], 2)
            self.assertEqual(payload["catalog_items"], 3)
            self.assertEqual(payload["catalog_byte_count"], 175)
            self.assertEqual(payload["verified_batches"], 1)
            self.assertEqual(payload["synced_batches"], 1)
            self.assertEqual(payload["verified_byte_count"], 100)
            self.assertEqual(payload["sha256_cache_entries"], 2)
            self.assertEqual(payload["remaining_batches"], 1)

    def test_object_store_release_candidate_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["object-store", "release-candidate", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--plan-output", output.getvalue())
        self.assertIn("--skip-wct-validation", output.getvalue())

    def test_object_store_buckets_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["object-store", "buckets", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--delete-empty-bucket", output.getvalue())
        self.assertIn("--create-bucket", output.getvalue())

    def test_object_store_buckets_execute_refuses_non_empty_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "object_store.toml"
            config.write_text(
                "\n".join(
                    [
                        "[object_store]",
                        'tenancy = "example"',
                        'public_bucket = "uk-wsr-visualizer-public"',
                        'staging_bucket = "uk-wsr-visualizer-staging"',
                    ]
                ),
                encoding="utf-8",
            )
            fake = FakeBucketClient(non_empty_buckets={"ukmo-nimrod"})
            original = cli_module.create_s3_client
            cli_module.create_s3_client = lambda config, internal=True: fake
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main(
                        [
                            "object-store",
                            "buckets",
                            "--config",
                            str(config),
                            "--delete-empty-bucket",
                            "ukmo-nimrod",
                            "--create-bucket",
                            "uk-wsr-visualizer-public",
                            "--execute",
                        ]
                    )
            finally:
                cli_module.create_s3_client = original
            self.assertEqual(code, 1)
            self.assertEqual(fake.deleted, [])
            self.assertEqual(fake.created, ["uk-wsr-visualizer-public"])
            self.assertIn('"status": "not_empty"', output.getvalue())

    def test_freshness_check_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["freshness", "check", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--require-object-store", output.getvalue())
        self.assertIn("--require-wct-validation", output.getvalue())

    def test_tile_batch_help(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["tile", "batch", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_session_project_help(self):
        export_output = io.StringIO()
        with contextlib.redirect_stdout(export_output):
            with self.assertRaises(SystemExit) as raised:
                main(["session", "export", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--output", export_output.getvalue())

        import_output = io.StringIO()
        with contextlib.redirect_stdout(import_output):
            with self.assertRaises(SystemExit) as raised:
                main(["session", "import", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--project-json", import_output.getvalue())

    def test_preview_batch_accepts_service_style_catalog_arg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.json"
            catalog.write_text('{"version": 1, "items": []}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["preview", "batch", "--catalog", str(catalog), "--preview-dir", str(root / "previews")])
            self.assertEqual(code, 0)

    def test_dry_run_publication_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "object_store.toml"
            config.write_text(
                "\n".join(
                    [
                        "[object_store]",
                        'tenancy = "example"',
                        'public_bucket = "uk-wsr-visualizer-public"',
                        'staging_bucket = "uk-wsr-visualizer-staging"',
                        'public_base_url = "https://example.invalid/uk-wsr-visualizer-public"',
                    ]
                ),
                encoding="utf-8",
            )
            aggregate = root / "20260614_polar_pl_radar20_aggregate.h5"
            aggregate.write_bytes(b"fake-hdf5")
            catalog = root / "catalog.json"
            write_catalog(
                catalog,
                [
                    CatalogItem(
                        radar="thurnham",
                        radar_num="20",
                        date="20260614",
                        path=str(aggregate),
                        file_size=aggregate.stat().st_size,
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
                ],
            )

            plan = root / "plan.json"
            synced = root / "synced.json"
            verified = root / "verified.json"
            published = root / "published.json"
            cors = root / "cors.xml"
            staging = root / "staging"

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "object-store",
                            "plan",
                            "--config",
                            str(config),
                            "--catalog",
                            str(catalog),
                            "--staging-dir",
                            str(staging),
                            "--output",
                            str(plan),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["object-store", "sync", "--config", str(config), "--plan", str(plan), "--manifest", str(synced)]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "object-store",
                            "verify",
                            "--config",
                            str(config),
                            "--manifest",
                            str(synced),
                            "--output",
                            str(verified),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "object-store",
                            "publish",
                            "--config",
                            str(config),
                            "--manifest",
                            str(verified),
                            "--output",
                            str(published),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(["object-store", "cors-template", "--config", str(config), "--output", str(cors)]),
                    0,
                )
                bucket_output = io.StringIO()
                with contextlib.redirect_stdout(bucket_output):
                    self.assertEqual(
                        main(
                            [
                                "object-store",
                                "buckets",
                                "--config",
                                str(config),
                                "--delete-empty-bucket",
                                "ukmo-nimrod",
                                "--create-bucket",
                                "uk-wsr-visualizer-staging",
                                "--create-bucket",
                                "uk-wsr-visualizer-public",
                            ]
                        ),
                        0,
                    )

            manifest = load_plan(verified)
            self.assertTrue(all(obj.status == "verified" for obj in manifest.objects))
            self.assertIn("<AllowedMethod>HEAD</AllowedMethod>", cors.read_text(encoding="utf-8"))
            self.assertIn("planned_empty_only", bucket_output.getvalue())


if __name__ == "__main__":
    unittest.main()
