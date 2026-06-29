import unittest
from unittest.mock import patch

from uk_wsr_visualizer.config import DEFAULT_REMOTE_CATALOG_URL, Settings


class ConfigTests(unittest.TestCase):
    def test_default_remote_catalog_points_to_public_pvol_inventory(self):
        self.assertEqual(
            DEFAULT_REMOTE_CATALOG_URL,
            "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json",
        )
        with patch.dict("os.environ", {"UK_WSR_VISUALIZER_REMOTE_CATALOG_URL": ""}, clear=False):
            self.assertEqual(Settings.from_env().remote_catalog_url, DEFAULT_REMOTE_CATALOG_URL)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(Settings.from_env().remote_catalog_url, DEFAULT_REMOTE_CATALOG_URL)


if __name__ == "__main__":
    unittest.main()
