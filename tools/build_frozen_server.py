"""Freeze the desktop server and record its source and dependency identity."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
QC_COMMIT = "10f05f615c8ea9c5924fac7d4fa00a6d8fb21cae"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    paths = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    ).split(b"\0")
    for name in sorted(set(paths)):
        if not name:
            continue
        path = root / os.fsdecode(name)
        if path.is_file():
            digest.update(name + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def source_is_dirty(root: Path) -> bool:
    if git(root, "status", "--porcelain", "--untracked-files=no"):
        return True
    names = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "--others", "--exclude-standard"]).split(b"\0")
    return any(name and (root / os.fsdecode(name)).is_file() for name in names)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qc-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=ROOT / "build" / "frozen-server")
    parser.add_argument("--target-arch", choices=["arm64", "x86_64"])
    parser.add_argument("--codesign-identity")
    args = parser.parse_args()
    qc_root = args.qc_root.resolve()
    if git(qc_root, "rev-parse", "HEAD") != QC_COMMIT or git(qc_root, "status", "--porcelain", "--", "src", "pyproject.toml"):
        raise SystemExit(f"QC checkout must be clean at {QC_COMMIT}")
    installed_qc = metadata.distribution("uk-wsr-qc")
    direct_url = json.loads(installed_qc.read_text("direct_url.json") or "{}")
    if direct_url.get("url") != qc_root.as_uri():
        raise SystemExit("Install the pinned QC checkout into the build environment first")
    args.work.mkdir(parents=True, exist_ok=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    payload = {
        "schema": "uk-wsr-build-v1",
        "version": version,
        "git_commit": git(ROOT, "rev-parse", "HEAD"),
        "source_dirty": source_is_dirty(ROOT),
        "source_sha256": source_digest(ROOT),
        "qc_commit": QC_COMMIT,
        "platform": sys.platform,
        "architecture": args.target_arch or platform.machine(),
        "python": platform.python_version(),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "dependencies": {d.metadata["Name"]: d.version for d in metadata.distributions()},
    }
    manifest = args.work / "build-info.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "uk-wsr-visualizer-server", "--paths", str(ROOT / "src"), "--distpath", str(args.output),
        "--workpath", str(args.work / "work"), "--specpath", str(args.work),
        "--add-data", f"{manifest}{os.pathsep}uk_wsr_visualizer",
        "--collect-data", "uk_wsr_visualizer", "--collect-all", "uk_wsr_qc",
        "--collect-all", "imageio", "--collect-all", "imageio_ffmpeg",
        "--collect-all", "rasterio", "--collect-all", "netCDF4",
        "--hidden-import", "h5py", "--hidden-import", "shapefile",
        "--hidden-import", "uvicorn.logging", "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "PIL._tkinter_finder",
    ]
    if args.target_arch:
        command += ["--target-arch", args.target_arch]
    if args.codesign_identity:
        command += ["--codesign-identity", args.codesign_identity]
    if sys.platform == "darwin":
        options = command[5:]
        for flag in ("--distpath", "--workpath"):
            index = options.index(flag)
            del options[index:index + 2]
        subprocess.run([sys.executable, "-m", "PyInstaller.utils.cliutils.makespec", *options, str(ROOT / "tools" / "frozen_server.py")], cwd=ROOT, check=True)
        spec = args.work / "uk-wsr-visualizer-server.spec"
        # BUNDLE relocates native libraries into a layout macOS can sign.
        with spec.open("a") as handle:
            handle.write(f"\napp = BUNDLE(coll, name='UKWSRServer.app', bundle_identifier='uk.ac.ncas.uk-wsr-visualizer.server', version={version!r}, info_plist={{'LSBackgroundOnly': True, 'LSMinimumSystemVersion': '13.0'}})\n")
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(args.output), "--workpath", str(args.work / "work"), str(spec)], cwd=ROOT, check=True)
    else:
        subprocess.run(command + [str(ROOT / "tools" / "frozen_server.py")], cwd=ROOT, check=True)
    (args.output / "uk-wsr-visualizer-server" / "build-info.json").write_bytes(manifest.read_bytes())


if __name__ == "__main__":
    main()
