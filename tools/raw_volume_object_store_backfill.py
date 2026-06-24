from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from uk_wsr_visualizer.catalog import build_raw_volume_catalog


RAW_VOLUME_BASE = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site")
RUN_ROOT = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/raw-volume-backfill")
PUBLIC_BASE_URL = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"
ENDPOINT_URL = "http://ncas-radar-o.s3.jc.rl.ac.uk"
BUCKET = "uk-wsr-visualizer-public"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def run(cmd: list[str], env: dict[str, str]) -> None:
    log("RUN " + " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)


def head_ok(url: str) -> bool:
    try:
        with urlopen(Request(url, method="HEAD"), timeout=30) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        log(f"HEAD_FAILED {url} {type(exc).__name__}: {exc}")
        return False


def date_dirs(raw_volume_base: Path, radar: str, year: str, start: str, end: str) -> list[Path]:
    root = raw_volume_base / radar / year
    if not root.exists():
        return []
    candidates = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not path.name.isdigit() or len(path.name) != 8:
            continue
        if start and path.name < start:
            continue
        if end and path.name > end:
            continue
        candidates.append(path)
    return candidates


def sync_day(args: argparse.Namespace, radar: str, day_dir: Path, env: dict[str, str]) -> dict[str, object]:
    date = day_dir.name
    year = date[:4]
    day_root = args.run_root / radar / year / date
    catalog_path = day_root / "catalog.json"
    done_path = day_root / "done.json"
    failed_path = day_root / "failed.json"
    day_root.mkdir(parents=True, exist_ok=True)

    if done_path.exists() and not args.force:
        payload = json.loads(done_path.read_text(encoding="utf-8"))
        log(f"SKIP done radar={radar} date={date}")
        return payload

    log(f"START radar={radar} date={date}")
    items = build_raw_volume_catalog(
        raw_volume_base=args.raw_volume_base,
        output=catalog_path,
        radar=radar,
        year=year,
        date=date,
        object_store_base=args.public_base_url,
        metadata_mode="fast",
    )
    volume_count = sum(len(item.raw_volumes) for item in items)
    byte_count = sum(int(volume.file_size) for item in items for volume in item.raw_volumes)
    if volume_count == 0:
        raise RuntimeError(f"no raw-volume files found for {radar} {date}")

    aws_base = [
        args.aws_bin,
        "--profile",
        args.aws_profile,
        "--region",
        args.aws_region,
        "--endpoint-url",
        args.endpoint_url,
    ]
    destination = f"s3://{args.bucket}/uk-radar/raw-volume/radar={radar}/year={year}/date={date}"
    for pulse_dir in sorted(path for path in day_dir.iterdir() if path.is_dir()):
        run(
            [
                *aws_base,
                "s3",
                "cp",
                str(pulse_dir) + "/",
                f"{destination}/pulse={pulse_dir.name}/",
                "--recursive",
                "--only-show-errors",
                "--acl",
                "public-read",
            ],
            env,
        )

    catalog_key = f"uk-radar/catalog/inventory/raw-volume/{radar}/{year}/{date}/catalog.json"
    run(
        [
            *aws_base,
            "s3",
            "cp",
            str(catalog_path),
            f"s3://{args.bucket}/{catalog_key}",
            "--only-show-errors",
            "--content-type",
            "application/json",
            "--acl",
            "public-read",
        ],
        env,
    )

    catalog_url = f"{args.public_base_url}/{catalog_key}"
    sample = items[0].raw_volumes[0]
    sample_url = f"{args.public_base_url}/{sample.object_key}"
    if not head_ok(catalog_url):
        raise RuntimeError(f"catalog public HEAD failed: {catalog_url}")
    if not head_ok(sample_url):
        raise RuntimeError(f"sample HDF5 public HEAD failed: {sample_url}")

    payload = {
        "ok": True,
        "radar": radar,
        "date": date,
        "catalog": str(catalog_path),
        "catalog_url": catalog_url,
        "volume_count": volume_count,
        "byte_count": byte_count,
        "finished_at": utc_now(),
    }
    done_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if failed_path.exists():
        failed_path.unlink()
    log(f"DONE radar={radar} date={date} volumes={volume_count} bytes={byte_count}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill raw-volume HDF5 objects to the JASMIN Object Store by radar-day.")
    parser.add_argument("--radar", action="append", required=True, help="Radar slug. May be repeated.")
    parser.add_argument("--year", required=True)
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--raw-volume-base", type=Path, default=RAW_VOLUME_BASE)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--public-base-url", default=PUBLIC_BASE_URL)
    parser.add_argument("--endpoint-url", default=ENDPOINT_URL)
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--aws-bin", default=os.environ.get("AWS_BIN", "aws"))
    parser.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE_NAME", "ncas-radar-o"))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    env = dict(os.environ)
    env["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
    env["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"

    summary = {"ok": True, "started_at": utc_now(), "days": [], "failures": []}
    for radar in args.radar:
        for day_dir in date_dirs(args.raw_volume_base, radar, args.year, args.start_date, args.end_date):
            try:
                summary["days"].append(sync_day(args, radar, day_dir, env))
            except Exception as exc:
                payload = {
                    "ok": False,
                    "radar": radar,
                    "date": day_dir.name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "failed_at": utc_now(),
                }
                failed_path = args.run_root / radar / args.year / day_dir.name / "failed.json"
                failed_path.parent.mkdir(parents=True, exist_ok=True)
                failed_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                summary["failures"].append(payload)
                summary["ok"] = False
                log(f"FAILED radar={radar} date={day_dir.name} {payload['error']}")
                if not args.keep_going:
                    raise
    summary["finished_at"] = utc_now()
    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "latest-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    log(f"SUMMARY days={len(summary['days'])} failures={len(summary['failures'])}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
