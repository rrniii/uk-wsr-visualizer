from pathlib import Path
from types import SimpleNamespace
from base64 import b64encode
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from uk_wsr_visualizer.background_model import (
    BackgroundScan,
    apply_background_model,
    build_background_model,
    default_background_model_path,
    load_background_model,
    save_background_model,
)


@unittest.skipIf(np is None, "numpy is required for background model tests")
class BackgroundModelTests(unittest.TestCase):
    def test_build_save_load_and_apply_background_model(self):
        scans = []
        for value in (12.0, 13.0, 14.0):
            dbzh = np.full((3, 3), -5.0, dtype="float32")
            dbzh[1, 1] = value
            velocity = np.full((3, 3), 4.0, dtype="float32")
            velocity[1, 1] = 0.1
            sqi = np.ones((3, 3), dtype="float32")
            sqi[1, 1] = 0.2
            ci = np.full((3, 3), 7.0, dtype="float32")
            ci[1, 1] = 1.0
            scans.append(BackgroundScan(dbzh, companion_fields={"VRADH": velocity, "SQIH": sqi, "CI": ci}))

        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})
        self.assertEqual(model.shape, (3, 3))
        self.assertAlmostEqual(float(model.arrays["persistent_echo_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(float(model.arrays["near_zero_vrad_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(float(model.arrays["low_ci_near_zero_vrad_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(float(model.arrays["low_sqi_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(float(model.arrays["low_ci_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(
            float(model.arrays["low_ci_persistent_echo_frequency"][1, 1]),
            1.0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            npz_path, json_path = save_background_model(model, Path(tmp) / "background.npz")
            self.assertTrue(npz_path.exists())
            self.assertTrue(json_path.exists())
            manifest = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("inline_arrays", manifest)
            self.assertIn("sample_count", manifest["inline_arrays"])
            loaded = load_background_model(json_path)
            npz_path.unlink()
            loaded_from_inline = load_background_model(json_path)

        config = SimpleNamespace(
            background_min_samples=3,
            background_persistent_frequency_min=0.60,
            background_static_vrad_frequency_min=0.40,
            background_low_sqi_frequency_min=0.40,
            background_dbzh_excess_max_db=8.0,
            background_evidence_score_threshold=2,
            background_current_vrad_abs_max_ms=0.5,
            background_learned_low_ci_frequency_min=0.6,
            background_require_current_ci=True,
            background_require_current_vrad=True,
            background_require_training_diversity=False,
            ci_clutter_max_db=2.0,
            sqi_medium=0.45,
            rhohv_weak=0.75,
            zdr_min_db=-3.0,
            zdr_max_db=8.0,
        )
        current = np.full((3, 3), -5.0, dtype="float32")
        current[1, 1] = 13.5
        application = apply_background_model(
            loaded,
            current,
            {
                "VRADH": np.asarray([[4, 4, 4], [4, 0.2, 4], [4, 4, 4]], dtype="float32"),
                "SQIH": np.asarray([[1, 1, 1], [1, 0.3, 1], [1, 1, 1]], dtype="float32"),
                "CI": np.asarray([[7, 7, 7], [7, 1, 7], [7, 7, 7]], dtype="float32"),
            },
            config,
        )

        self.assertTrue(application.mask[1, 1])
        self.assertEqual(application.evidence_counts["masked"], 1)
        self.assertEqual(application.model["key"]["radar"], "test")
        self.assertEqual(loaded_from_inline.shape, loaded.shape)

    def test_ci_conditioned_static_velocity_ignores_atmospheric_crossings(self):
        scans = []
        for index in range(10):
            is_atmospheric = index >= 6
            scans.append(
                BackgroundScan(
                    np.asarray(
                        [[-5.0 if is_atmospheric else 12.0]],
                        dtype="float32",
                    ),
                    companion_fields={
                        "VRADH": np.asarray(
                            [[8.0 if is_atmospheric else 0.1]],
                            dtype="float32",
                        ),
                        "CI": np.asarray(
                            [[7.0 if is_atmospheric else 1.0]],
                            dtype="float32",
                        ),
                    },
                )
            )
        model = build_background_model(
            scans,
            key={"radar": "test", "pulse": "lp", "quantity": "DBZH"},
        )

        self.assertAlmostEqual(
            float(model.arrays["near_zero_vrad_frequency"][0, 0]),
            0.6,
        )
        self.assertAlmostEqual(
            float(model.arrays["persistent_echo_frequency"][0, 0]),
            0.6,
        )
        self.assertEqual(
            float(model.arrays["low_ci_vrad_sample_count"][0, 0]),
            6.0,
        )
        self.assertAlmostEqual(
            float(model.arrays["low_ci_near_zero_vrad_frequency"][0, 0]),
            1.0,
        )
        self.assertAlmostEqual(
            float(model.arrays["low_ci_persistent_echo_frequency"][0, 0]),
            1.0,
        )
        application = apply_background_model(
            model,
            np.asarray([[12.0]], dtype="float32"),
            {
                "VRADH": np.asarray([[0.1]], dtype="float32"),
                "CI": np.asarray([[1.0]], dtype="float32"),
            },
            SimpleNamespace(
                background_min_samples=10,
                background_persistent_frequency_min=0.95,
                background_static_vrad_frequency_min=0.80,
                background_static_conditioned_min_fraction=0.25,
                background_dbzh_excess_max_db=3.0,
                background_current_vrad_abs_max_ms=0.5,
                background_learned_low_ci_frequency_min=0.50,
                background_require_current_ci=True,
                background_require_current_vrad=True,
                background_require_training_diversity=False,
                ci_clutter_max_db=2.0,
            ),
        )

        self.assertTrue(application.mask[0, 0])
        self.assertEqual(
            application.evidence_counts[
                "learned_static_vrad_ci_conditioned"
            ],
            1,
        )
        self.assertEqual(
            application.evidence_counts[
                "learned_persistent_ci_conditioned"
            ],
            1,
        )

    def test_ci_conditioned_background_fails_open_without_support(self):
        scans = [
            BackgroundScan(
                np.asarray([[12.0]], dtype="float32"),
                companion_fields={
                    "VRADH": np.asarray([[0.1]], dtype="float32"),
                    "CI": np.asarray([[1.0]], dtype="float32"),
                },
            )
            for _ in range(3)
        ]
        model = build_background_model(
            scans,
            key={"radar": "test", "pulse": "lp", "quantity": "DBZH"},
        )
        application = apply_background_model(
            model,
            np.asarray([[12.0]], dtype="float32"),
            {
                "VRADH": np.asarray([[0.1]], dtype="float32"),
                "CI": np.asarray([[1.0]], dtype="float32"),
            },
            SimpleNamespace(
                background_min_samples=3,
                background_conditioned_min_samples=4,
                background_persistent_frequency_min=0.95,
                background_static_vrad_frequency_min=0.80,
                background_dbzh_excess_max_db=3.0,
                background_current_vrad_abs_max_ms=0.5,
                background_require_current_ci=True,
                background_require_current_vrad=True,
                background_require_training_diversity=False,
                ci_clutter_max_db=2.0,
            ),
        )

        self.assertFalse(application.mask[0, 0])
        self.assertEqual(
            application.evidence_counts["learned_conditioned_support"],
            0,
        )

    def test_background_model_preserves_stronger_current_signal(self):
        scans = []
        for value in (12.0, 13.0, 14.0):
            dbzh = np.full((2, 2), -5.0, dtype="float32")
            dbzh[0, 0] = value
            velocity = np.full((2, 2), 0.1, dtype="float32")
            scans.append(
                BackgroundScan(
                    dbzh,
                    companion_fields={"VRADH": velocity, "CI": np.full((2, 2), 1.0, dtype="float32")},
                )
            )
        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})

        current = np.asarray([[30.0, -5.0], [-5.0, -5.0]], dtype="float32")
        config = SimpleNamespace(
            background_min_samples=3,
            background_persistent_frequency_min=0.60,
            background_static_vrad_frequency_min=0.40,
            background_low_sqi_frequency_min=0.40,
            background_dbzh_excess_max_db=8.0,
            background_evidence_score_threshold=2,
            background_current_vrad_abs_max_ms=0.5,
            background_learned_low_ci_frequency_min=0.6,
            background_require_current_ci=True,
            background_require_current_vrad=True,
            background_require_training_diversity=False,
            ci_clutter_max_db=2.0,
            sqi_medium=0.45,
            rhohv_weak=0.75,
            zdr_min_db=-3.0,
            zdr_max_db=8.0,
        )
        application = apply_background_model(
            model,
            current,
            {
                "VRADH": np.full((2, 2), 0.1, dtype="float32"),
                "CI": np.full((2, 2), 1.0, dtype="float32"),
            },
            config,
        )

        self.assertFalse(application.mask[0, 0])

    def test_one_day_background_model_fails_open(self):
        metadata = SimpleNamespace(date="20260703", time="0000", dataset="dataset1")
        scans = []
        for value in (12.0, 13.0, 14.0):
            dbzh = np.full((2, 2), value, dtype="float32")
            scans.append(
                BackgroundScan(
                    dbzh,
                    metadata=metadata,
                    companion_fields={
                        "VRADH": np.full((2, 2), 0.1, dtype="float32"),
                        "CI": np.full((2, 2), 1.0, dtype="float32"),
                    },
                )
            )
        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})
        config = SimpleNamespace(
            background_require_training_diversity=True,
            background_min_training_dates=7,
            background_min_training_span_days=14,
        )

        application = apply_background_model(
            model,
            np.full((2, 2), 13.0, dtype="float32"),
            {
                "VRADH": np.full((2, 2), 0.1, dtype="float32"),
                "CI": np.full((2, 2), 1.0, dtype="float32"),
            },
            config,
        )

        self.assertFalse(application.qualified)
        self.assertEqual(application.reason, "insufficient_training_dates:1<7")
        self.assertFalse(application.mask.any())

    def test_multi_date_background_model_can_remove_confirmed_static_clutter(self):
        dates = ("20260701", "20260704", "20260707", "20260710", "20260713", "20260716", "20260719")
        scans = []
        for date in dates:
            dbzh = np.full((2, 2), -5.0, dtype="float32")
            dbzh[0, 0] = 12.0
            velocity = np.full((2, 2), 4.0, dtype="float32")
            velocity[0, 0] = 0.1
            ci = np.full((2, 2), 7.0, dtype="float32")
            ci[0, 0] = 1.0
            scans.append(
                BackgroundScan(
                    dbzh,
                    metadata=SimpleNamespace(date=date, time="0000", dataset="dataset1"),
                    companion_fields={"VRADH": velocity, "CI": ci},
                )
            )
        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})
        config = SimpleNamespace(
            background_min_samples=7,
            background_persistent_frequency_min=0.95,
            background_static_vrad_frequency_min=0.80,
            background_dbzh_excess_max_db=3.0,
            background_current_vrad_abs_max_ms=0.5,
            background_learned_low_ci_frequency_min=0.60,
            background_require_current_ci=True,
            background_require_current_vrad=True,
            background_require_training_diversity=True,
            background_min_training_dates=7,
            background_min_training_span_days=14,
            ci_clutter_max_db=2.0,
        )

        application = apply_background_model(
            model,
            np.asarray([[12.5, -5.0], [-5.0, -5.0]], dtype="float32"),
            {
                "VRADH": np.asarray([[0.1, 4.0], [4.0, 4.0]], dtype="float32"),
                "CI": np.asarray([[1.0, 7.0], [7.0, 7.0]], dtype="float32"),
            },
            config,
        )

        self.assertTrue(application.qualified)
        self.assertEqual(model.metadata["source_date_count"], 7)
        self.assertEqual(model.metadata["training_span_days"], 18)
        self.assertTrue(application.mask[0, 0])

    def test_load_quantized_inline_background_model(self):
        sample_count = np.asarray([[0, 50]], dtype="uint8")
        persistent = np.asarray([[0, 255]], dtype="uint8")
        dbzh_p90 = np.asarray([[-32768, 123]], dtype="<i2")
        manifest = {
            "schema": "uk_wsr_background_model",
            "schema_version": 1,
            "key": {"radar": "test", "pulse": "lp", "quantity": "DBZH"},
            "shape": [1, 2],
            "inline_arrays": {
                "sample_count": {
                    "dtype": "uint8",
                    "shape": [1, 2],
                    "encoding": "base64",
                    "scale": 1.0,
                    "offset": 0.0,
                    "data": b64encode(sample_count.tobytes()).decode("ascii"),
                },
                "persistent_echo_frequency": {
                    "dtype": "uint8",
                    "shape": [1, 2],
                    "encoding": "base64",
                    "scale": 1.0 / 255.0,
                    "offset": 0.0,
                    "data": b64encode(persistent.tobytes()).decode("ascii"),
                },
                "dbzh_p90": {
                    "dtype": "int16",
                    "shape": [1, 2],
                    "encoding": "base64",
                    "scale": 0.1,
                    "offset": 0.0,
                    "nan_sentinel": -32768,
                    "data": b64encode(dbzh_p90.tobytes()).decode("ascii"),
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "background.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            model = load_background_model(path)

        self.assertEqual(model.shape, (1, 2))
        self.assertAlmostEqual(float(model.arrays["sample_count"][0, 1]), 50.0)
        self.assertAlmostEqual(float(model.arrays["persistent_echo_frequency"][0, 1]), 1.0)
        self.assertTrue(np.isnan(model.arrays["dbzh_p90"][0, 0]))
        self.assertAlmostEqual(float(model.arrays["dbzh_p90"][0, 1]), 12.3, places=2)

    def test_default_background_model_resolver_rejects_legacy_packaged_model(self):
        metadata = SimpleNamespace(
            radar="druima-starraig",
            pulse="lp",
            quantity="DBZH",
            dataset="dataset1",
            elevation_deg=0.5,
        )

        path = default_background_model_path(metadata, quantity="DBZH")

        self.assertIsNone(path)

        wrong_radar = SimpleNamespace(**(metadata.__dict__ | {"radar": "not-a-radar"}))
        self.assertIsNone(default_background_model_path(wrong_radar, quantity="DBZH"))

    def test_default_background_model_resolver_requires_explicit_qc_v2_qualification(self):
        metadata = SimpleNamespace(
            radar="test-radar",
            pulse="lp",
            quantity="DBZH",
            dataset="dataset1",
            elevation_deg=0.5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            model_path = model_dir / "qualified.json"
            model_path.write_text("{}", encoding="utf-8")
            manifest = {
                "schema": "uk_wsr_background_model_manifest",
                "schema_version": 2,
                "models": [
                    {
                        "filename": model_path.name,
                        "radar": "test-radar",
                        "pulse": "lp",
                        "quantity": "DBZH",
                        "dataset": "dataset1",
                        "elevation_deg": 0.5,
                        "qc_version": "qc-v2",
                        "status": "qualified",
                        "eligible_for_default": True,
                        "qualification_reasons": [],
                    }
                ],
            }
            (model_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            resolved = default_background_model_path(
                metadata,
                quantity="DBZH",
                model_dir=model_dir,
            )

        self.assertEqual(resolved, model_path.resolve())

    def test_default_background_model_resolver_fails_closed_for_legacy_or_invalid_registry(self):
        metadata = SimpleNamespace(
            radar="test-radar",
            pulse="lp",
            quantity="DBZH",
            dataset="dataset1",
            elevation_deg=0.5,
        )
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            (model_dir / "model.json").write_text("{}", encoding="utf-8")
            legacy = {
                "schema": "uk_wsr_background_model_manifest",
                "schema_version": 1,
                "models": [
                    {
                        "filename": "model.json",
                        "radar": "test-radar",
                        "pulse": "lp",
                        "quantity": "DBZH",
                        "dataset": "dataset1",
                        "elevation_deg": 0.5,
                        "eligible_for_default": True,
                    }
                ],
            }
            (model_dir / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIsNone(
                default_background_model_path(metadata, quantity="DBZH", model_dir=model_dir)
            )

            legacy["schema_version"] = 2
            legacy["models"][0] |= {
                "status": "qualified",
                "qc_version": "qc-v1",
                "qualification_reasons": [],
            }
            (model_dir / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIsNone(
                default_background_model_path(metadata, quantity="DBZH", model_dir=model_dir)
            )


if __name__ == "__main__":
    unittest.main()
