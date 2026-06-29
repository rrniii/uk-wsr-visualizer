import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


class PvolCatalogToolTests(unittest.TestCase):
    def test_config_defaults_match_public_pvol_catalog_layout(self):
        common = importlib.import_module("pvol_catalog_common")
        config = common.config_from_env()

        self.assertEqual(config.bucket, "uk-wsr-visualizer-public")
        self.assertEqual(config.object_prefix, "ukmo-nimrod")
        self.assertIn("ncas-radar-o.s3-ext.jc.rl.ac.uk", config.public_base_url)
        self.assertTrue(str(config.pvol_base).endswith("vol2birdinput/single-site"))

    def test_config_can_be_overridden_without_editing_scripts(self):
        common = importlib.import_module("pvol_catalog_common")
        overrides = {
            "UK_WSR_AWS": "/tmp/aws",
            "UK_WSR_OBJECT_STORE_BUCKET": "test-bucket",
            "UK_WSR_OBJECT_STORE_ENDPOINT": "http://example.invalid",
            "UK_WSR_AWS_PROFILE": "test-profile",
            "UK_WSR_AWS_REGION": "test-region",
            "UK_WSR_OBJECT_PREFIX": "test-prefix",
            "UK_WSR_PVOL_BASE": "/tmp/pvol",
            "UK_WSR_PUBLIC_BASE_URL": "https://public.example.invalid",
            "UK_WSR_PVOL_UPLOAD_BASE": "/tmp/uploads",
        }
        with patch.dict(os.environ, overrides, clear=False):
            config = common.config_from_env()

        self.assertEqual(config.aws, "/tmp/aws")
        self.assertEqual(config.bucket, "test-bucket")
        self.assertEqual(config.endpoint, "http://example.invalid")
        self.assertEqual(config.profile, "test-profile")
        self.assertEqual(config.region, "test-region")
        self.assertEqual(config.object_prefix, "test-prefix")
        self.assertEqual(config.pvol_base, Path("/tmp/pvol"))
        self.assertEqual(config.public_base_url, "https://public.example.invalid")
        self.assertEqual(config.upload_base, Path("/tmp/uploads"))

    def test_object_key_and_public_url_normalize_slashes(self):
        common = importlib.import_module("pvol_catalog_common")
        key = common.object_key("/ukmo-nimrod/", "/pvol/", "chenies", "2026")

        self.assertEqual(key, "ukmo-nimrod/pvol/chenies/2026")
        self.assertEqual(
            common.join_object_url("https://example.invalid/base/", f"/{key}"),
            "https://example.invalid/base/ukmo-nimrod/pvol/chenies/2026",
        )


if __name__ == "__main__":
    unittest.main()
