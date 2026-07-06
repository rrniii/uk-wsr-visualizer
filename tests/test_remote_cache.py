from pathlib import Path
import os
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.catalog import CatalogItem, RawVolumeRecord
from uk_wsr_visualizer.remote_cache import (
    cached_aggregate_path,
    cached_raw_volume_path,
    clear_raw_cache,
    is_remote_url,
    item_aggregate_url,
    prune_raw_cache,
    raw_cache_status,
    raw_volume_url,
)


def catalog_item(**overrides) -> CatalogItem:
    payload = {
        "radar": "chenies",
        "radar_num": "05",
        "date": "20180101",
        "path": "",
        "file_size": 1,
        "modified_time": 0,
        "pulses": [],
        "times": [],
        "quantities": [],
        "quantity_records": [],
        "object_key": "ukmo-nimrod/aggregate/chenies/2018/20180101_polar_pl_radar05_aggregate.h5",
        "object_url": "",
    }
    payload.update(overrides)
    return CatalogItem(**payload)


def raw_volume(**overrides) -> RawVolumeRecord:
    payload = {
        "pulse": "lp",
        "time": "0000",
        "path": "",
        "filename": "20180101_polar_pl_radar05_aggregate_lp_0000.h5",
        "file_size": 1,
        "modified_time": 0,
        "object_key": "ukmo-nimrod/pvol/chenies/2018/01/01/lp/20180101_polar_pl_radar05_aggregate_lp_0000.h5",
        "object_url": "",
        "quantities": ["DBZH"],
    }
    payload.update(overrides)
    return RawVolumeRecord(**payload)


class RemoteCacheTests(unittest.TestCase):
    def test_remote_url_detection(self):
        self.assertTrue(is_remote_url("https://example.invalid/file.h5"))
        self.assertTrue(is_remote_url("http://example.invalid/file.h5"))
        self.assertFalse(is_remote_url("/tmp/file.h5"))
        self.assertFalse(is_remote_url(""))

    def test_item_aggregate_url_prefers_public_object_url(self):
        item = catalog_item(path="https://example.invalid/path-value.h5", object_url="https://example.invalid/object-value.h5")
        self.assertEqual(item_aggregate_url(item, "https://base.invalid/bucket"), "https://example.invalid/object-value.h5")

    def test_item_aggregate_url_can_derive_from_key(self):
        item = catalog_item()
        self.assertEqual(
            item_aggregate_url(item, "https://base.invalid/bucket"),
            "https://base.invalid/bucket/ukmo-nimrod/aggregate/chenies/2018/20180101_polar_pl_radar05_aggregate.h5",
        )

    def test_cached_aggregate_path_preserves_raw_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = cached_aggregate_path(catalog_item(), Path(tmp))
        self.assertEqual(
            path,
            Path(tmp) / "chenies" / "2018" / "20180101_polar_pl_radar05_aggregate.h5",
        )

    def test_raw_volume_url_and_cache_path(self):
        item = catalog_item()
        volume = raw_volume()
        self.assertEqual(
            raw_volume_url(volume, "https://base.invalid/bucket"),
            "https://base.invalid/bucket/ukmo-nimrod/pvol/chenies/2018/01/01/lp/20180101_polar_pl_radar05_aggregate_lp_0000.h5",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = cached_raw_volume_path(item, volume, Path(tmp))
        self.assertEqual(
            path,
            Path(tmp)
            / "pvol"
            / "chenies"
            / "2018"
            / "01"
            / "01"
            / "lp"
            / "20180101_polar_pl_radar05_aggregate_lp_0000.h5",
        )

    def test_raw_cache_status_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            path = cache / "chenies" / "2018" / "20180101_polar_pl_radar05_aggregate.h5"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"raw")
            volume_path = cache / "pvol" / "chenies" / "2018" / "01" / "01" / "lp" / "file.h5"
            volume_path.parent.mkdir(parents=True)
            volume_path.write_bytes(b"volume")

            status = raw_cache_status(cache)
            cleared = clear_raw_cache(cache)

        self.assertEqual(status["file_count"], 2)
        self.assertEqual(status["byte_count"], 9)
        self.assertEqual(cleared["removed_count"], 2)
        self.assertEqual(cleared["removed_bytes"], 9)

    def test_prune_raw_cache_keeps_recent_files_when_age_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            old_file = cache / "old.h5"
            new_file = cache / "new.h5"
            old_file.write_bytes(b"old")
            new_file.write_bytes(b"new")
            old_time = 1_000_000_000
            new_time = 2_000_000_000
            os.utime(old_file, (old_time, old_time))
            os.utime(new_file, (new_time, new_time))

            result = prune_raw_cache(cache, max_age_seconds=0, max_bytes=10)

        self.assertEqual(result["removed_count"], 0)

    def test_prune_raw_cache_uses_lru_when_size_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            old_file = cache / "old.h5"
            new_file = cache / "new.h5"
            old_file.write_bytes(b"old")
            new_file.write_bytes(b"new")
            os.utime(old_file, (1_000_000_000, 1_000_000_000))
            os.utime(new_file, (2_000_000_000, 2_000_000_000))

            result = prune_raw_cache(cache, max_age_seconds=0, max_bytes=4)
            remaining = sorted(path.name for path in cache.glob("*.h5"))

        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(remaining, ["new.h5"])


if __name__ == "__main__":
    unittest.main()
