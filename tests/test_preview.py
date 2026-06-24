from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avocet_radar_toolkit.preview import (
    PreviewRequest,
    generate_preview,
    parse_palette_stops,
    preview_filename,
    preview_metadata_filename,
)
from avocet_radar_toolkit.export_types import FieldSelection
from avocet_radar_toolkit.geospatial import read_polar_field


def write_root_volume(path: Path) -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

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
        what.attrs["quantity"] = "DBZH"
        data_group.create_dataset("data", data=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])


def write_scaled_root_volume(path: Path) -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

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
        what.attrs["quantity"] = "DBZH"
        what.attrs["gain"] = 0.5
        what.attrs["offset"] = -32.0
        what.attrs["nodata"] = 255
        what.attrs["undetect"] = 0
        data_group.create_dataset("data", data=[[0, 1, 2], [3, 255, 4]], dtype="u1")


class PreviewTests(unittest.TestCase):
    def test_preview_filename_includes_dataset_quantity_and_palette(self):
        request = PreviewRequest(
            aggregate_path=Path("/tmp/source.h5"),
            radar="thurnham",
            date="20260614",
            pulse="lp",
            time="0000",
            quantity="DBZH/TEST",
            dataset="dataset1",
            palette="radar",
            output_dir=Path("/tmp/previews"),
        )
        self.assertEqual(preview_filename(request), "thurnham_20260614_lp_0000_dataset1_DBZH_TEST_radar.png")
        self.assertEqual(preview_metadata_filename(request), "thurnham_20260614_lp_0000_dataset1_DBZH_TEST_radar.json")

    def test_invalid_palette_falls_back_to_gray_filename(self):
        request = PreviewRequest(
            aggregate_path=Path("/tmp/source.h5"),
            radar="thurnham",
            date="20260614",
            pulse="lp",
            time="0000",
            quantity="DBZH",
            output_dir=Path("/tmp/previews"),
            palette="unknown",
        )
        self.assertTrue(preview_filename(request).endswith("_gray.png"))

    def test_preview_filename_hashes_cappi_filter(self):
        request = PreviewRequest(
            aggregate_path=Path("/tmp/source.h5"),
            radar="thurnham",
            date="20260614",
            pulse="lp",
            time="0000",
            quantity="DBZH",
            output_dir=Path("/tmp/previews"),
            filters={"cappi_height_m": 1500},
        )
        self.assertIn("_gray_", preview_filename(request))
        self.assertTrue(preview_filename(request).endswith(".png"))

    def test_parse_custom_palette_stops(self):
        self.assertEqual(
            parse_palette_stops("0:#000000,0.5:#28b450,1:#ffffff"),
            [(0.0, (0, 0, 0)), (0.5, (40, 180, 80)), (1.0, (255, 255, 255))],
        )
        with self.assertRaisesRegex(ValueError, "position"):
            parse_palette_stops("bad")

    def test_custom_palette_filename_includes_hash(self):
        request = PreviewRequest(
            aggregate_path=Path("/tmp/source.h5"),
            radar="thurnham",
            date="20260614",
            pulse="lp",
            time="0000",
            quantity="DBZH",
            output_dir=Path("/tmp/previews"),
            palette="custom",
            filters={"palette_stops": "0:#000000,1:#ffffff"},
        )
        self.assertIn("_custom_", preview_filename(request))

    def test_generate_preview_reuses_existing_image_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            request = PreviewRequest(
                aggregate_path=Path("/tmp/missing-source.h5"),
                radar="thurnham",
                date="20260614",
                pulse="lp",
                time="0000",
                quantity="DBZH",
                output_dir=output_dir,
            )
            expected = output_dir / preview_filename(request)
            expected.write_bytes(b"cached")
            (output_dir / preview_metadata_filename(request)).write_text("{}", encoding="utf-8")
            h5py = Mock()
            h5py.File.side_effect = AssertionError("cache hit should not open HDF5")
            with patch("avocet_radar_toolkit.preview.require_h5py", return_value=h5py), patch(
                "avocet_radar_toolkit.preview.require_pillow"
            ):
                self.assertEqual(generate_preview(request), expected)

    def test_generate_preview_reads_root_volume_layout(self):
        try:
            import PIL  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("preview dependencies are unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "20180401_polar_pl_radar05_aggregate_lp_0000.h5"
            write_root_volume(source)
            request = PreviewRequest(
                aggregate_path=source,
                radar="chenies",
                date="20180401",
                pulse="lp",
                time="0000",
                quantity="DBZH",
                output_dir=root / "previews",
            )
            output = generate_preview(request)

            self.assertTrue(output.exists())
            self.assertTrue((output.parent / preview_metadata_filename(request)).exists())

    def test_read_polar_field_reads_root_volume_layout(self):
        try:
            import numpy  # noqa: F401
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "20180401_polar_pl_radar05_aggregate_lp_0000.h5"
            write_root_volume(source)
            data, metadata = read_polar_field(
                source,
                "chenies",
                "20180401",
                FieldSelection(pulse="lp", time="0000", quantity="DBZH", dataset="1"),
            )

        self.assertEqual(list(data.shape), [2, 3])
        self.assertEqual(metadata.dataset, "dataset1")
        self.assertEqual(metadata.latitude, 51.0)
        self.assertEqual(metadata.longitude, -1.0)
        self.assertEqual(metadata.nbins, 3)
        self.assertEqual(metadata.nrays, 2)

    def test_read_polar_field_applies_odim_scaling_and_missing_values(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "20180401_polar_pl_radar05_aggregate_lp_0000.h5"
            write_scaled_root_volume(source)
            data, metadata = read_polar_field(
                source,
                "chenies",
                "20180401",
                FieldSelection(pulse="lp", time="0000", quantity="DBZH", dataset="1"),
            )

        self.assertTrue(np.isnan(data[0, 0]))
        self.assertEqual(float(data[0, 1]), -31.5)
        self.assertEqual(float(data[0, 2]), -31.0)
        self.assertTrue(np.isnan(data[1, 1]))
        self.assertTrue(metadata.attrs["avocet:odim_scaling_applied"])


if __name__ == "__main__":
    unittest.main()
