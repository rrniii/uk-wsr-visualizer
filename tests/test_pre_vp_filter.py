from pathlib import Path
import tempfile
import unittest

from uk_wsr_visualizer.export_types import FieldSelection
from uk_wsr_visualizer.pre_vp_filter import (
    apply_pre_vp_filter,
    load_sweep_fields,
    preview_filter_results,
    resolve_pre_vp_settings,
)


class PreVpFilterTests(unittest.TestCase):
    def test_recommended_mask_sets_nan_across_same_shaped_fields(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        fields = {
            "DBZH": np.array([[0, 40, 42], [18, 45, 43], [22, 46, 44]], dtype="float32"),
            "VRADH": np.array([[2.0, 2.0, 2.0], [2.0, 2.0, 2.0], [2.0, 2.0, 2.0]], dtype="float32"),
            "SQIH": np.array([[0.10, 1.00, 1.00], [1.00, 1.00, 1.00], [1.00, 1.00, 1.00]], dtype="float32"),
            "NCPH": np.array([[1.00, 0.10, 1.00], [1.00, 1.00, 1.00], [1.00, 1.00, 1.00]], dtype="float32"),
            "CI": np.array([[7, 7, 7], [7, 4, 7], [7, 7, 7]], dtype="float32"),
            "RHOHV": np.ones((3, 3), dtype="float32"),
            "one_dim_profile": np.arange(3, dtype="float32"),
        }
        original_dbzh = fields["DBZH"].copy()

        result = apply_pre_vp_filter(fields, resolve_pre_vp_settings("current_ci_le4"))

        self.assertTrue(result.mask[0, 0])
        self.assertTrue(result.mask[0, 1])
        self.assertTrue(result.mask[1, 1])
        for name in ["DBZH", "VRADH", "SQIH", "NCPH", "CI", "RHOHV"]:
            self.assertTrue(np.isnan(result.fields[name][0, 0]), name)
            self.assertTrue(np.isnan(result.fields[name][0, 1]), name)
            self.assertTrue(np.isnan(result.fields[name][1, 1]), name)
        self.assertFalse(np.isnan(result.fields["one_dim_profile"]).any())
        self.assertFalse(np.isnan(fields["DBZH"]).any())
        self.assertTrue(np.array_equal(fields["DBZH"], original_dbzh))
        self.assertEqual(result.diagnostics.status, "success")
        self.assertIn("CI", result.diagnostics.fields_masked)
        self.assertGreater(result.diagnostics.masked_gate_count, 0)

    def test_aggressive_preset_has_validation_values(self):
        settings = resolve_pre_vp_settings("aggressive_ci_le4")

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.sqi_threshold, 0.30)
        self.assertEqual(settings.ncp_threshold, 0.30)
        self.assertEqual(settings.noise_floor_quantile, 0.10)
        self.assertEqual(settings.noise_floor_margin_db, 4.0)
        self.assertEqual(settings.clutter_persistence_min, 0.30)
        self.assertEqual(settings.ci_threshold, 4.0)
        self.assertEqual(settings.ci_bad_condition, "<=")
        self.assertEqual(settings.mask_action, "set_nan")

    def test_missing_optional_fields_are_diagnostic_warnings(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        fields = {
            "DBZH": np.array([[0, 40], [20, 42], [24, 45]], dtype="float32"),
            "SQIH": np.ones((3, 2), dtype="float32"),
            "VRADH": np.full((3, 2), 2.0, dtype="float32"),
        }

        result = apply_pre_vp_filter(fields, resolve_pre_vp_settings("current_ci_le4"))

        self.assertIn("NCP missing, skipped NCP component", result.diagnostics.warnings)
        self.assertIn("CI missing, skipped CI component", result.diagnostics.warnings)
        self.assertFalse(result.diagnostics.components["ncp"]["available"])
        self.assertFalse(result.diagnostics.components["ci"]["available"])

    def test_custom_ci_high_threshold_reports_destructive_warning(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        fields = {
            "DBZH": np.array([[0, 40], [20, 42], [24, 45]], dtype="float32"),
            "VRADH": np.full((3, 2), 2.0, dtype="float32"),
            "SQIH": np.ones((3, 2), dtype="float32"),
            "NCPH": np.ones((3, 2), dtype="float32"),
            "CI": np.array([[6, 1], [7, 1], [5, 1]], dtype="float32"),
        }
        settings = resolve_pre_vp_settings(
            "custom",
            overrides={"ci_bad_condition": ">=", "ci_threshold": 6},
        )

        result = apply_pre_vp_filter(fields, settings)

        self.assertIn("Validation found this setting too destructive for default production use.", result.diagnostics.warnings)
        self.assertTrue(result.mask[0, 0])
        self.assertTrue(result.mask[1, 0])

    def test_load_sweep_fields_decodes_odim_data_and_quality_groups(self):
        try:
            import h5py
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("h5py/numpy are unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "pvol.h5"
            with h5py.File(source, "w") as h5:
                dataset = h5.create_group("dataset1")
                for group_name, quantity, values in [
                    ("data1", "DBZH", [[0, 10], [20, 30]]),
                    ("data2", "VRADH", [[1, 2], [3, 4]]),
                    ("quality1", "SQIH", [[100, 200], [250, 255]]),
                    ("quality2", "NCPH", [[255, 255], [10, 255]]),
                    ("quality3", "CI", [[1, 7], [4, 5]]),
                ]:
                    group = dataset.create_group(group_name)
                    what = group.create_group("what")
                    what.attrs["quantity"] = quantity
                    what.attrs["gain"] = 0.01 if quantity in {"SQIH", "NCPH"} else 1.0
                    what.attrs["offset"] = 0.0
                    what.attrs["nodata"] = 255 if quantity in {"SQIH", "NCPH"} else -9999
                    what.attrs["undetect"] = -9998
                    group.create_dataset("data", data=np.array(values))

            fields, metadata = load_sweep_fields(source, FieldSelection(pulse="lp", time="0000", quantity="DBZH", dataset="1"))

        self.assertEqual(metadata["dataset"], "dataset1")
        self.assertEqual(sorted(fields), ["CI", "DBZH", "NCPH", "SQIH", "VRADH"])
        self.assertEqual(float(fields["DBZH"][0, 1]), 10.0)
        self.assertAlmostEqual(float(fields["SQIH"][0, 0]), 1.0)
        self.assertTrue(np.isnan(fields["SQIH"][1, 1]))

    def test_preview_results_include_expected_panels(self):
        try:
            import numpy as np
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("numpy is unavailable")

        fields = {
            "DBZH": np.array([[0, 40], [20, 42], [24, 45]], dtype="float32"),
            "VRADH": np.full((3, 2), 2.0, dtype="float32"),
            "SQIH": np.ones((3, 2), dtype="float32"),
            "NCPH": np.ones((3, 2), dtype="float32"),
            "CI": np.ones((3, 2), dtype="float32") * 7,
        }

        results = preview_filter_results(fields, resolve_pre_vp_settings("current_ci_le4"))

        self.assertEqual(set(results), {"raw", "current_combined", "current_ci_le4", "aggressive_ci_le4", "selected"})
        self.assertFalse(results["raw"].diagnostics.settings["enabled"])
        self.assertEqual(results["selected"].diagnostics.preset, "current_ci_le4")


if __name__ == "__main__":
    unittest.main()
