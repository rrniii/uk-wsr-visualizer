"""Exercise an extracted server package in an isolated data directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


def fixture(root: Path) -> None:
    import h5py
    import numpy as np

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from uk_wsr_visualizer.catalog import CatalogItem, QuantityRecord, RawVolumeRecord, write_catalog

    volumes, records = [], []
    for clock in ("0000", "0005"):
        path = root / f"20260622_polar_pl_radar20_aggregate_lp_{clock}.h5"
        with h5py.File(path, "w") as h5:
            where = h5.create_group("where")
            where.attrs.update(lat=51.0, lon=-1.0, height=50.0)
            sweep = h5.create_group("dataset1")
            sweep.create_group("where").attrs.update(elangle=0.5, nbins=20, rscale=1000.0)
            data = sweep.create_group("data1")
            data.create_group("what").attrs.update(quantity="DBZH", gain=0.5, offset=-32.0, nodata=255, undetect=0)
            grid = np.full((360, 20), 100, dtype="uint8")
            grid[0, :2] = [255, 0]
            data.create_dataset("data", data=grid)
        volumes.append(RawVolumeRecord("lp", clock, str(path), path.name, path.stat().st_size, 0, ""))
        records.append(QuantityRecord("lp", clock, "1", "data", "1", "DBZH"))
    item = CatalogItem("thurnham", "20", "20260622", str(root), 0, 0, ["lp"], ["0000", "0005"], ["DBZH"], records, "", source_type="raw_volume_day", raw_volumes=volumes, quantities_by_pulse={"lp": ["DBZH"]}, times_by_pulse={"lp": ["0000", "0005"]})
    write_catalog(root / "catalog.json", [item])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--live", action="store_true", help="Use the published Castor Bay example instead of the local fixture")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    server = args.server.resolve()
    environment = {k: v for k, v in os.environ.items() if not k.startswith("UK_WSR_") and k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    if sys.platform == "darwin":
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    build = json.loads(subprocess.check_output([str(server), "--build-info"], env=environment, text=True))
    assert build["version"] and build["git_commit"] and build["qc_commit"], build
    subprocess.run([str(server), "--video-self-test"], env=environment, check=True, timeout=60)
    with tempfile.TemporaryDirectory(prefix="uk-wsr-package-smoke-") as directory:
        root = Path(directory)
        if not args.live:
            fixture(root)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment["UK_WSR_VISUALIZER_DATA_DIR"] = str(root)
        environment["UK_WSR_VISUALIZER_CATALOG"] = str(root / "catalog.json")
        if args.launcher:
            launcher_environment = dict(environment)
            launcher_environment.update({
                "UK_WSR_VISUALIZER_APP_SUPPORT": str(root / "launcher"),
                "UK_WSR_VISUALIZER_MAC_PORT": str(port),
                "UK_WSR_VISUALIZER_WINDOWS_PORT": str(port),
                "UK_WSR_VISUALIZER_LINUX_PORT": str(port),
                "XDG_CACHE_HOME": str(root / "launcher-cache"),
                "XDG_STATE_HOME": str(root / "launcher-state"),
            })
            subprocess.run([str(args.launcher.resolve()), "--self-test"], env=launcher_environment, check=True, timeout=150)
            assert not (root / "launcher" / "venv").exists(), "Launcher created an external Python environment"
        base = f"http://127.0.0.1:{port}"

        def request(path: str, payload=None):
            body = None if payload is None else json.dumps(payload).encode()
            with urlopen(Request(base + path, data=body, headers={"Content-Type": "application/json"}), timeout=180) as response:
                return json.load(response)

        with (root / "server.log").open("w") as log:
            process = subprocess.Popen([str(server), "api", "--host", "127.0.0.1", "--port", str(port)], env=environment, cwd=root, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError((root / "server.log").read_text())
                    try:
                        request("/api/ready")
                        break
                    except OSError:
                        time.sleep(0.25)
                else:
                    raise RuntimeError("Packaged server did not become ready")
                citation = request("/api/citation")
                assert citation["software"]["version"] == build["version"]
                assert citation["software"]["git_commit"] == build["git_commit"]
                radar, date, times = ("castor-bay", "20140918", ["1535", "1540"]) if args.live else ("thurnham", "20260622", ["0000", "0005"])
                selection = dict(radar=radar, date=date, pulse="lp", time=times[0], quantity="DBZH", dataset="1")
                ppi = request(f"/api/ppi/{radar}/{date}/lp/{times[0]}/DBZH?dataset=1&noise_floor_enabled=false")
                assert ppi["rows"] > 0 and ppi["columns"] > 0
                assert ppi["metadata"]["latitude"] and ppi["metadata"]["longitude"]
                source_hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.h5")}
                assert source_hashes, "The package did not load a source HDF5"
                exports = {}
                for format in ("png", "mp4", "geotiff", "cf_netcdf", "shapefile"):
                    job = request("/api/export", {**selection, "format": format, "times": times, "animation_full_day": False, "filters": {"noise_floor_enabled": False}})
                    assert job["status"] == "complete", job
                    output = Path(job["output_path"])
                    assert output.is_file() and output.stat().st_size > 0, job
                    manifest = request(f"/api/export/{job['job_id']}/manifest")
                    assert build["git_commit"] in json.dumps(manifest), manifest
                    exports[format] = {"bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
                for path, digest in source_hashes.items():
                    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, "Source HDF5 changed"
                report = {"build": build, "source": "public Castor Bay" if args.live else "synthetic fixture", "source_sha256": source_hashes, "ppi_shape": [ppi["rows"], ppi["columns"]], "exports": exports, "status": "passed"}
                if args.evidence:
                    args.evidence.parent.mkdir(parents=True, exist_ok=True)
                    args.evidence.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
                print(json.dumps({"status": "passed", "version": build["version"], "live": args.live, "exports": list(exports)}))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
