from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import json
import os
import subprocess
import sys
import time


AWS = "/home/users/rrniii/bin/aws"
BUCKET = "uk-wsr-visualizer-public"
ENDPOINT = "http://ncas-radar-o.s3.jc.rl.ac.uk"
PROFILE = "ncas-radar-o"
REGION = "us-east-1"
OBJECT_PREFIX = "ukmo-nimrod"
PVOL_BASE = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site")


@dataclass(frozen=True)
class FailedDay:
    radar: str
    year: str
    date: str
    marker_path: Path


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


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


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    log("run " + " ".join(cmd))
    proc = subprocess.run(cmd, text=True, env=aws_env(), capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {cmd!r}")
    return proc


def collect_failed_days(main_run: Path) -> list[FailedDay]:
    days: list[FailedDay] = []
    for marker in sorted((main_run / "day-status").glob("*/*/*.failed.json")):
        data = json.loads(marker.read_text(encoding="utf-8"))
        days.append(FailedDay(data["radar"], data["year"], data["date"], marker))
    return days


def local_manifest(day: FailedDay) -> dict[str, dict[str, int | str]]:
    day_dir = PVOL_BASE / day.radar / day.year / day.date
    manifest: dict[str, dict[str, int | str]] = {}
    if not day_dir.exists():
        raise FileNotFoundError(day_dir)
    for pulse_dir in sorted(path for path in day_dir.iterdir() if path.is_dir() and not path.name.startswith(".")):
        for path in sorted(pulse_dir.glob("*.h5")):
            rel_key = f"{pulse_dir.name}/{path.name}"
            manifest[rel_key] = {"size": path.stat().st_size, "pulse": pulse_dir.name, "path": str(path)}
    return manifest


def remote_manifest(day: FailedDay) -> dict[str, int]:
    prefix = f"{OBJECT_PREFIX}/pvol/{day.radar}/{day.year}/{day.date[4:6]}/{day.date[6:8]}/"
    cmd = aws_base() + [
        "s3api",
        "list-objects-v2",
        "--bucket",
        BUCKET,
        "--prefix",
        prefix,
        "--output",
        "json",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, env=aws_env())
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"list-objects-v2 failed for {prefix}")
    payload = json.loads(proc.stdout or "{}")
    result: dict[str, int] = {}
    for item in payload.get("Contents") or []:
        key = item["Key"]
        if not key.endswith(".h5"):
            continue
        rel_key = key.removeprefix(prefix)
        result[rel_key] = int(item["Size"])
    return result


def compare(local: dict[str, dict[str, int | str]], remote: dict[str, int]) -> tuple[list[str], list[str], list[str]]:
    local_keys = set(local)
    remote_keys = set(remote)
    missing = sorted(local_keys - remote_keys)
    extra = sorted(remote_keys - local_keys)
    mismatched = sorted(key for key in local_keys & remote_keys if int(local[key]["size"]) != remote[key])
    return missing, extra, mismatched


def sync_day(day: FailedDay) -> None:
    day_dir = PVOL_BASE / day.radar / day.year / day.date
    for pulse_dir in sorted(path for path in day_dir.iterdir() if path.is_dir() and not path.name.startswith(".")):
        destination = (
            f"s3://{BUCKET}/{OBJECT_PREFIX}/pvol/{day.radar}/{day.year}/"
            f"{day.date[4:6]}/{day.date[6:8]}/{pulse_dir.name}/"
        )
        cmd = aws_base() + [
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
        run(cmd)


def repair_day(day: FailedDay, supplemental_run: Path) -> dict[str, Any]:
    started = time.time()
    log(f"repair_start radar={day.radar} date={day.date} failed_marker={day.marker_path}")
    before_remote = remote_manifest(day)
    local = local_manifest(day)
    before_missing, before_extra, before_mismatched = compare(local, before_remote)
    log(
        f"before radar={day.radar} date={day.date} local={len(local)} remote={len(before_remote)} "
        f"missing={len(before_missing)} extra={len(before_extra)} mismatched={len(before_mismatched)}"
    )
    sync_day(day)
    after_remote = remote_manifest(day)
    missing, extra, mismatched = compare(local, after_remote)
    ok = not missing and not mismatched
    file_count = len(local)
    byte_count = sum(int(item["size"]) for item in local.values())
    elapsed = time.time() - started
    payload = {
        "radar": day.radar,
        "year": day.year,
        "date": day.date,
        "status": "ok" if ok else "repair_verify_failed",
        "source_failed_marker": str(day.marker_path),
        "file_count": file_count,
        "byte_count": byte_count,
        "remote_file_count": len(after_remote),
        "remote_byte_count": sum(after_remote.values()),
        "missing_after": missing[:100],
        "extra_after": extra[:100],
        "mismatched_after": mismatched[:100],
        "before_missing_count": len(before_missing),
        "before_extra_count": len(before_extra),
        "before_mismatched_count": len(before_mismatched),
        "return_code": 0 if ok else 1,
        "elapsed_s": round(elapsed, 1),
        "finished_at": utc_now(),
    }
    status_dir = supplemental_run / "day-status" / day.radar / day.year
    marker = status_dir / f"{day.date}.{'done' if ok else 'failed'}.json"
    write_json(marker, payload)
    log(f"repair_complete radar={day.radar} date={day.date} ok={ok} files={file_count} elapsed_s={elapsed:.1f}")
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Repair failed PVOL day uploads and verify object-store manifests.")
    parser.add_argument("--main-run", type=Path, required=True)
    parser.add_argument("--supplemental-run", type=Path, required=True)
    args = parser.parse_args(argv)
    args.supplemental_run.mkdir(parents=True, exist_ok=True)
    failed_days = collect_failed_days(args.main_run)
    if not failed_days:
        log("no failed days found")
        return 0
    log(f"repair_run_start failed_days={len(failed_days)} supplemental_run={args.supplemental_run}")
    results = []
    for day in failed_days:
        results.append(repair_day(day, args.supplemental_run))
    ok = all(item["status"] == "ok" for item in results)
    summary = {
        "ok": ok,
        "started_from_main_run": str(args.main_run),
        "supplemental_run": str(args.supplemental_run),
        "finished_at": utc_now(),
        "failed_day_count": len(failed_days),
        "repaired_day_count": sum(1 for item in results if item["status"] == "ok"),
        "unrepaired_day_count": sum(1 for item in results if item["status"] != "ok"),
        "file_count": sum(int(item["file_count"]) for item in results),
        "byte_count": sum(int(item["byte_count"]) for item in results),
        "results": results,
    }
    write_json(args.supplemental_run / "repair_summary.json", summary)
    log(
        f"repair_run_complete ok={ok} repaired={summary['repaired_day_count']}/"
        f"{summary['failed_day_count']} files={summary['file_count']}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
