from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from uk_wsr_visualizer.export_types import FieldSelection
from uk_wsr_visualizer.background_model import BackgroundScan, build_background_model, save_background_model
from uk_wsr_visualizer.geospatial import apply_polar_filters, read_polar_field_with_companions
from uk_wsr_visualizer.qc import QCConfig, QCMaskFlag, build_qc_mask, qc_config_from_filters


def write_companion_volume(path: Path) -> None:
    try:
        import h5py
    except ImportError:  # pragma: no cover
        raise unittest.SkipTest("h5py is unavailable")

    data = np.full((4, 4), 20.0, dtype="float32")
    sqi = np.ones((4, 4), dtype="float32")
    rhohv = np.ones((4, 4), dtype="float32")
    sqi[1, 1] = 0.1
    rhohv[1, 1] = 0.4
    with h5py.File(path, "w") as h5:
        where = h5.create_group("where")
        where.attrs["lat"] = 51.0
        where.attrs["lon"] = -1.0
        dataset = h5.create_group("dataset1")
        dataset_where = dataset.create_group("where")
        dataset_where.attrs["elangle"] = 0.5
        dataset_where.attrs["nbins"] = 4
        dataset_where.attrs["rscale"] = 1000.0
        for index, (quantity, values) in enumerate((("DBZH", data), ("SQIH", sqi), ("RHOHV", rhohv)), start=1):
            data_group = dataset.create_group(f"data{index}")
            what = data_group.create_group("what")
            what.attrs["quantity"] = quantity
            data_group.create_dataset("data", data=values)


