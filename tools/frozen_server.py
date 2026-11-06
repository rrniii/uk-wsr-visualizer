"""Shared entry point for every bundled desktop server."""

import json
import sys

from uk_wsr_visualizer.build_info import packaged_build_info
from uk_wsr_visualizer.cli import main
from uk_wsr_visualizer.video_self_test import run_video_self_test


if __name__ == "__main__":
    if sys.argv[1:] == ["--build-info"]:
        print(json.dumps(packaged_build_info(), sort_keys=True))
    elif sys.argv[1:] == ["--video-self-test"]:
        run_video_self_test()
        print(json.dumps({"video_encoder": "ok"}))
    else:
        main()
