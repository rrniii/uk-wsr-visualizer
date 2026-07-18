from pathlib import Path
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.catalog import (
    CatalogItem,
    QuantityRecord,
    build_raw_volume_catalog,
    catalog_summary,
    filter_catalog,
    load_catalog,
    load_catalog_url,
    pvol_catalog_summary,
    pvol_items_from_coverage,
    pvol_radar_records,
    write_catalog,
)


def write_root_volume(path: Path, quantity: str = "DBZH") -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.0
        where.attrs["lon"] = -1.0
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 3
        dataset_where.attrs["rscale"] = 1000.0
        data_group = dataset.create_group("data1")
        what = data_group.create_group("what")
        what.attrs["quantity"] = quantity
        data_group.create_dataset("data", data=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])


def item(radar: str, date: str, pulses: list[str], quantities: list[str]) -> CatalogItem:
    return CatalogItem(
        radar=radar,
        radar_num="20",
        date=date,
        path=f"/tmp/{date}.h5",
        file_size=1,
        modified_time=0,
        pulses=pulses,
        times=["0000"],
        quantities=quantities,
        quantity_records=[
            QuantityRecord(
                pulse=pulses[0],
                time="0000",
                dataset="1",
                kind="data",
                index="1",
                quantity=quantities[0],
            )
        ],
        object_key=f"uk-radar/{date}.h5",
    )


