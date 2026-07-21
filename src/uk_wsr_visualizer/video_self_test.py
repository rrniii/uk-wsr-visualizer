"""Small runtime check for the bundled MP4 encoder."""

from __future__ import annotations

import tempfile
from pathlib import Path


def run_video_self_test() -> Path:
    """Encode two tiny frames and return the resulting MP4 path.

    Packaging workflows invoke this through the bundled server executable. It
    proves that PyInstaller included both ``imageio`` and the FFmpeg binary.
    """

    import imageio.v2 as imageio
    import imageio_ffmpeg
    import numpy as np

    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not ffmpeg.is_file():
        raise RuntimeError(f"imageio-ffmpeg did not provide an executable: {ffmpeg}")

    with tempfile.TemporaryDirectory(prefix="uk-wsr-video-self-test-") as directory:
        output = Path(directory) / "encoder-smoke.mp4"
        first = np.zeros((16, 16, 3), dtype=np.uint8)
        second = np.full((16, 16, 3), 255, dtype=np.uint8)
        imageio.mimsave(output, [first, second], fps=2)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("imageio-ffmpeg did not create an MP4 output")
        return output
