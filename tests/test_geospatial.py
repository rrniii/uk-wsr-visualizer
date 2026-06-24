from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from avocet_radar_toolkit.export import ExportRequest, contour_feature_collection
from avocet_radar_toolkit.geospatial import (
    RadarGridMetadata,
    apply_polar_filters,
    dataset_nominal_height_m,
    field_selection_from_request,
    polar_to_cartesian,
    radar_bin_location,
)


class GeospatialTests(unittest.TestCase):
    def metadata(self) -> RadarGridMetadata:
        return RadarGridMetadata(
            radar="thurnham",
            date="20260614",
            pulse="lp",
            time="0000",
            quantity="DBZH",
            dataset="dataset1",
            latitude=51.3,
            longitude=0.6,
            height_m=100.0,
            elevation_deg=0.5,
            rstart_km=0.0,
            rscale_m=1000.0,
            nbins=4,
            nrays=4,
        )

    def test_metadata_reports_projected_and_geographic_bounds(self):
        metadata = self.metadata()
        self.assertIn("+proj=aeqd", metadata.projected_crs_proj4)
        self.assertEqual(metadata.projected_bbox(), [-4000.0, -4000.0, 4000.0, 4000.0])
        self.assertEqual(len(metadata.geographic_bbox()), 4)

    def test_radar_bin_location_reports_range_azimuth_and_lat_lon(self):
        location = radar_bin_location(self.metadata(), row=0, column=1)
        self.assertEqual(location.row, 0)
        self.assertEqual(location.column, 1)
        self.assertEqual(location.range_m, 1500.0)
        self.assertEqual(location.range_km, 1.5)
        self.assertEqual(location.azimuth_deg, 45.0)
        self.assertGreater(location.latitude, 51.3)
        self.assertGreater(location.longitude, 0.6)

    def test_radar_bin_location_clips_indices(self):
        location = radar_bin_location(self.metadata(), row=99, column=99)
        self.assertEqual(location.row, 3)
        self.assertEqual(location.column, 3)
        self.assertEqual(location.range_m, 3500.0)

    def test_dataset_nominal_height_prefers_direct_height_then_beam_estimate(self):
        self.assertEqual(dataset_nominal_height_m({"height": 100}, {"height": 1500}), 1500.0)
        height = dataset_nominal_height_m(
            {"height": 100},
            {"elangle": 1.0, "rstart": 0.0, "rscale": 1000.0, "nbins": 100},
        )
        self.assertGreater(height, 900.0)
        self.assertLess(height, 1100.0)

    def test_field_selection_reads_cappi_height_filter(self):
        request = ExportRequest(
            radar="thurnham",
            date="20260614",
            format="geotiff",
            pulse="lp",
            time="0000",
            quantity="DBZH",
            filters={"cappi_height_m": 1500},
        )
        selection = field_selection_from_request(request)
        self.assertEqual(selection.cappi_height_m, 1500.0)

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_apply_polar_filters_masks_range_azimuth_and_value(self):
        data = np.arange(16, dtype="float32").reshape(4, 4)
        filtered = apply_polar_filters(
            data,
            self.metadata(),
            {
                "min_range_km": 1.0,
                "max_range_km": 3.0,
                "min_azimuth_deg": 0.0,
                "max_azimuth_deg": 90.0,
                "min_value": 1.0,
                "max_value": 2.0,
            },
        )
        self.assertTrue(np.isfinite(filtered[0, 1]))
        self.assertTrue(np.isfinite(filtered[0, 2]))
        self.assertTrue(np.isnan(filtered[0, 0]))
        self.assertTrue(np.isnan(filtered[1, 1]))

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_apply_polar_filters_handles_azimuth_wraparound(self):
        data = np.ones((4, 4), dtype="float32")
        filtered = apply_polar_filters(data, self.metadata(), {"min_azimuth_deg": 300, "max_azimuth_deg": 60})
        self.assertTrue(np.isfinite(filtered[0, 0]))
        self.assertTrue(np.isfinite(filtered[3, 0]))
        self.assertTrue(np.isnan(filtered[1, 0]))

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_polar_to_cartesian_has_projected_metadata(self):
        data = np.arange(16, dtype="float32").reshape(4, 4)
        cartesian = polar_to_cartesian(data, self.metadata(), pixel_size_m=1000)
        self.assertEqual(cartesian.values.shape, (8, 8))
        self.assertIn("+proj=aeqd", cartesian.metadata.projected_crs_proj4)
        self.assertEqual(len(cartesian.metadata.geographic_bbox()), 4)

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_contour_feature_collection(self):
        data = np.arange(16, dtype="float32").reshape(4, 4)
        cartesian = polar_to_cartesian(data, self.metadata(), pixel_size_m=1000)
        collection = contour_feature_collection(
            cartesian,
            ExportRequest(
                radar="thurnham",
                date="20260614",
                format="geojson",
                pulse="lp",
                time="0000",
                quantity="DBZH",
                filters={"levels": [5.0], "max_segments": 1000},
            ),
        )
        self.assertEqual(collection["type"], "FeatureCollection")
        self.assertTrue(collection["features"])
        self.assertEqual(collection["features"][0]["geometry"]["type"], "MultiLineString")


if __name__ == "__main__":
    unittest.main()