@unittest.skipIf(np is None, "numpy is required for QC tests")
class QCMaskTests(unittest.TestCase):
    def test_build_qc_mask_records_no_data_and_user_domain(self):
        data = np.asarray([[1.0, np.nan], [2.0, 3.0]], dtype="float32")
        domain_mask = np.asarray([[False, False], [True, False]])

        result = build_qc_mask(data, config=QCConfig(), domain_mask=domain_mask)

        self.assertEqual(result.flag_counts["NO_DATA"], 1)
        self.assertEqual(result.flag_counts["USER_DOMAIN"], 1)
        self.assertTrue(result.mask[1, 0] & int(QCMaskFlag.USER_DOMAIN))
        self.assertTrue(np.isnan(result.values[1, 0]))
        self.assertTrue(np.isfinite(result.values[0, 0]))

    def test_build_qc_mask_records_noise_floor_and_texture(self):
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

        result = build_qc_mask(
            data,
            config=QCConfig(
                mode="display_standard",
                noise_floor_enabled=True,
                noise_floor_margin_db=0.0,
                noise_floor_window_bins=1,
                texture_enabled=True,
            ),
        )

        self.assertGreater(result.flag_counts["NOISE_FLOOR"], 0)
        self.assertEqual(result.flag_counts["TEXTURE_SPECKLE"], 1)
        self.assertTrue(result.mask[1, 1] & int(QCMaskFlag.TEXTURE_SPECKLE))
        self.assertTrue(np.isnan(result.values[1, 1]))
        self.assertTrue(np.isfinite(result.values[1, 3]))

    def test_signal_preserving_mode_does_not_mask_low_snr_alone(self):
        data = np.full((5, 5), 10.0, dtype="float32")

        result = build_qc_mask(
            data,
            config=QCConfig(
                mode="signal_preserving",
                noise_floor_enabled=True,
                noise_floor_margin_db=6.0,
                noise_floor_hard_mask=False,
                noise_floor_window_bins=1,
                texture_enabled=True,
                companion_qc_near_noise_only=True,
                rhohv_low_is_noise_evidence=False,
            ),
        )

        self.assertEqual(result.flag_counts["NOISE_FLOOR"], 0)
        self.assertEqual(result.masked_count, 0)
        self.assertEqual(result.finite_after, result.finite_before)

    def test_build_qc_mask_records_static_clutter_from_velocity(self):
        data = np.full((4, 4), 12.0, dtype="float32")
        velocity = np.full((4, 4), 4.0, dtype="float32")
        velocity[:2, :2] = 0.2

        result = build_qc_mask(
            data,
            companion_fields={"VRADH": velocity},
            config=QCConfig(
                mode="vp_standard",
                noise_floor_enabled=True,
                noise_floor_margin_db=-20.0,
                noise_floor_window_bins=1,
                static_clutter_enabled=True,
                static_clutter_min_neighbors=2,
            ),
        )

        self.assertGreaterEqual(result.flag_counts["STATIC_CLUTTER"], 4)
        self.assertTrue(result.mask[0, 0] & int(QCMaskFlag.STATIC_CLUTTER))
        self.assertTrue(np.isnan(result.values[0, 0]))
        self.assertTrue(np.isfinite(result.values[3, 3]))

    def test_build_qc_mask_records_learned_background_clutter(self):
        scans = []
        for value in (12.0, 13.0, 14.0):
            dbzh = np.full((3, 3), -5.0, dtype="float32")
            dbzh[1, 1] = value
            velocity = np.full((3, 3), 4.0, dtype="float32")
            velocity[1, 1] = 0.2
            scans.append(BackgroundScan(dbzh, companion_fields={"VRADH": velocity}))
        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})

        with tempfile.TemporaryDirectory() as tmp:
            model_path, _ = save_background_model(model, Path(tmp) / "background.npz")
            current = np.full((3, 3), -5.0, dtype="float32")
            current[1, 1] = 13.5
            velocity = np.full((3, 3), 4.0, dtype="float32")
            velocity[1, 1] = 0.1
            result = build_qc_mask(
                current,
                companion_fields={"VRADH": velocity},
                config=QCConfig(
                    background_model_enabled=True,
                    background_model_path=str(model_path),
                    background_min_samples=3,
                    background_evidence_score_threshold=2,
                    noise_floor_enabled=False,
                    texture_enabled=False,
                ),
            )

        self.assertEqual(result.flag_counts["BACKGROUND_CLUTTER"], 1)
        self.assertTrue(result.mask[1, 1] & int(QCMaskFlag.BACKGROUND_CLUTTER))
        self.assertTrue(np.isnan(result.values[1, 1]))
        self.assertEqual(result.background_model["masked_count"], 1)
        self.assertEqual(result.background_model["model"]["key"]["radar"], "test")

    def test_build_qc_mask_records_dualpol_companion_qc(self):
        data = np.full((4, 4), 20.0, dtype="float32")
        sqi = np.ones((4, 4), dtype="float32")
        rhohv = np.ones((4, 4), dtype="float32")
        sqi[1, 1] = 0.1
        rhohv[1, 1] = 0.4

        result = build_qc_mask(
            data,
            companion_fields={"SQIH": sqi, "RHOHV": rhohv},
            config=QCConfig(
                mode="vp_standard",
                noise_floor_enabled=True,
                noise_floor_margin_db=0.0,
                noise_floor_hard_mask=False,
                noise_floor_window_bins=1,
                companion_qc_enabled=True,
                companion_qc_near_noise_only=True,
                rhohv_low_is_noise_evidence=False,
            ),
        )

        self.assertEqual(result.flag_counts["DUALPOL_QC"], 1)
        self.assertTrue(result.mask[1, 1] & int(QCMaskFlag.DUALPOL_QC))
        self.assertTrue(np.isnan(result.values[1, 1]))
        self.assertTrue(np.isfinite(result.values[0, 0]))

    def test_read_polar_field_with_companions_feeds_qc_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "pvol.h5"
            write_companion_volume(source)
            data, metadata, companions = read_polar_field_with_companions(
                source,
                "chenies",
                "20180401",
                FieldSelection(pulse="lp", time="0000", quantity="DBZH", dataset="1"),
            )

        self.assertEqual(sorted(companions), ["DBZH", "RHOHV", "SQIH"])
        result = apply_polar_filters(
            data,
            metadata,
            {
                "qc_mode": "signal_preserving",
                "noise_floor_margin_db": 0.0,
                "noise_floor_window_bins": 1,
            },
            return_metadata=True,
            companion_fields=companions,
        )

        self.assertEqual(result.qc.flag_counts["DUALPOL_QC"], 1)
        self.assertEqual(result.qc.companion_quantities, ["DBZH", "RHOHV", "SQIH"])
        self.assertTrue(result.qc.mask[1, 1] & int(QCMaskFlag.DUALPOL_QC))

    def test_qc_config_from_filters_maps_legacy_noise_filter(self):
        config = qc_config_from_filters(
            {
                "noise_floor_enabled": True,
                "noise_floor_margin_db": 0.0,
                "noise_floor_percentile": 5.0,
                "noise_floor_window_bins": 1,
                "noise_floor_texture_db": 0.0,
            }
        )

        self.assertEqual(config.mode, "display_standard")
        self.assertTrue(config.noise_floor_enabled)
        self.assertEqual(config.noise_floor_margin_db, 0.0)
        self.assertEqual(config.noise_floor_percentile, 5.0)
        self.assertEqual(config.noise_floor_window_bins, 1)
        self.assertEqual(config.texture_threshold_db, 0.0)

    def test_qc_config_from_filters_maps_signal_preserving_mode(self):
        config = qc_config_from_filters({"qc_mode": "signal_preserving"})

        self.assertEqual(config.mode, "signal_preserving")
        self.assertTrue(config.noise_floor_enabled)
        self.assertEqual(config.noise_floor_margin_db, 0.0)
        self.assertFalse(config.noise_floor_hard_mask)
        self.assertTrue(config.companion_qc_enabled)
        self.assertTrue(config.static_clutter_enabled)
        self.assertTrue(config.companion_qc_near_noise_only)
        self.assertFalse(config.rhohv_low_is_noise_evidence)

    def test_qc_config_keeps_vp_standard_as_upper_bound_diagnostic(self):
        config = qc_config_from_filters({"qc_mode": "vp_standard"})

        self.assertEqual(config.mode, "vp_standard")
        self.assertTrue(config.noise_floor_enabled)
        self.assertEqual(config.noise_floor_margin_db, 6.0)
        self.assertTrue(config.noise_floor_hard_mask)
        self.assertTrue(config.companion_qc_enabled)
        self.assertTrue(config.static_clutter_enabled)
        self.assertFalse(config.companion_qc_near_noise_only)
        self.assertTrue(config.rhohv_low_is_noise_evidence)


if __name__ == "__main__":
    unittest.main()
