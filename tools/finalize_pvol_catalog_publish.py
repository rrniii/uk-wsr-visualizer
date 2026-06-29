from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json
import os
import subprocess
import sys
import time

import h5py


AWS = "/home/users/rrniii/bin/aws"
BUCKET = "uk-wsr-visualizer-public"
ENDPOINT = "http://ncas-radar-o.s3.jc.rl.ac.uk"
PROFILE = "ncas-radar-o"
REGION = "us-east-1"
OBJECT_PREFIX = "ukmo-nimrod"
PVOL_BASE = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site")
PUBLIC_BASE_URL = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"
SPATIAL_SOURCE = "ODIM HDF5 /where attrs from latest staged source PVOL file"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def aws_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AWS_MAX_ATTEMPTS": "10",
            "AWS_RETRY_MODE": "adaptive",
            "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
            "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
        }
    )
    return env


def aws_base() -> list[str]:
    return [AWS, "--profile", PROFILE, "--region", REGION, "--endpoint-url", ENDPOINT]


def run(cmd: list[str]) -> None:
    log("run " + " ".join(cmd))
    proc = subprocess.run(cmd, text=True, env=aws_env())
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {cmd!r}")


def head_object(key: str) -> bool:
    proc = subprocess.run(
        aws_base() + ["s3api", "head-object", "--bucket", BUCKET, "--key", key, "--output", "json"],
        text=True,
        capture_output=True,
        env=aws_env(),
    )
    return proc.returncode == 0


def catalog_root(stage_root: Path) -> Path:
    return stage_root / OBJECT_PREFIX / "catalog" / "pvol"


def latest_spatial(root: Path, radar: str, date: str) -> dict[str, Any]:
    day_catalog = root / radar / date[:4] / date[4:6] / date[6:8] / "catalog.json"
    day = load_json(day_catalog)
    last_error: Exception | None = None
    for record in day.get("files", []):
        path = PVOL_BASE / radar / date[:4] / date / record["pulse"] / record["filename"]
        try:
            with h5py.File(path, "r") as handle:
                attrs = handle["where"].attrs
                spatial: dict[str, Any] = {
                    "latitude": float(attrs["lat"]),
                    "longitude": float(attrs["lon"]),
                    "source": SPATIAL_SOURCE,
                }
                if "height" in attrs:
                    spatial["height_m"] = float(attrs["height"])
                return spatial
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"could not extract spatial attrs for {radar}/{date}: {last_error}")


def patch_spatial(stage_root: Path, run_dir: Path) -> dict[str, Any]:
    root = catalog_root(stage_root)
    catalog_path = root / "catalog.json"
    coverage_path = root / "coverage.json"
    catalog = load_json(catalog_path)
    spatial_by_radar: dict[str, dict[str, Any]] = {}
    for radar_row in catalog.get("radars", []):
        radar = radar_row["radar"]
        spatial = latest_spatial(root, radar, radar_row["last_date"])
        radar_row["spatial"] = spatial
        spatial_by_radar[radar] = spatial
    updated_at = utc_now()
    catalog["spatial_updated_at"] = updated_at
    catalog["spatial_source"] = SPATIAL_SOURCE
    write_json(catalog_path, catalog)

    if coverage_path.exists():
        coverage = load_json(coverage_path)
        for radar_row in coverage.get("radars", []):
            radar = radar_row.get("radar")
            if radar in spatial_by_radar:
                radar_row["spatial"] = spatial_by_radar[radar]
        coverage["spatial_updated_at"] = updated_at
        coverage["spatial_source"] = SPATIAL_SOURCE
        write_json(coverage_path, coverage)

    payload = {
        "ok": True,
        "updated_at": updated_at,
        "source": SPATIAL_SOURCE,
        "radar_count": len(spatial_by_radar),
        "spatial_by_radar": spatial_by_radar,
    }
    write_json(run_dir / "pvol_catalog_spatial_update.json", payload)
    log(f"spatial_patch_complete radars={len(spatial_by_radar)}")
    return payload


