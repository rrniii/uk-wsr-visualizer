from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def test_required_deployment_assets_exist(self):
        required = [
            "deploy/env/uk-wsr-visualizer.env.example",
            "deploy/systemd/uk-wsr-visualizer-api.service",
            "deploy/systemd/uk-wsr-visualizer-catalog-refresh.service",
            "deploy/systemd/uk-wsr-visualizer-catalog-refresh.timer",
            "deploy/systemd/uk-wsr-visualizer-preview-build.service",
            "deploy/systemd/uk-wsr-visualizer-preview-build.timer",
            "deploy/systemd/uk-wsr-visualizer-object-store-publish.service",
            "deploy/systemd/uk-wsr-visualizer-object-store-publish.timer",
            "deploy/systemd/uk-wsr-visualizer-freshness-check.service",
            "deploy/systemd/uk-wsr-visualizer-freshness-check.timer",
            "deploy/nginx/uk-wsr-visualizer.conf",
            "deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh",
            "deploy/bin/uk-wsr-visualizer-remote-release-smoke.sh",
            "tools/build_pvol_catalog_mirror.py",
            "tools/jasmin_integrity_audit/build_expected_raw_manifest.py",
            "tools/jasmin_pipeline/launch_integrity_checkers.sh",
            "tools/jasmin_pipeline/run_daily_avocet_pipeline.sh",
            "tools/jasmin_pipeline/run_full_avocet_rebuild.sh",
            "tools/jasmin_pvol_upload/launch_fast_pvol_upload.sh",
            "tools/jasmin_pvol_upload/fast_pvol_upload_worker.py",
            "deploy/README.md",
        ]
        missing = [path for path in required if not (ROOT / path).exists()]
        self.assertEqual(missing, [])

    def test_services_reference_expected_paths_and_commands(self):
        api = (ROOT / "deploy/systemd/uk-wsr-visualizer-api.service").read_text(encoding="utf-8")
        self.assertIn("ncas", (ROOT / "docs/uk_wsr_visualizer_deployment.md").read_text(encoding="utf-8"))
        self.assertIn("/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer api", api)
        self.assertIn("EnvironmentFile=/etc/uk-wsr-visualizer/uk-wsr-visualizer.env", api)

        env = (ROOT / "deploy/env/uk-wsr-visualizer.env.example").read_text(encoding="utf-8")
        self.assertIn("UK_WSR_VISUALIZER_TILE_DIR", env)
        self.assertIn("UK_WSR_VISUALIZER_VALIDATION_DIR", env)
        self.assertIn("UK_WSR_VISUALIZER_CATALOG_METADATA_MODE=fast", env)
        self.assertIn("UK_WSR_VISUALIZER_DATASET_TITLE", env)
        self.assertIn("UK_WSR_VISUALIZER_DATASET_TERMS_URL", env)

        catalog = (ROOT / "deploy/systemd/uk-wsr-visualizer-catalog-refresh.service").read_text(encoding="utf-8")
        self.assertIn("--metadata-mode ${UK_WSR_VISUALIZER_CATALOG_METADATA_MODE}", catalog)

        previews = (ROOT / "deploy/systemd/uk-wsr-visualizer-preview-build.service").read_text(encoding="utf-8")
        self.assertIn("preview batch", previews)
        self.assertIn("tile batch", previews)

        publisher = (ROOT / "deploy/systemd/uk-wsr-visualizer-object-store-publish.service").read_text(encoding="utf-8")
        self.assertIn("object-store plan", publisher)
        self.assertIn("--tile-dir ${UK_WSR_VISUALIZER_TILE_DIR}", publisher)
        self.assertIn("--export-dir ${UK_WSR_VISUALIZER_EXPORT_DIR}", publisher)
        self.assertIn("--validation-dir ${UK_WSR_VISUALIZER_VALIDATION_DIR}", publisher)
        self.assertIn("object-store sync --execute", publisher)
        self.assertIn("object-store verify --execute", publisher)
        self.assertIn("object-store publish --execute", publisher)

        freshness = (ROOT / "deploy/systemd/uk-wsr-visualizer-freshness-check.service").read_text(encoding="utf-8")
        self.assertIn("freshness check", freshness)
        self.assertIn("uk-wsr-visualizer-remote-smoke-test.sh", freshness)

        release_smoke = (ROOT / "deploy/bin/uk-wsr-visualizer-remote-release-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("ncas-rsg-cloud-workstation-ssh", release_smoke)
        self.assertIn("object-store release-candidate", release_smoke)
        self.assertIn("require_object_store=true&require_wct_validation=true", release_smoke)

        daily_pipeline = (ROOT / "tools/jasmin_pipeline/run_daily_avocet_pipeline.sh").read_text(encoding="utf-8")
        self.assertIn("run_daily_update.sh", daily_pipeline)
        self.assertIn("run_validate_and_vol2birdinput_after_aggregates.sh", daily_pipeline)
        self.assertIn("launch_fast_pvol_upload.sh", daily_pipeline)
        self.assertIn("launch_integrity_checkers.sh", daily_pipeline)

        checker_launcher = (ROOT / "tools/jasmin_pipeline/launch_integrity_checkers.sh").read_text(encoding="utf-8")
        self.assertIn("build_expected_raw_manifest.py", checker_launcher)
        self.assertIn("aggregate_integrity_audit.py", checker_launcher)
        self.assertIn("pvol_integrity_audit.py", checker_launcher)

        pvol_upload = (ROOT / "tools/jasmin_pvol_upload/fast_pvol_upload_worker.py").read_text(encoding="utf-8")
        self.assertIn("ukmo-nimrod/pvol", pvol_upload)

        nginx = (ROOT / "deploy/nginx/uk-wsr-visualizer.conf").read_text(encoding="utf-8")
        self.assertIn("server 127.0.0.1:8000", nginx)
        self.assertIn("130.246.214.121", nginx)


if __name__ == "__main__":
    unittest.main()
