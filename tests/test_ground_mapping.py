from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from uk_wsr_visualizer.geospatial import RadarGridMetadata
from uk_wsr_visualizer.ground_mapping import (
    beam_center_height_m,
    beam_ground_clearance_m,
    classify_refractivity_gradient,
    effective_earth_radius_factor_from_gradient,
    make_radar_sample_grid,
    partial_beam_blockage_fraction,
    refractivity_gradient_n_per_km,
    topographic_blockage_fraction,
    vertical_profile_detection_fraction,
)


@unittest.skipIf(np is None, "numpy is required for ground mapping tests")
class GroundMappingTests(unittest.TestCase):
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
            nbins=100,
            nrays=360,
        )

    def test_make_radar_sample_grid_reports_centres_and_area(self):
        grid = make_radar_sample_grid(self.metadata(), max_range_km=2, range_step_km=1, azimuth_step_deg=90)
        self.assertEqual(grid.range_km.shape, (4, 2))
        self.assertAlmostEqual(float(grid.range_km[0, 0]), 0.5)
        self.assertAlmostEqual(float(grid.azimuth_deg[0, 0]), 45.0)
        self.assertGreater(float(grid.cell_area_ha[0, 1]), float(grid.cell_area_ha[0, 0]))
        self.assertGreater(float(grid.latitude[0, 0]), 51.3)
        self.assertGreater(float(grid.longitude[0, 0]), 0.6)

    def test_beam_height_matches_expected_order_of_magnitude(self):
        height = float(beam_center_height_m(np.array([100_000.0]), elevation_deg=0.5, site_height_m=100.0)[0])
        self.assertGreater(height, 1400.0)
        self.assertLess(height, 1600.0)

    def test_beam_ground_clearance_uses_terrain(self):
        clearance = beam_ground_clearance_m(np.array([250.0]), np.array([10_000.0]), elevation_deg=0.5, site_height_m=100.0)
        self.assertLess(float(clearance[0]), 0.0)

    def test_partial_beam_blockage_fraction_bounds(self):
        terrain = np.array([-1.0, 0.0, 1.0])
        fraction = partial_beam_blockage_fraction(terrain, beam_height_m=np.array([0.0]), radius_m=np.array([1.0]))
        self.assertAlmostEqual(float(fraction[0]), 0.0)
        self.assertAlmostEqual(float(fraction[1]), 0.5)
        self.assertAlmostEqual(float(fraction[2]), 1.0)

    def test_topographic_blockage_can_accumulate_along_radial(self):
        terrain = np.array([[0.0, 1000.0, 0.0]])
        ranges = np.array([[10_000.0, 20_000.0, 30_000.0]])
        blockage = topographic_blockage_fraction(terrain, ranges, elevation_deg=0.5, site_height_m=0.0)
        self.assertGreater(float(blockage[0, 1]), 0.0)
        self.assertEqual(float(blockage[0, 2]), float(blockage[0, 1]))

    def test_vertical_profile_detection_fraction(self):
        fraction = vertical_profile_detection_fraction(
            range_m=np.array([10_000.0]),
            elevation_deg=0.5,
            terrain_height_m=np.array([0.0]),
            altitude_m_agl=np.array([0.0, 100.0, 200.0, 300.0]),
            profile_weight=np.ones(4),
            site_height_m=0.0,
            beam_width_deg=2.0,
        )
        self.assertGreaterEqual(float(fraction[0]), 0.0)
        self.assertLessEqual(float(fraction[0]), 1.0)

    def test_refractivity_gradient_and_classification(self):
        gradient = refractivity_gradient_n_per_km(
            height_m=np.array([0.0, 500.0, 1000.0]),
            pressure_hpa=np.array([1010.0, 955.0, 900.0]),
            temperature_c=np.array([10.0, 7.0, 4.0]),
            dewpoint_c=np.array([8.0, 4.0, 0.0]),
        )
        self.assertTrue(np.isfinite(gradient))
        self.assertEqual(classify_refractivity_gradient(-40.0), "standard_or_normal")
        self.assertEqual(classify_refractivity_gradient(-100.0), "super_refractive")
        self.assertGreater(effective_earth_radius_factor_from_gradient(-40.0), 1.0)


if __name__ == "__main__":
    unittest.main()