def upload_root_last(stage_root: Path, run_dir: Path) -> dict[str, Any]:
    root = catalog_root(stage_root)
    dest = f"s3://{BUCKET}/{OBJECT_PREFIX}/catalog/pvol/"
    hold = run_dir / "root_hold"
    hold.mkdir(parents=True, exist_ok=True)
    held: list[tuple[Path, Path]] = []
    for path in [root / "catalog.json", root / "coverage.json"]:
        held_path = hold / path.name
        if held_path.exists():
            held_path.unlink()
        path.replace(held_path)
        held.append((held_path, path))
    try:
        run(
            aws_base()
            + [
                "s3",
                "sync",
                str(root) + "/",
                dest,
                "--acl",
                "public-read",
                "--only-show-errors",
                "--no-progress",
                "--exclude",
                "*.tmp",
            ]
        )
    finally:
        for held_path, path in held:
            if held_path.exists() and not path.exists():
                held_path.replace(path)
    run(
        aws_base()
        + [
            "s3",
            "cp",
            str(root / "coverage.csv"),
            dest + "coverage.csv",
            "--acl",
            "public-read",
            "--content-type",
            "text/csv",
            "--only-show-errors",
            "--no-progress",
        ]
    )
    run(
        aws_base()
        + [
            "s3",
            "cp",
            str(root / "coverage.json"),
            dest + "coverage.json",
            "--acl",
            "public-read",
            "--content-type",
            "application/json",
            "--only-show-errors",
            "--no-progress",
        ]
    )
    run(
        aws_base()
        + [
            "s3",
            "cp",
            str(root / "catalog.json"),
            dest + "catalog.json",
            "--acl",
            "public-read",
            "--content-type",
            "application/json",
            "--only-show-errors",
            "--no-progress",
        ]
    )
    payload = {"ok": True, "uploaded_at": utc_now(), "catalog_root": str(root)}
    write_json(run_dir / "pvol_catalog_root_last_upload_summary.json", payload)
    log("upload_complete_root_last")
    return payload


def smoke(stage_root: Path, run_dir: Path) -> dict[str, Any]:
    root = catalog_root(stage_root)
    catalog = load_json(root / "catalog.json")
    checks: list[dict[str, Any]] = []
    for key in [
        f"{OBJECT_PREFIX}/catalog/pvol/catalog.json",
        f"{OBJECT_PREFIX}/catalog/pvol/coverage.csv",
        f"{OBJECT_PREFIX}/catalog/pvol/coverage.json",
    ]:
        checks.append({"kind": "catalog_object", "key": key, "head_ok": head_object(key)})
    repaired = [
        ("dudwick", "20230601"),
        ("hameldon-hill", "20220619"),
        ("holehead", "20260409"),
        ("ingham", "20260114"),
        ("jersey", "20231214"),
        ("munduff-hill", "20200911"),
        ("munduff-hill", "20211130"),
        ("predannack", "20150801"),
    ]
    for radar, date in repaired:
        day = load_json(root / radar / date[:4] / date[4:6] / date[6:8] / "catalog.json")
        if day.get("files"):
            checks.append({"kind": "repaired_pvol_object", "key": day["files"][0]["object_key"], "head_ok": head_object(day["files"][0]["object_key"])})
            checks.append({"kind": "repaired_day_catalog", "key": day["catalog_key"], "head_ok": head_object(day["catalog_key"])})
    missing_spatial = [
        row.get("radar")
        for row in catalog.get("radars", [])
        if not row.get("spatial") or row["spatial"].get("latitude") in (None, 0) or row["spatial"].get("longitude") in (None, 0)
    ]
    ok = all(item["head_ok"] for item in checks) and not missing_spatial
    payload = {
        "ok": ok,
        "checked_at": utc_now(),
        "checks": checks,
        "missing_spatial": missing_spatial,
        "root_url": f"{PUBLIC_BASE_URL}/{OBJECT_PREFIX}/catalog/pvol/catalog.json",
    }
    write_json(run_dir / "pvol_catalog_smoke.json", payload)
    log(f"smoke_complete ok={ok} checks={len(checks)} missing_spatial={len(missing_spatial)}")
    if not ok:
        raise RuntimeError("smoke check failed")
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Patch spatial metadata and publish final PVOL catalog root-last.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path, required=True)
    args = parser.parse_args(argv)
    patch_spatial(args.stage_root, args.run_dir)
    upload_root_last(args.stage_root, args.run_dir)
    smoke(args.stage_root, args.run_dir)
    log("finalize_finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
