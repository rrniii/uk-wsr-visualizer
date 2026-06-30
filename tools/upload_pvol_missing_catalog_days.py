from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import subprocess
import sys
import time

from pvol_catalog_common import (
    aws_base as common_aws_base,
    aws_env,
    config_from_env,
    log,
    object_key,
    shell_join,
    utc_now,
    write_json,
)

CONFIG = config_from_env()
BUCKET = CONFIG.bucket
OBJECT_PREFIX = CONFIG.object_prefix
PVOL_BASE = CONFIG.pvol_base


@dataclass(frozen=True)
class Day:
    radar: str
    date: str

    @property
    def year(self) -> str:
        return self.date[:4]


def aws_base() -> list[str]:
    return common_aws_base(CONFIG)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    log("run " + shell_join(cmd))
    proc = subprocess.run(cmd, text=True, capture_output=True, env=aws_env())
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {cmd!r}")
    return proc


def marker_keys(base: Path, suffix: str) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    day_status = base / "day-status"
    if not day_status.exists():
        return keys
    for marker in day_status.glob(f"*/*/*.{suffix}.json"):
        radar = marker.parts[-3]
        date = marker.name.split(".")[0]
        keys.add((radar, date))
    return keys


def catalog_days(stage_root: Path) -> list[Day]:
    root = stage_root / OBJECT_PREFIX / "catalog" / "pvol"
    days: list[Day] = []
    for catalog in root.glob("*/*/*/*/catalog.json"):
        radar, year, month, day = catalog.relative_to(root).parts[:4]
        days.append(Day(radar, year + month + day))
    return sorted(days, key=lambda item: (item.radar, item.date))


def collect_missing_days(stage_root: Path, covered_runs: list[Path]) -> list[Day]:
    covered: set[tuple[str, str]] = set()
    for run_dir in covered_runs:
        covered |= marker_keys(run_dir, "done")
    missing = [day for day in catalog_days(stage_root) if (day.radar, day.date) not in covered]
    return missing


def local_manifest(day: Day) -> dict[str, dict[str, int | str]]:
    day_dir = PVOL_BASE / day.radar / day.year / day.date
    if not day_dir.exists():
        raise FileNotFoundError(day_dir)
    manifest: dict[str, dict[str, int | str]] = {}
    for pulse_dir in sorted(path for path in day_dir.iterdir() if path.is_dir() and not path.name.startswith(".")):
        for path in sorted(pulse_dir.glob("*.h5")):
            rel_key = f"{pulse_dir.name}/{path.name}"
            manifest[rel_key] = {"size": path.stat().st_size, "pulse": pulse_dir.name, "path": str(path)}
    return manifest


