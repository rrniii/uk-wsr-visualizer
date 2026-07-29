from pathlib import Path
from dataclasses import replace
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from uk_wsr_visualizer.export import ExportRequest, contour_feature_collection
from uk_wsr_visualizer.geospatial import (
    RadarGridMetadata,
    apply_polar_filters,
    apply_noise_floor_filter,
    dataset_nominal_height_m,
    field_selection_from_request,
    polar_to_cartesian,
    radar_bin_location,
    read_polar_field_with_companions,
    read_qc_v3_context_companions,
)
from uk_wsr_visualizer.export_types import FieldSelection
from uk_wsr_qc.qc import QCMaskFlag
from uk_wsr_qc.qc_v3 import QCMaskResultV3


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
        self.assertIsNotNone(location.height_m)
        self.assertGreater(location.height_m, 100.0)
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
    def test_qc_v3_auto_gathers_aligned_temporal_and_upper_fields(self):
        try:
            import h5py
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("h5py is unavailable")

        def write_volume(
            path: Path,
            *,
            lower_dbzh: float,
            upper_dbzh: float,
            velocity: float,
        ) -> None:
            with h5py.File(path, "w") as h5:
                where = h5.create_group("where")
                where.attrs["lat"] = 51.3
                where.attrs["lon"] = 0.6
                for index, (elevation, dbzh) in enumerate(
                    ((0.5, lower_dbzh), (1.0, upper_dbzh)),
                    start=1,
                ):
                    dataset = h5.create_group(f"dataset{index}")
                    dataset_where = dataset.create_group("where")
                    dataset_where.attrs["elangle"] = elevation
                    dataset_where.attrs["nrays"] = 4
                    dataset_where.attrs["nbins"] = 4
                    dataset_where.attrs["rstart"] = 0.0
                    dataset_where.attrs["rscale"] = 1000.0
                    for field_index, (quantity, value) in enumerate(
                        (("DBZH", dbzh), ("VRADH", velocity)),
                        start=1,
                    ):
                        field = dataset.create_group(
                            f"data{field_index}"
                        )
                        what = field.create_group("what")
                        what.attrs["quantity"] = quantity
                        field.create_dataset(
                            "data",
                            data=np.full(
                                (4, 4),
                                value,
                                dtype="float32",
                            ),
                        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous.h5"
            current = root / "current.h5"
            following = root / "next.h5"
            write_volume(
                previous,
                lower_dbzh=10.0,
                upper_dbzh=11.0,
                velocity=1.0,
            )
            write_volume(
                current,
                lower_dbzh=20.0,
                upper_dbzh=25.0,
                velocity=2.0,
            )
            write_volume(
                following,
                lower_dbzh=30.0,
                upper_dbzh=31.0,
                velocity=3.0,
            )
            selection = FieldSelection(
                pulse="lp",
                time="0005",
                quantity="DBZH",
                dataset="dataset1",
            )
            _, metadata, _ = read_polar_field_with_companions(
                current,
                "thurnham",
                "20260614",
                selection,
            )
            context = read_qc_v3_context_companions(
                current,
                "thurnham",
                "20260614",
                selection,
                metadata,
                previous_source=previous,
                previous_time="0000",
                next_source=following,
                next_time="0010",
            )

        self.assertEqual(
            sorted(context),
            [
                "__QC_V3_NEXT_DBZH",
                "__QC_V3_NEXT_VRAD",
                "__QC_V3_PREVIOUS_DBZH",
                "__QC_V3_PREVIOUS_VRAD",
                "__QC_V3_UPPER_ELEVATION_DBZH",
            ],
        )
        self.assertTrue(
            np.all(context["__QC_V3_PREVIOUS_DBZH"] == 10.0)
        )
        self.assertTrue(
            np.all(context["__QC_V3_NEXT_DBZH"] == 30.0)
        )
        self.assertTrue(
            np.all(context["__QC_V3_PREVIOUS_VRAD"] == 1.0)
        )
        self.assertTrue(
            np.all(context["__QC_V3_NEXT_VRAD"] == 3.0)
        )
        self.assertTrue(
            np.all(
                context["__QC_V3_UPPER_ELEVATION_DBZH"] == 25.0
            )
        )

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

        result = apply_polar_filters(
            data,
            self.metadata(),
            {"min_range_km": 1.0, "max_range_km": 3.0},
            return_metadata=True,
        )
        self.assertIsNotNone(result.qc)
        self.assertGreater(result.qc.flag_counts["USER_DOMAIN"], 0)
        self.assertTrue(result.qc.mask[0, 0] & int(QCMaskFlag.USER_DOMAIN))

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_apply_polar_filters_handles_azimuth_wraparound(self):
        data = np.ones((4, 4), dtype="float32")
        filtered = apply_polar_filters(data, self.metadata(), {"min_azimuth_deg": 300, "max_azimuth_deg": 60})
        self.assertTrue(np.isfinite(filtered[0, 0]))
        self.assertTrue(np.isfinite(filtered[3, 0]))
        self.assertTrue(np.isnan(filtered[1, 0]))

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_qc_v3_safe_is_the_fail_open_desktop_runtime(self):
        data = np.full((4, 4), 10.0, dtype="float32")
        companions = {
            "CI": np.full(data.shape, 1.0, dtype="float32"),
            "SQIH": np.full(data.shape, 0.8, dtype="float32"),
            "RHOHV": np.full(data.shape, 0.95, dtype="float32"),
            "VRADH": np.full(data.shape, 3.0, dtype="float32"),
        }
        result = apply_polar_filters(
            data,
            self.metadata(),
            {
                "noise_floor_enabled": True,
                "qc_mode": "qc_v3_safe",
                "qc_v3_runtime_mode": "safe",
            },
            return_metadata=True,
            companion_fields=companions,
        )

        self.assertIsInstance(result.qc, QCMaskResultV3)
        self.assertEqual(result.qc.config.runtime_mode.value, "safe")
        self.assertFalse(result.qc.runtime["learned_candidate_applied"])
        self.assertEqual(result.qc.runtime["bundle_qualification"], "not_requested")
        self.assertEqual(int(result.qc.removal_mask.sum()), 0)
        self.assertTrue(np.isfinite(result.values).all())
        sidecar = result.qc.to_dict()
        self.assertEqual(sidecar["finite_before"], 16)
        self.assertEqual(sidecar["finite_after"], 16)

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_qc_v3_never_uses_ci_or_long_range_noise_as_a_sole_rule(self):
        data = np.full((4, 4), 10.0, dtype="float32")
        companions = {
            "CI": np.full(data.shape, 20.0, dtype="float32"),
            "SQIH": np.full(data.shape, 0.9, dtype="float32"),
            "RHOHV": np.full(data.shape, 0.95, dtype="float32"),
            "VRADH": np.full(data.shape, 3.0, dtype="float32"),
            "LONG_RANGE_NOISE_DBC_H": np.full(
                data.shape,
                100.0,
                dtype="float32",
            ),
        }
        result = apply_polar_filters(
            data,
            self.metadata(),
            {
                "noise_floor_enabled": True,
                "qc_mode": "qc_v3_safe",
                "qc_v3_experimental_long_range_noise_enabled": True,
            },
            return_metadata=True,
            companion_fields=companions,
        )

        self.assertEqual(int(result.qc.removal_mask.sum()), 0)
        self.assertTrue(np.isfinite(result.values).all())
        self.assertFalse(
            result.qc.runtime["experimental_noise_fields_used"]
        )
        self.assertEqual(
            result.qc.runtime["ci_policy"],
            "auxiliary_evidence_only_never_a_label_or_sole_rule",
        )

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_qc_v3_validated_mode_fails_open_without_validated_bundle(self):
        data = np.full((4, 4), 10.0, dtype="float32")
        result = apply_polar_filters(
            data,
            self.metadata(),
            {
                "noise_floor_enabled": True,
                "qc_mode": "qc_v3_validated",
            },
            return_metadata=True,
            companion_fields={},
        )

        self.assertEqual(
            result.qc.runtime["bundle_qualification"],
            "missing_bundle",
        )
        self.assertFalse(result.qc.runtime["learned_candidate_applied"])
        self.assertEqual(int(result.qc.removal_mask.sum()), 0)
        self.assertTrue(np.isfinite(result.values).all())

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_qc_v3_masks_non_reflectivity_fields_from_dbzh_companion(self):
        velocity = np.arange(16, dtype="float32").reshape(4, 4)
        result = apply_polar_filters(
            velocity,
            replace(self.metadata(), quantity="VRADH"),
            {
                "noise_floor_enabled": True,
                "qc_mode": "qc_v3_safe",
            },
            return_metadata=True,
            companion_fields={
                "DBZH": np.full((4, 4), 10.0, dtype="float32"),
                "CI": np.full((4, 4), 1.0, dtype="float32"),
            },
        )

        self.assertEqual(
            result.qc.runtime["reflectivity_source_quantity"],
            "DBZH",
        )
        self.assertTrue(np.isfinite(result.values).all())
        self.assertTrue(np.array_equal(result.values, velocity))

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_qc_v3_fails_open_without_reflectivity_companion(self):
        velocity = np.arange(16, dtype="float32").reshape(4, 4)
        result = apply_polar_filters(
            velocity,
            replace(self.metadata(), quantity="VRADH"),
            {
                "noise_floor_enabled": True,
                "qc_mode": "qc_v3_safe",
            },
            return_metadata=True,
            companion_fields={
                "CI": np.full((4, 4), 20.0, dtype="float32"),
                "SQIH": np.zeros((4, 4), dtype="float32"),
            },
        )

        self.assertIsNone(
            result.qc.runtime["reflectivity_source_quantity"]
        )
        self.assertEqual(
            result.qc.runtime["reflectivity_source_error"],
            "missing_reflectivity_companion_fail_open",
        )
        self.assertTrue(np.isfinite(result.values).all())

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_apply_noise_floor_filter_masks_range_dependent_background(self):
        data = np.asarray(
            [
                [1.0, 6.0, 11.0, 16.0],
                [1.5, 6.5, 11.5, 16.5],
                [2.0, 7.0, 12.0, 17.0],
                [20.0, 30.0, 40.0, 50.0],
            ],
            dtype="float32",
        )
        result = apply_noise_floor_filter(
            data,
            {
                "noise_floor_enabled": True,
                "noise_floor_method": "estimated",
                "noise_floor_margin_db": 3.0,
                "noise_floor_operation": "mask",
                "noise_floor_percentile": 10.0,
                "noise_floor_window_bins": 1,
            },
        )

        self.assertTrue(result.noise_floor.enabled)
        self.assertIsNotNone(result.qc)
        self.assertGreater(result.qc.flag_counts["NOISE_FLOOR"], 0)
        self.assertGreater(result.noise_floor.masked_count, 0)
        self.assertTrue(np.isnan(result.values[0, 0]))
        self.assertTrue(np.isnan(result.values[2, 2]))
        self.assertTrue(np.isfinite(result.values[3, 3]))
        self.assertEqual(len(result.noise_floor.floor_profile), 4)

    @unittest.skipIf(np is None, "numpy is required for geospatial grid tests")
    def test_apply_noise_floor_filter_uses_reflectivity_texture_without_ncp(self):
        data = np.asarray(
            [
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 22.0, 10.0, 22.0, 22.0],
                [10.0, 10.0, 10.0, 22.0, 22.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
            ],
            dtype="float32",
        )

        result = apply_noise_floor_filter(
            data,
            {
                "noise_floor_enabled": True,
                "noise_floor_method": "estimated",
                "noise_floor_margin_db": 0.0,
                "noise_floor_operation": "mask",
                "noise_floor_percentile": 10.0,
                "noise_floor_window_bins": 1,
                "noise_floor_texture_enabled": True,
            },
        )

        self.assertTrue(np.isnan(result.values[1, 1]))
        self.assertTrue(np.isfinite(result.values[1, 3]))
        self.assertTrue(np.isfinite(result.values[1, 4]))
        self.assertTrue(np.isfinite(result.values[2, 3]))
        self.assertTrue(np.isfinite(result.values[2, 4]))
        self.assertEqual(result.noise_floor.texture_masked_count, 1)
        self.assertEqual(result.qc.flag_counts["TEXTURE_SPECKLE"], 1)

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
