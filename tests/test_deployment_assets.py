from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


ROOT = Path(__file__).resolve().parents[1]


class DeploymentAssetTests(unittest.TestCase):
    def test_required_deployment_assets_exist(self):
        required = [
            "deploy/env/avocet-wct.env.example",
            "deploy/systemd/avocet-wct-api.service",
            "deploy/systemd/avocet-wct-catalog-refresh.service",
            "deploy/systemd/avocet-wct-catalog-refresh.timer",
            "deploy/systemd/avocet-wct-preview-build.service",
            "deploy/systemd/avocet-wct-preview-build.timer",
            "deploy/systemd/avocet-wct-object-store-publish.service",
            "deploy/systemd/avocet-wct-object-store-publish.timer",
            "deploy/systemd/avocet-wct-freshness-check.service",
            "deploy/systemd/avocet-wct-freshness-check.timer",
            "deploy/nginx/avocet-wct.conf",
            "deploy/bin/avocet-wct-remote-smoke-test.sh",
            "deploy/bin/avocet-wct-remote-release-smoke.sh",
            "deploy/bin/avocet-wct-jasmin-backfill-year.sh",
            "deploy/README.md",
        ]
        missing = [path for path in required if not (ROOT / path).exists()]
        self.assertEqual(missing, [])

    def test_services_reference_expected_paths_and_commands(self):
        api = (ROOT / "deploy/systemd/avocet-wct-api.service").read_text(encoding="utf-8")
        self.assertIn("ncas", (ROOT / "docs/avocet_radar_toolkit_deployment.md").read_text(encoding="utf-8"))
        self.assertIn("/opt/avocet-radar-toolkit/venv/bin/avocet-wct api", api)
        self.assertIn("EnvironmentFile=/etc/avocet-wct/avocet-wct.env", api)

        env = (ROOT / "deploy/env/avocet-wct.env.example").read_text(encoding="utf-8")
        self.assertIn("AVOCET_WCT_TILE_DIR", env)
        self.assertIn("AVOCET_WCT_VALIDATION_DIR", env)
        self.assertIn("AVOCET_WCT_CATALOG_METADATA_MODE=fast", env)
        self.assertIn("AVOCET_WCT_DATASET_TITLE", env)
        self.assertIn("AVOCET_WCT_DATASET_TERMS_URL", env)

        catalog = (ROOT / "deploy/systemd/avocet-wct-catalog-refresh.service").read_text(encoding="utf-8")
        self.assertIn("--metadata-mode ${AVOCET_WCT_CATALOG_METADATA_MODE}", catalog)

        previews = (ROOT / "deploy/systemd/avocet-wct-preview-build.service").read_text(encoding="utf-8")
        self.assertIn("preview batch", previews)
        self.assertIn("tile batch", previews)

        publisher = (ROOT / "deploy/systemd/avocet-wct-object-store-publish.service").read_text(encoding="utf-8")
        self.assertIn("object-store plan", publisher)
        self.assertIn("--tile-dir ${AVOCET_WCT_TILE_DIR}", publisher)
        self.assertIn("--export-dir ${AVOCET_WCT_EXPORT_DIR}", publisher)
        self.assertIn("--validation-dir ${AVOCET_WCT_VALIDATION_DIR}", publisher)
        self.assertIn("object-store sync --execute", publisher)
        self.assertIn("object-store verify --execute", publisher)
        self.assertIn("object-store publish --execute", publisher)

        freshness = (ROOT / "deploy/systemd/avocet-wct-freshness-check.service").read_text(encoding="utf-8")
        self.assertIn("freshness check", freshness)
        self.assertIn("avocet-wct-remote-smoke-test.sh", freshness)

        release_smoke = (ROOT / "deploy/bin/avocet-wct-remote-release-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("ncas-rsg-cloud-workstation-ssh", release_smoke)
        self.assertIn("object-store release-candidate", release_smoke)
        self.assertIn("require_object_store=true&require_wct_validation=true", release_smoke)

        nginx = (ROOT / "deploy/nginx/avocet-wct.conf").read_text(encoding="utf-8")
        self.assertIn("server 127.0.0.1:8000", nginx)
        self.assertIn("130.246.214.121", nginx)


if __name__ == "__main__":
    unittest.main()