def remote_manifest(day: Day) -> dict[str, int]:
    prefix = object_key(OBJECT_PREFIX, "pvol", day.radar, day.year, day.date[4:6], day.date[6:8]) + "/"
    proc = subprocess.run(
        aws_base()
        + [
            "s3api",
            "list-objects-v2",
            "--bucket",
            BUCKET,
            "--prefix",
            prefix,
            "--output",
            "json",
        ],
        text=True,
        capture_output=True,
        env=aws_env(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"list-objects-v2 failed for {prefix}")
    payload = json.loads(proc.stdout or "{}")
    result: dict[str, int] = {}
    for item in payload.get("Contents") or []:
        key = item["Key"]
        if key.endswith(".h5"):
            result[key[len(prefix) :]] = int(item["Size"])
    return result


def compare(local: dict[str, dict[str, int | str]], remote: dict[str, int]) -> tuple[list[str], list[str], list[str]]:
    local_keys = set(local)
    remote_keys = set(remote)
    missing = sorted(local_keys - remote_keys)
    extra = sorted(remote_keys - local_keys)
    mismatched = sorted(key for key in local_keys & remote_keys if int(local[key]["size"]) != remote[key])
    return missing, extra, mismatched


def sync_day(day: Day) -> None:
    day_dir = PVOL_BASE / day.radar / day.year / day.date
    for pulse_dir in sorted(path for path in day_dir.iterdir() if path.is_dir() and not path.name.startswith(".")):
        destination_key = object_key(OBJECT_PREFIX, "pvol", day.radar, day.year, day.date[4:6], day.date[6:8], pulse_dir.name)
        destination = f"s3://{BUCKET}/{destination_key}/"
        run(
            aws_base()
            + [
                "s3",
                "sync",
                str(pulse_dir) + "/",
                destination,
                "--only-show-errors",
                "--acl",
                "public-read",
                "--no-progress",
                "--size-only",
            ]
        )


def upload_day(day: Day, supplemental_run: Path) -> dict[str, Any]:
    started = time.time()
    log(f"missing_day_upload_start radar={day.radar} date={day.date}")
    try:
        local = local_manifest(day)
        before_remote = remote_manifest(day)
        before_missing, before_extra, before_mismatched = compare(local, before_remote)
        log(
            f"before radar={day.radar} date={day.date} local={len(local)} remote={len(before_remote)} "
            f"missing={len(before_missing)} extra={len(before_extra)} mismatched={len(before_mismatched)}"
        )
        if before_missing or before_mismatched:
            sync_day(day)
        after_remote = remote_manifest(day)
        missing, extra, mismatched = compare(local, after_remote)
        ok = not missing and not mismatched
        status = "ok" if ok else "upload_verify_failed"
        payload: dict[str, Any] = {
            "radar": day.radar,
            "year": day.year,
            "date": day.date,
            "status": status,
            "file_count": len(local),
            "byte_count": sum(int(item["size"]) for item in local.values()),
            "remote_file_count": len(after_remote),
            "remote_byte_count": sum(after_remote.values()),
            "before_missing_count": len(before_missing),
            "before_extra_count": len(before_extra),
            "before_mismatched_count": len(before_mismatched),
            "missing_after": missing[:100],
            "extra_after": extra[:100],
            "mismatched_after": mismatched[:100],
            "elapsed_s": round(time.time() - started, 1),
            "finished_at": utc_now(),
        }
    except Exception as exc:
        payload = {
            "radar": day.radar,
            "year": day.year,
            "date": day.date,
            "status": "exception",
            "error": repr(exc),
            "elapsed_s": round(time.time() - started, 1),
            "finished_at": utc_now(),
        }
    status_dir = supplemental_run / "day-status" / day.radar / day.year
    marker = status_dir / f"{day.date}.{'done' if payload['status'] == 'ok' else 'failed'}.json"
    write_json(marker, payload)
    log(
        f"missing_day_upload_complete radar={day.radar} date={day.date} "
        f"status={payload['status']} elapsed_s={payload['elapsed_s']}"
    )
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Upload final-catalog PVOL days that are missing upload markers.")
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--supplemental-run", type=Path, required=True)
    parser.add_argument("--covered-run", type=Path, action="append", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    args.supplemental_run.mkdir(parents=True, exist_ok=True)
    missing_days = collect_missing_days(args.stage_root, args.covered_run)
    log(
        f"missing_upload_run_start days={len(missing_days)} workers={args.workers} "
        f"supplemental_run={args.supplemental_run}"
    )
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(upload_day, day, args.supplemental_run) for day in missing_days]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if index % 10 == 0 or index == len(futures):
                ok_count = sum(1 for item in results if item.get("status") == "ok")
                log(f"missing_upload_progress completed={index}/{len(futures)} ok={ok_count}")

    ok = all(item.get("status") == "ok" for item in results)
    summary = {
        "ok": ok,
        "stage_root": str(args.stage_root),
        "supplemental_run": str(args.supplemental_run),
        "covered_runs": [str(path) for path in args.covered_run],
        "finished_at": utc_now(),
        "day_count": len(missing_days),
        "uploaded_day_count": sum(1 for item in results if item.get("status") == "ok"),
        "failed_day_count": sum(1 for item in results if item.get("status") != "ok"),
        "file_count": sum(int(item.get("file_count", 0)) for item in results),
        "byte_count": sum(int(item.get("byte_count", 0)) for item in results),
        "results": sorted(results, key=lambda item: (str(item.get("radar")), str(item.get("date")))),
    }
    write_json(args.supplemental_run / "missing_upload_summary.json", summary)
    log(
        f"missing_upload_run_complete ok={ok} days={summary['uploaded_day_count']}/{summary['day_count']} "
        f"files={summary['file_count']}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
