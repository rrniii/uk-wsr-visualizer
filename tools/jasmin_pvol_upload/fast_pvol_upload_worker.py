#!/usr/bin/env python3
"""Worker for sharded pvol object-store uploads on JASMIN.

Each worker owns shards where shard_id % worker_count == worker_index and syncs
the pvol pulse directories directly to the public object-store layout. The full
pvol catalog is built once after all workers finish, avoiding expensive per-day
catalog generation during the transfer wave.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def load_shards(path: Path, worker_index: int, worker_count: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            shard_id = int(row["shard_id"])
            if shard_id % worker_count == worker_index:
                selected.append(row)
    return selected


def day_dirs(pvol_base: Path, radar: str, year: str, start_date: str, end_date: str) -> list[Path]:
    root = pvol_base / radar / year
    if not root.exists():
        return []
    result = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not path.name.isdigit() or len(path.name) != 8:
            continue
        if start_date and path.name < start_date:
            continue
        if end_date and path.name > end_date:
            continue
        result.append(path)
    return result


def pulse_dirs(day_dir: Path) -> list[Path]:
    return sorted(path for path in day_dir.iterdir() if path.is_dir() and not path.name.startswith("."))


def local_size(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            if filename.startswith("."):
                continue
            file_path = Path(dirpath) / filename
            try:
                stat = file_path.stat()
            except OSError:
                continue
            files += 1
            total += stat.st_size
    return files, total


def sync_day(
    args: argparse.Namespace,
    env: dict[str, str],
    radar: str,
    year: str,
    day_dir: Path,
) -> tuple[str, int, int, int]:
    date = day_dir.name
    mm = date[4:6]
    dd = date[6:8]
    pulses = pulse_dirs(day_dir)
    if not pulses:
        return "no_pulses", 0, 0, 0
    file_count = 0
    byte_count = 0
    for pulse_dir in pulses:
        pulse_files, pulse_bytes = local_size(pulse_dir)
        file_count += pulse_files
        byte_count += pulse_bytes
        destination = f"s3://{args.bucket}/ukmo-nimrod/pvol/{radar}/{year}/{mm}/{dd}/{pulse_dir.name}/"
        command = [
            args.aws_bin,
            "--profile",
            args.aws_profile,
            "--region",
            args.aws_region,
            "--endpoint-url",
            args.endpoint_url,
            "s3",
            "sync",
            str(pulse_dir) + "/",
            destination,
            "--only-show-errors",
            "--acl",
            "public-read",
            "--no-progress",
        ]
        completed = subprocess.run(command, env=env)
        if completed.returncode != 0:
            return f"aws_sync_failed:{pulse_dir.name}", file_count, byte_count, completed.returncode
    return "ok", file_count, byte_count, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--pvol-base", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--shards", type=Path, required=True)
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--worker-count", type=int, required=True)
    parser.add_argument("--aws-bin", default="/home/users/rrniii/bin/aws")
    parser.add_argument("--bucket", default="uk-wsr-visualizer-public")
    parser.add_argument("--endpoint-url", default="http://ncas-radar-o.s3.jc.rl.ac.uk")
    parser.add_argument("--aws-profile", default="ncas-radar-o")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    args = parser.parse_args()

    worker_name = f"worker_{args.worker_index:03d}"
    status_path = args.run_dir / "worker-status" / f"{worker_name}.tsv"
    summary_path = args.run_dir / "worker-status" / f"{worker_name}.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    done_root = args.run_dir / "day-status"

    shards = load_shards(args.shards, args.worker_index, args.worker_count)
    env = dict(os.environ)
    env["AWS_MAX_ATTEMPTS"] = env.get("AWS_MAX_ATTEMPTS", "10")
    env["AWS_RETRY_MODE"] = env.get("AWS_RETRY_MODE", "adaptive")
    env["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
    env["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"
    env["HDF5_USE_FILE_LOCKING"] = "FALSE"
    counts = {"ok": 0, "failed": 0, "shards": len(shards)}
    started = utc_now()
    log(f"{worker_name} start shards={len(shards)}")

    with status_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "worker",
                "shard_id",
                "radar",
                "year",
                "day_count",
                "days_done",
                "days_failed",
                "files_seen",
                "bytes_seen",
                "started_at",
                "finished_at",
                "elapsed_s",
                "exit_code",
                "status",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        handle.flush()

        for shard in shards:
            shard_started_epoch = time.time()
            shard_started = utc_now()
            radar = shard["radar"]
            year = shard["year"]
            log(f"{worker_name} START shard={shard['shard_id']} radar={radar} year={year} days={shard['day_count']}")
            days_done = 0
            days_failed = 0
            files_seen = 0
            bytes_seen = 0
            shard_status_dir = done_root / radar / year
            shard_status_dir.mkdir(parents=True, exist_ok=True)
            for day_dir in day_dirs(args.pvol_base, radar, year, args.start_date, args.end_date):
                day_started = time.time()
                date = day_dir.name
                day_status, file_count, byte_count, return_code = sync_day(args, env, radar, year, day_dir)
                files_seen += file_count
                bytes_seen += byte_count
                payload = {
                    "radar": radar,
                    "year": year,
                    "date": date,
                    "status": day_status,
                    "file_count": file_count,
                    "byte_count": byte_count,
                    "return_code": return_code,
                    "elapsed_s": round(time.time() - day_started, 1),
                    "finished_at": utc_now(),
                }
                marker = shard_status_dir / f"{date}.{('done' if day_status == 'ok' else 'failed')}.json"
                marker.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                if day_status == "ok":
                    days_done += 1
                else:
                    days_failed += 1
                    log(f"{worker_name} DAY_FAILED radar={radar} date={date} status={day_status}")
            elapsed = time.time() - shard_started_epoch
            status = "ok" if days_failed == 0 else "failed"
            counts[status] += 1
            writer.writerow(
                {
                    "worker": worker_name,
                    "shard_id": shard["shard_id"],
                    "radar": radar,
                    "year": year,
                    "day_count": shard["day_count"],
                    "days_done": str(days_done),
                    "days_failed": str(days_failed),
                    "files_seen": str(files_seen),
                    "bytes_seen": str(bytes_seen),
                    "started_at": shard_started,
                    "finished_at": utc_now(),
                    "elapsed_s": f"{elapsed:.1f}",
                    "exit_code": "0" if days_failed == 0 else "1",
                    "status": status,
                }
            )
            handle.flush()
            log(f"{worker_name} DONE shard={shard['shard_id']} radar={radar} year={year} status={status} elapsed_s={elapsed:.1f}")

    summary = {
        "worker": worker_name,
        "started_at": started,
        "finished_at": utc_now(),
        "counts": counts,
        "status_path": str(status_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    log(f"{worker_name} complete {counts}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
