from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uk_wsr_visualizer.animation import (
    AnimationFrame,
    AnimationProduct,
    AnimationRequest,
    animation_manifest,
    animation_stem,
    validate_animation_request,
)


class AnimationTests(unittest.TestCase):
    def test_validate_animation_request(self):
        validate_animation_request(
            AnimationRequest(radar="thurnham", date="20260614", pulse="lp", quantity="DBZH", frame_delay_ms=100)
        )
        with self.assertRaisesRegex(ValueError, "pulse"):
            validate_animation_request(AnimationRequest(radar="thurnham", date="20260614", pulse="", quantity="DBZH"))
        with self.assertRaisesRegex(ValueError, "quantity"):
            validate_animation_request(AnimationRequest(radar="thurnham", date="20260614", pulse="lp", quantity=""))
        with self.assertRaisesRegex(ValueError, "frame_delay_ms"):
            validate_animation_request(AnimationRequest(radar="thurnham", date="20260614", pulse="lp", quantity="DBZH", frame_delay_ms=10))

    def test_animation_stem_and_manifest(self):
        request = AnimationRequest(
            radar="thurnham",
            date="20260614",
            pulse="lp",
            quantity="DBZH",
            dataset="dataset1",
            palette="radar",
            times=["0000", "0005"],
        )
        self.assertEqual(animation_stem(request), "thurnham_20260614_lp_dataset1_DBZH_radar_animation")
        product = AnimationProduct(
            request=request,
            output_path="/tmp/out.zip",
            manifest_path="/tmp/out.json",
            frame_count=1,
            frames=[AnimationFrame(index=0, time="0000", filename="frames/0000.png", metadata_filename="frames/0000.json")],
            created_at="2026-06-23T00:00:00Z",
        )
        manifest = animation_manifest(product)
        self.assertEqual(manifest["frame_count"], 1)
        self.assertEqual(manifest["frames"][0]["time"], "0000")


if __name__ == "__main__":
    unittest.main()
