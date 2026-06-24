from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from avocet_radar_toolkit.math_ops import MathOperand, MathRequest, compute_math_array, validate_math_request


def request(operation: str = "difference", fmt: str = "png") -> MathRequest:
    operand = MathOperand(pulse="lp", time="0000", quantity="DBZH")
    return MathRequest(radar="thurnham", date="20260614", operation=operation, left=operand, right=operand, format=fmt)


class MathOpsTests(unittest.TestCase):
    def test_validate_math_request(self):
        validate_math_request(request("difference", "png"))
        with self.assertRaisesRegex(ValueError, "unsupported math operation"):
            validate_math_request(request("bogus", "png"))
        with self.assertRaisesRegex(ValueError, "unsupported math format"):
            validate_math_request(request("difference", "geotiff"))

    @unittest.skipIf(np is None, "numpy is required for math array tests")
    def test_compute_math_array_operations(self):
        left = np.array([[2, 4], [6, 8]], dtype="float32")
        right = np.array([[1, 2], [3, 4]], dtype="float32")
        self.assertEqual(compute_math_array(left, right, "difference").tolist(), [[1.0, 2.0], [3.0, 4.0]])
        self.assertEqual(compute_math_array(left, right, "sum").tolist(), [[3.0, 6.0], [9.0, 12.0]])
        self.assertEqual(compute_math_array(left, right, "ratio").tolist(), [[2.0, 2.0], [2.0, 2.0]])
        self.assertEqual(compute_math_array(left, right, "mean").tolist(), [[1.5, 3.0], [4.5, 6.0]])

    @unittest.skipIf(np is None, "numpy is required for math array tests")
    def test_compute_math_array_rejects_shape_mismatch(self):
        with self.assertRaisesRegex(ValueError, "different shapes"):
            compute_math_array(np.ones((2, 2)), np.ones((2, 3)), "difference")


if __name__ == "__main__":
    unittest.main()
