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
            scans.append(BackgroundScan(dbzh, companion_fields={"VRADH": velocity, "SQIH": sqi}))

        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})
        self.assertEqual(model.shape, (3, 3))
        self.assertAlmostEqual(float(model.arrays["persistent_echo_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(float(model.arrays["near_zero_vrad_frequency"][1, 1]), 1.0)
        self.assertAlmostEqual(float(model.arrays["low_sqi_frequency"][1, 1]), 1.0)

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
            static_clutter_vrad_abs_max_ms=1.0,
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
            },
            config,
        )

        self.assertTrue(application.mask[1, 1])
        self.assertEqual(application.evidence_counts["masked"], 1)
        self.assertEqual(application.model["key"]["radar"], "test")
        self.assertEqual(loaded_from_inline.shape, loaded.shape)

    def test_background_model_preserves_stronger_current_signal(self):
        scans = []
        for value in (12.0, 13.0, 14.0):
            dbzh = np.full((2, 2), -5.0, dtype="float32")
            dbzh[0, 0] = value
            velocity = np.full((2, 2), 0.1, dtype="float32")
            scans.append(BackgroundScan(dbzh, companion_fields={"VRADH": velocity}))
        model = build_background_model(scans, key={"radar": "test", "pulse": "sp", "quantity": "DBZH"})

        current = np.asarray([[30.0, -5.0], [-5.0, -5.0]], dtype="float32")
        config = SimpleNamespace(
            background_min_samples=3,
            background_persistent_frequency_min=0.60,
            background_static_vrad_frequency_min=0.40,
            background_low_sqi_frequency_min=0.40,
            background_dbzh_excess_max_db=8.0,
            background_evidence_score_threshold=2,
            static_clutter_vrad_abs_max_ms=1.0,
            sqi_medium=0.45,
            rhohv_weak=0.75,
            zdr_min_db=-3.0,
            zdr_max_db=8.0,
        )
        application = apply_background_model(model, current, {"VRADH": np.full((2, 2), 0.1, dtype="float32")}, config)

        self.assertFalse(application.mask[0, 0])

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

    def test_default_background_model_resolver_matches_trained_metadata(self):
        metadata = SimpleNamespace(
            radar="druima-starraig",
            pulse="lp",
            quantity="DBZH",
            dataset="dataset1",
            elevation_deg=0.5,
        )

        path = default_background_model_path(metadata, quantity="DBZH")

        self.assertIsNotNone(path)
        self.assertTrue(path.exists())

        wrong_radar = SimpleNamespace(**(metadata.__dict__ | {"radar": "not-a-radar"}))
        self.assertIsNone(default_background_model_path(wrong_radar, quantity="DBZH"))


if __name__ == "__main__":
    unittest.main()
