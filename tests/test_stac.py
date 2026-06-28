from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.catalog import CatalogItem, QuantityRecord
from uk_wsr_visualizer.stac import AGGREGATE_COLLECTION_ID, collection_to_stac, item_to_stac, root_catalog_to_stac


def make_item(radar: str = "thurnham", date: str = "20260614", bbox=None) -> CatalogItem:
    bbox = bbox or [0.0, 51.0, 1.0, 52.0]
    return CatalogItem(
        radar=radar,
        radar_num="20",
        date=date,
        path="/tmp/source.h5",
        file_size=1,
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
        object_url="https://example.invalid/source.h5",
        root_attrs={
            "uk_wsr:spatial": {
                "latitude": 51.3,
                "longitude": 0.6,
                "bbox": bbox,
                "max_range_m": 100000.0,
            }
        },
    )


class StacTests(unittest.TestCase):
    def test_item_to_stac_includes_spatial_metadata(self):
        item = make_item()
        stac = item_to_stac(item)
        self.assertEqual(stac["geometry"], {"type": "Point", "coordinates": [0.6, 51.3]})
        self.assertEqual(stac["bbox"], [0.0, 51.0, 1.0, 52.0])
        self.assertIn("derived_geotiff_template", stac["assets"])
        self.assertIn("sha256_manifest", stac["assets"])
        self.assertIn("preview_prefix", stac["assets"])
        self.assertIn("tile_prefix", stac["assets"])
        self.assertEqual(stac["collection"], AGGREGATE_COLLECTION_ID)
        self.assertIn("links", stac)

    def test_item_to_stac_public_assets_do_not_use_private_path(self):
        item = make_item()
        stac = item_to_stac(item, public_base_url="https://example.invalid/bucket")
        self.assertEqual(
            stac["assets"]["aggregate_h5"]["href"],
            "https://example.invalid/bucket/ukmo-nimrod/aggregate/thurnham/2026/20260614_polar_pl_radar20_aggregate.h5",
        )
        self.assertIn("/ukmo-nimrod/checksums/sha256/2026/thurnham.json", stac["assets"]["sha256_manifest"]["href"])
        self.assertIn("/ukmo-nimrod/previews/thurnham/2026/06/14", stac["assets"]["preview_prefix"]["href"])
        self.assertIn("/ukmo-nimrod/tiles/thurnham/2026/06/14", stac["assets"]["tile_prefix"]["href"])
        self.assertNotIn("/tmp/source.h5", str(stac["assets"]))

    def test_collection_to_stac_includes_extent_summaries_and_item_links(self):
        items = [
            make_item(date="20260614", bbox=[0.0, 51.0, 1.0, 52.0]),
            make_item(date="20260615", bbox=[-1.0, 50.0, 2.0, 53.0]),
        ]
        collection = collection_to_stac(items, public_base_url="https://example.invalid/bucket")
        self.assertEqual(collection["type"], "Collection")
        self.assertEqual(collection["id"], AGGREGATE_COLLECTION_ID)
        self.assertEqual(collection["extent"]["spatial"]["bbox"], [[-1.0, 50.0, 2.0, 53.0]])
        self.assertEqual(
            collection["extent"]["temporal"]["interval"],
            [["2026-06-14T00:00:00Z", "2026-06-15T00:00:00Z"]],
        )
        self.assertEqual(len([link for link in collection["links"] if link["rel"] == "item"]), 2)

    def test_public_metadata_is_included_in_collection_root_and_items(self):
        metadata = {
            "title": "UK Radar Community Release",
            "description": "Public release description.",
            "license": "OGL-UK-3.0",
            "citation": "Doe et al. 2026",
            "provider_name": "NCAS",
            "provider_url": "https://example.invalid/provider",
            "contact_email": "radar@example.invalid",
            "terms_url": "https://example.invalid/terms",
        }
        item = item_to_stac(make_item(), public_base_url="https://example.invalid/bucket", public_metadata=metadata)
        self.assertEqual(item["properties"]["license"], "OGL-UK-3.0")
        self.assertEqual(item["properties"]["sci:citation"], "Doe et al. 2026")
        self.assertIn("validation_prefix", item["assets"])

        collection = collection_to_stac([make_item()], public_metadata=metadata)
        self.assertEqual(collection["title"], "UK Radar Community Release")
        self.assertEqual(collection["license"], "OGL-UK-3.0")
        self.assertEqual(collection["providers"][0]["name"], "NCAS")
        self.assertEqual(collection["sci:citation"], "Doe et al. 2026")
        self.assertEqual(collection["uk_wsr:contact_email"], "radar@example.invalid")
        self.assertTrue(any(link["rel"] == "license" for link in collection["links"]))

        catalog = root_catalog_to_stac([make_item()], public_metadata=metadata)
        self.assertEqual(catalog["title"], "UK Radar Community Release")
        self.assertEqual(catalog["sci:citation"], "Doe et al. 2026")

    def test_root_catalog_links_to_collection(self):
        catalog = root_catalog_to_stac([make_item()], public_base_url="https://example.invalid/bucket")
        self.assertEqual(catalog["type"], "Catalog")
        self.assertEqual(catalog["uk_wsr:item_count"], 1)
        child_links = [link for link in catalog["links"] if link["rel"] == "child"]
        self.assertEqual(len(child_links), 1)
        self.assertIn(AGGREGATE_COLLECTION_ID, child_links[0]["href"])


if __name__ == "__main__":
    unittest.main()
