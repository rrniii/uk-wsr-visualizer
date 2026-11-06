"""Install binary wheels compatible with the app's macOS 13 minimum."""

import argparse
from pathlib import Path
import platform
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin" or sys.version_info[:2] != (3, 11):
        raise SystemExit("Use a macOS Python 3.11 build environment")
    args.wheelhouse.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "pip", "download", "--dest", str(args.wheelhouse),
        "--platform", f"macosx_13_0_{platform.machine()}", "--only-binary=:all:",
        "numpy", "rasterio", "netCDF4", "h5py", "pillow", "imageio-ffmpeg",
    ], check=True)
    wheels = sorted(str(path) for path in args.wheelhouse.glob("*.whl"))
    subprocess.run([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", *wheels], check=True)


if __name__ == "__main__":
    main()
