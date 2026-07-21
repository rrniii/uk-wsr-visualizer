"""PyInstaller entry point for the Windows bundled server."""

import sys

from uk_wsr_visualizer.cli import main
from uk_wsr_visualizer.video_self_test import run_video_self_test


if __name__ == "__main__":
    if "--video-self-test" in sys.argv[1:]:
        print(run_video_self_test())
    else:
        main()
