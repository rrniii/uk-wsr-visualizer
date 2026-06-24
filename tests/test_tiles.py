from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

from avocet_radar_toolkit.tiles import TileRequest, tile_manifest, tile_request_hash, tile_root, validate_tile_request


class TileTests(unittest.TestCase):
    def request(self) -> TileRequest:
        return TileRequest(
            aggregate_path=Path("/tmp/source.h5"),
            radar="thurnham",
            date="20260614",
            pulse="lp",
            time="0000",
            quantity="DBZH",
            dataset="dataset1",
            palette="radar",
            filters={"min_value": 5},
            output_dir=Path("/tmp/tiles"),
            tile_size=256,
            min_zoom=0,
            max_zoom=2,
        )

    def test_tile_root_is_deterministic_and_partitioned(self):
        request = self.request()
        root = tile_root(request)
        self.assertEqual(tile_request_hash(request), tile_request_hash(request))
        self.assertIn("radar=thurnham", root.parts)
        self.assertIn("date=20260614", root.parts)
        self.assertIn("pulse=lp", root.parts)
        self.assertIn("quantity=DBZH", root.parts)
        self.assertIn("time=0000", root.parts)

    def test_validate_tile_request(self):
        validate_tile_request(self.request())
        with self.assertRaisesRegex(ValueError, "requires pulse"):
            validate_tile_request(TileRequest(**{**self.request().__dict__, "pulse": ""}))
        with self.assertRaisesRegex(ValueError, "zoom range"):
            validate_tile_request(TileRequest(**{**self.request().__dict__, "min_zoom": 3, "max_zoom": 2}))

    @unittest.skipIf(Image is None, "Pillow is required for tile manifest serialization test")
    def test_tile_manifest_serializes_paths(self):
        request = self.request()
        with tempfile.TemporaryDirectory() as tmp:
            product = {
                "root_dir": tmp,
                "manifest_path": str(Path(tmp) / "tile-manifest.json"),
                "preview_path": str(Path(tmp) / "preview.png"),
                "tile_count": 5,
                "tile_size": 256,
                "min_zoom": 0,
                "max_zoom": 1,
                "url_template": "tiles/{z}/{x}/{y}.png",
                "source_width": 512,
                "source_height": 256,
                "bbox": [-1, 50, 1, 52],
                "request": request,
            }
            from avocet_radar_toolkit.tiles import TileProduct

            manifest = tile_manifest(TileProduct(**product))
            self.assertEqual(manifest["request"]["aggregate_path"], "/tmp/source.h5")
            self.assertEqual(manifest["request"]["output_dir"], "/tmp/tiles")


if __name__ == "__main__":
    unittest.main()
