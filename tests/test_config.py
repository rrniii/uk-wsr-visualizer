import unittest
from unittest.mock import patch

from avocet_radar_toolkit.config import DEFAULT_REMOTE_CATALOG_URL, Settings


class ConfigTests(unittest.TestCase):
    def test_default_remote_catalog_points_to_public_inventory(self):
        self.assertEqual(
            DEFAULT_REMOTE_CATALOG_URL,
            "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public/uk-radar/catalog/inventory/catalog.json",
        )
        with patch.dict("os.environ", {"AVOCET_WCT_REMOTE_CATALOG_URL": ""}, clear=False):
            self.assertEqual(Settings.from_env().remote_catalog_url, DEFAULT_REMOTE_CATALOG_URL)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(Settings.from_env().remote_catalog_url, DEFAULT_REMOTE_CATALOG_URL)


if __name__ == "__main__":
    unittest.main()