class CatalogFilterTests(unittest.TestCase):
    def test_filter_by_radar_date_pulse_quantity(self):
        items = [
            item("thurnham", "20260614", ["lp"], ["DBZH"]),
            item("chenies", "20260615", ["sp"], ["VRADH"]),
        ]
        result = filter_catalog(items, radar="thurnham", start="2026-06-01", end="2026-06-30", pulse="lp", quantity="DBZH")
        self.assertEqual([entry.date for entry in result], ["20260614"])

    def test_catalog_summary(self):
        items = [
            item("thurnham", "20260614", ["lp"], ["DBZH"]),
            item("chenies", "20260615", ["sp"], ["VRADH"]),
        ]
        summary = catalog_summary(items)
        self.assertEqual(summary["item_count"], 2)
        self.assertEqual(summary["start_date"], "20260614")
        self.assertEqual(summary["end_date"], "20260615")
        self.assertEqual(summary["radars"], ["chenies", "thurnham"])

    def test_load_catalog_url_accepts_public_inventory_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            write_catalog(path, [item("chenies", "20180101", ["lp"], ["DBZH"])])
            payload = path.read_text(encoding="utf-8")
            payload = payload.replace('"path": "/tmp/20180101.h5"', '"path": "https://example.invalid/20180101.h5"')
            payload = payload.replace('"object_url": ""', '"object_url": "https://example.invalid/20180101.h5"')
            payload = payload.replace('"object_key": "uk-radar/20180101.h5"', '"object_key": "uk-radar/20180101.h5", "private_path_redacted": true')
            path.write_text(payload, encoding="utf-8")

            items = load_catalog_url(path.as_uri())

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].radar, "chenies")
        self.assertEqual(items[0].path, "https://example.invalid/20180101.h5")
        self.assertEqual(items[0].object_url, "https://example.invalid/20180101.h5")

    def test_pvol_root_summary_and_spatial_records(self):
        root = {
            "interim": True,
            "upload_complete": False,
            "spatial_source": "fixture",
            "radars": [
                {
                    "radar": "castor-bay",
                    "radar_num": "07",
                    "years": ["2026"],
                    "coverage_keys": ["ukmo-nimrod/catalog/pvol/castor-bay/2026/coverage.json"],
                    "first_date": "20260601",
                    "last_date": "20260602",
                    "date_count": 2,
                    "file_count": 864,
                    "size_bytes": 123,
                    "spatial": {
                        "latitude": 54.50194444444445,
                        "longitude": -6.342777777777777,
                        "height_m": 41.0,
                        "source": "ODIM",
                    },
                }
            ],
        }

        summary = pvol_catalog_summary(root)
        records = pvol_radar_records(root)

        self.assertEqual(summary["item_count"], 2)
        self.assertEqual(summary["by_radar"]["castor-bay"]["latest_plot_ready_date"], "20260602")
        self.assertEqual(records[0]["latitude"], 54.50194444444445)
        self.assertEqual(records[0]["longitude"], -6.342777777777777)
        self.assertEqual(records[0]["height_m"], 41.0)

    def test_pvol_coverage_days_become_lazy_raw_volume_items_with_spatial_metadata(self):
        root = {
            "interim": True,
            "upload_complete": False,
            "spatial_source": "fixture",
            "radars": [],
        }
        radar = {
            "radar": "castor-bay",
            "radar_num": "07",
            "spatial": {
                "latitude": 54.50194444444445,
                "longitude": -6.342777777777777,
                "height_m": 41.0,
                "source": "fixture",
            },
        }
        coverage = {
            "days": [
                {
                    "date": "20260621",
                    "catalog_key": "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/21/catalog.json",
                    "pvol_prefix": "ukmo-nimrod/pvol/castor-bay/2026/06/21",
                    "file_count": 432,
                    "size_bytes": 1000,
                    "pulse_counts": {"lp": 288, "sp": 144},
                }
            ]
        }

        items = pvol_items_from_coverage(root, radar, coverage, "https://example.invalid")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_type, "raw_volume_day")
        self.assertEqual(items[0].pulses, ["lp", "sp"])
        self.assertEqual(items[0].times, [])
        self.assertEqual(items[0].root_attrs["uk_wsr:spatial"]["longitude"], -6.342777777777777)
        self.assertEqual(items[0].root_attrs["catalog_key"], "ukmo-nimrod/catalog/pvol/castor-bay/2026/06/21/catalog.json")

    def test_build_raw_volume_catalog_groups_split_files_by_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "vol2birdinput" / "single-site"
            write_root_volume(
                base / "chenies" / "2018" / "20180401" / "lp" / "20180401_polar_pl_radar05_aggregate_lp_0000.h5"
            )
            write_root_volume(
                base / "chenies" / "2018" / "20180401" / "sp" / "20180401_polar_pl_radar05_aggregate_sp_0000.h5",
                quantity="VRADH",
            )
            output = root / "catalog.json"

            items = build_raw_volume_catalog(
                base,
                output,
                radar="chenies",
                year="2018",
                date="20180401",
                object_store_base="https://example.invalid/bucket",
            )
            loaded = load_catalog(output)

        self.assertEqual(len(items), 1)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(items[0].source_type, "raw_volume_day")
        self.assertEqual(items[0].pulses, ["lp", "sp"])
        self.assertEqual(items[0].times, ["0000"])
        self.assertEqual(items[0].quantities, ["DBZH", "VRADH"])
        self.assertEqual(len(items[0].raw_volumes), 2)
        self.assertIn("/ukmo-nimrod/pvol/chenies/2018/04/01/lp/", items[0].raw_volumes[0].object_url)
        self.assertEqual(loaded[0].raw_volumes[0].pulse, "lp")

    def test_build_raw_volume_catalog_fast_mode_reuses_representative_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "vol2birdinput" / "single-site"
            write_root_volume(
                base / "chenies" / "2018" / "20180401" / "lp" / "20180401_polar_pl_radar05_aggregate_lp_0000.h5"
            )
            write_root_volume(
                base / "chenies" / "2018" / "20180401" / "lp" / "20180401_polar_pl_radar05_aggregate_lp_0005.h5"
            )
            output = root / "catalog.json"

            items = build_raw_volume_catalog(
                base,
                output,
                radar="chenies",
                year="2018",
                date="20180401",
                metadata_mode="fast",
            )

        self.assertEqual(len(items), 1)
        self.assertEqual([volume.time for volume in items[0].raw_volumes], ["0000", "0005"])
        self.assertEqual(items[0].times, ["0000", "0005"])
        self.assertEqual(items[0].quantities, ["DBZH"])
        self.assertEqual(len(items[0].quantity_records), 2)


if __name__ == "__main__":
    unittest.main()
