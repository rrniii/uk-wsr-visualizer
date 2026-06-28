#!/usr/bin/env python3
"""Full aggregate integrity and coverage audit for the JASMIN Avocet build.

This wrapper reuses the aggregate health checker from Nimrod_convert_and_aggregate
and adds coverage and cron evidence around it. It is intended to run detached on
JASMIN and write restart-independent reports into a run directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path


AGGREGATE_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate\.h5$")
STATUS_MARKER_RE = re.compile(
    r"^(?P<radar>.+)_(?P<date>[0-9]{8})\.(?P<status>done|failed|skipped|raw_missing|stalled|no_space)$"
)


FIELDS = [
    "path",
    "radar",
    "date",
    "radar_num",
    "size_bytes",
    "mtime_epoch",
    "status",
    "issue_count",
    "issues",
    "pulses",
    "time_groups",
    "dataset_total",
    "quantities",
    "missing_quantities",
    "has_sqi",
    "has_normalised_coherent_power",
    "corrupt_gap_boundaries",
    "compression_checked_datasets",
    "gzip4_shuffle_ok",
    "compression_issues",
]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def safe_cell(value: object) -> str:
    return str(value).replace("\t", " ").replace("\n", " ")


def parse_manifest_rows(path: Path) -> tuple[dict[tuple[str, str, str], dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    by_day: dict[tuple[str, str], dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"path", "radar", "date", "radar_num"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise RuntimeError(f"expected manifest is missing required columns: {path}")
        for row in reader:
            radar = (row.get("radar") or "").strip()
            date = (row.get("date") or "").strip()
            radar_num = (row.get("radar_num") or "").strip()
            file_path = (row.get("path") or "").strip()
            if radar and date and radar_num and file_path:
                normalized = {key: (value or "").strip() for key, value in row.items()}
                by_key[(radar, date, radar_num)] = normalized
                by_day[(radar, date)] = normalized
    return by_key, by_day


def load_expected_outputs(
    manifest_path: Path, status_dir: Path | None
) -> tuple[dict[tuple[str, str, str], str], Counter[str], list[dict[str, str]]]:
    manifest_by_key, manifest_by_day = parse_manifest_rows(manifest_path)
    if not status_dir:
        return {key: row["path"] for key, row in manifest_by_key.items()}, Counter({"manifest_rows": len(manifest_by_key)}), []

    expected: dict[tuple[str, str, str], str] = {}
    marker_counts: Counter[str] = Counter()
    non_done_markers: list[dict[str, str]] = []
    unresolved_done: list[dict[str, str]] = []
    for marker in status_dir.iterdir():
        if not marker.is_file():
            continue
        match = STATUS_MARKER_RE.match(marker.name)
        if not match:
            continue
        radar = match.group("radar")
        date = match.group("date")
        status = match.group("status")
        marker_counts[status] += 1
        manifest_row = manifest_by_day.get((radar, date))
        radar_num = (manifest_row or {}).get("radar_num", "")
        file_path = (manifest_row or {}).get("path", "")
        row = {
            "radar": radar,
            "date": date,
            "radar_num": radar_num,
            "status": status,
            "marker": str(marker),
            "path": file_path,
        }
        if status == "done":
            if radar_num and file_path:
                expected[(radar, date, radar_num)] = file_path
            else:
                unresolved_done.append(row)
        else:
            non_done_markers.append(row)
    marker_counts["done_unresolved_in_manifest"] = len(unresolved_done)
    non_done_markers.extend(unresolved_done)
    return expected, marker_counts, non_done_markers


def parse_aggregate_path(root: Path, path: Path) -> tuple[str, str, str] | None:
    match = AGGREGATE_RE.match(path.name)
    if not match:
        return None
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if len(rel.parts) < 3:
        return None
    radar = rel.parts[0]
    return radar, match.group("date"), match.group("num")


def iter_aggregate_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if name.startswith(".") or not name.endswith(".h5"):
                continue
            if "_aggregate" not in name:
                continue
            yield Path(dirpath) / name


def check_gzip4_shuffle(path_text: str, max_datasets: int) -> tuple[int, int, list[str]]:
    import h5py

    checked = 0
    ok = 1
    issues: list[str] = []
    with h5py.File(path_text, "r") as h5:
        def visitor(name, obj):
            nonlocal checked, ok
            if checked >= max_datasets:
                return
            if not isinstance(obj, h5py.Dataset):
                return
            if not name.endswith("/data"):
                return
            checked += 1
            if obj.compression != "gzip" or obj.compression_opts != 4 or not obj.shuffle:
                ok = 0
                issues.append(
                    f"{name}:compression={obj.compression}:level={obj.compression_opts}:shuffle={int(bool(obj.shuffle))}"
                )

        h5.visititems(visitor)
    if checked == 0:
        ok = 0
        issues.append("no_data_datasets_checked")
    return checked, ok, issues[:20]


def audit_one(path_text: str, nimrod_code_dir: str, read_probe: bool, deep_quantities: bool, compression_sample: int) -> dict[str, str]:
    sys.path.insert(0, nimrod_code_dir)
    from audit_aggregate_file_health import audit_file

    row = audit_file(Path(path_text), read_probe=read_probe, deep_quantities=deep_quantities)
    row["compression_checked_datasets"] = "0"
    row["gzip4_shuffle_ok"] = ""
    row["compression_issues"] = ""
    if row.get("status") != "unreadable_or_invalid_hdf5" and compression_sample > 0:
        try:
            checked, ok, issues = check_gzip4_shuffle(path_text, compression_sample)
            row["compression_checked_datasets"] = str(checked)
            row["gzip4_shuffle_ok"] = str(ok)
            row["compression_issues"] = ";".join(issues)
            if not ok:
                row["issues"] = (row.get("issues", "") + ";file:compression_not_gzip4_shuffle").strip(";")
        except Exception as exc:
            row["gzip4_shuffle_ok"] = "0"
            row["compression_issues"] = f"{type(exc).__name__}:{exc}"
            row["issues"] = (row.get("issues", "") + ";file:compression_check_error").strip(";")
    return {field: safe_cell(row.get(field, "")) for field in FIELDS}


def write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_cron_status(run_dir: Path, cron_log_dir: Path, block_file: Path) -> dict:
    logs = sorted(cron_log_dir.glob("nimrod_daily_update_*.log"), key=lambda item: item.stat().st_mtime)
    latest = logs[-1] if logs else None
    latest_text = ""
    if latest:
        latest_text = latest.read_text(encoding="utf-8", errors="replace")[-12000:]
    cron = {
        "checked_at": utc_now(),
        "cron_log_dir": str(cron_log_dir),
        "latest_log": str(latest) if latest else "",
        "latest_log_mtime_epoch": int(latest.stat().st_mtime) if latest else None,
        "latest_log_tail": latest_text,
        "cron_fired_recently": bool(latest and time.time() - latest.stat().st_mtime < 36 * 3600),
        "daily_update_skipped_active_jobs": "active Nimrod conversion jobs are still running; skipping" in latest_text,
        "daily_update_stale_block_ignored": "daily update block is stale; ignoring" in latest_text,
        "daily_update_completed": "finished daily Nimrod aggregate update" in latest_text or "completed daily Nimrod aggregate update" in latest_text,
        "block_file": str(block_file),
        "block_file_exists": block_file.exists(),
    }
    if block_file.exists():
        stat = block_file.stat()
        cron["block_file_mtime_epoch"] = int(stat.st_mtime)
        cron["block_file_age_seconds"] = int(time.time() - stat.st_mtime)
        cron["block_file_text"] = block_file.read_text(encoding="utf-8", errors="replace")[-4000:]
    write_json(run_dir / "cron_status.json", cron)
    (run_dir / "cron_latest_tail.txt").write_text(latest_text, encoding="utf-8")
    return cron


def capture_command(path: Path, command: list[str]) -> None:
    with path.open("w", encoding="utf-8") as out:
        out.write("+ " + " ".join(command) + "\n")
        try:
            completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            out.write(completed.stdout)
            out.write(f"\nexit_code={completed.returncode}\n")
        except Exception as exc:
            out.write(f"{type(exc).__name__}: {exc}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-root", type=Path, required=True)
    parser.add_argument("--expected-manifest", type=Path, required=True)
    parser.add_argument("--status-dir", type=Path, default=None)
    parser.add_argument("--nimrod-code-dir", type=Path, required=True)
    parser.add_argument("--cron-log-dir", type=Path, required=True)
    parser.add_argument("--block-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--read-probe", action="store_true")
    parser.add_argument("--deep-quantities", action="store_true")
    parser.add_argument("--compression-sample", type=int, default=16)
    parser.add_argument("--progress-every", type=int, default=250)
    args = parser.parse_args()

    args.run_dir.mkdir(parents=True, exist_ok=True)
    log(f"aggregate audit run_dir={args.run_dir}")
    safe_args = {key: str(value) for key, value in vars(args).items()}
    write_json(args.run_dir / "started.json", {"started_at": utc_now(), "args": safe_args})

    capture_command(args.run_dir / "squeue_at_start.txt", ["squeue", "-u", os.environ.get("USER", "rrniii")])
    write_cron_status(args.run_dir, args.cron_log_dir, args.block_file)

    expected, marker_counts, non_done_markers = load_expected_outputs(args.expected_manifest, args.status_dir)
    log(f"expected_done_days={len(expected)}")
    write_json(args.run_dir / "status_marker_counts.json", dict(marker_counts))
    with (args.run_dir / "non_done_status_markers.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\tstatus\tmarker\tpath\n")
        for row in non_done_markers:
            out.write(
                "\t".join(
                    safe_cell(row.get(field, ""))
                    for field in ("radar", "date", "radar_num", "status", "marker", "path")
                )
                + "\n"
            )
    actual_paths: dict[tuple[str, str, str], str] = {}
    duplicate_actual: list[tuple[tuple[str, str, str], str, str]] = []
    all_files: list[str] = []
    for path in iter_aggregate_files(args.aggregate_root):
        parsed = parse_aggregate_path(args.aggregate_root, path)
        if not parsed:
            continue
        path_text = str(path)
        all_files.append(path_text)
        if parsed in actual_paths and actual_paths[parsed] != path_text:
            duplicate_actual.append((parsed, actual_paths[parsed], path_text))
        actual_paths[parsed] = path_text
    all_files.sort()
    log(f"actual_aggregate_files={len(all_files)}")

    missing_keys = sorted(set(expected) - set(actual_paths))
    extra_keys = sorted(set(actual_paths) - set(expected))
    with (args.run_dir / "missing_aggregate_from_done_status.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\texpected_path\n")
        for key in missing_keys:
            out.write("\t".join((*key, expected[key])) + "\n")
    with (args.run_dir / "extra_aggregate_not_in_done_status.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\tpath\n")
        for key in extra_keys:
            out.write("\t".join((*key, actual_paths[key])) + "\n")
    with (args.run_dir / "duplicate_aggregate_keys.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\tfirst_path\tduplicate_path\n")
        for key, first, duplicate in duplicate_actual:
            out.write("\t".join((*key, first, duplicate)) + "\n")

    progress = {
        "started_at": utc_now(),
        "expected_done_days": len(expected),
        "status_marker_counts": dict(marker_counts),
        "actual_aggregate_files": len(all_files),
        "missing_from_done_status": len(missing_keys),
        "extra_not_in_done_status": len(extra_keys),
        "scanned": 0,
        "bad": 0,
    }
    write_json(args.run_dir / "progress.json", progress)

    status_counts: Counter[str] = Counter()
    scanned = 0
    bad = 0
    with (args.run_dir / "aggregate_audit.tsv").open("w", encoding="utf-8") as audit_out, (
        args.run_dir / "aggregate_issues.tsv"
    ).open("w", encoding="utf-8") as issue_out:
        audit_out.write("\t".join(FIELDS) + "\n")
        issue_out.write("\t".join(FIELDS) + "\n")
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
            pending = set()
            iterator = iter(all_files)

            def submit_until_full() -> None:
                while len(pending) < max(1, args.workers) * 4:
                    try:
                        path_text = next(iterator)
                    except StopIteration:
                        return
                    pending.add(
                        executor.submit(
                            audit_one,
                            path_text,
                            str(args.nimrod_code_dir),
                            args.read_probe,
                            args.deep_quantities,
                            args.compression_sample,
                        )
                    )

            submit_until_full()
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    row = future.result()
                    audit_out.write("\t".join(row.get(field, "") for field in FIELDS) + "\n")
                    status = row.get("status", "")
                    status_counts[status] += 1
                    scanned += 1
                    if status != "ok" or row.get("gzip4_shuffle_ok") == "0":
                        bad += 1
                        issue_out.write("\t".join(row.get(field, "") for field in FIELDS) + "\n")
                    if args.progress_every and scanned % args.progress_every == 0:
                        progress.update(
                            {
                                "updated_at": utc_now(),
                                "scanned": scanned,
                                "bad": bad,
                                "status_counts": dict(status_counts),
                            }
                        )
                        write_json(args.run_dir / "progress.json", progress)
                        log(f"scanned={scanned} bad={bad}")
                submit_until_full()

    summary = {
        "finished_at": utc_now(),
        "expected_done_days": len(expected),
        "status_marker_counts": dict(marker_counts),
        "actual_aggregate_files": len(all_files),
        "missing_from_done_status": len(missing_keys),
        "extra_not_in_done_status": len(extra_keys),
        "duplicate_keys": len(duplicate_actual),
        "scanned": scanned,
        "bad_or_compression_issue": bad,
        "status_counts": dict(status_counts),
        "outputs": {
            "aggregate_audit": str(args.run_dir / "aggregate_audit.tsv"),
            "aggregate_issues": str(args.run_dir / "aggregate_issues.tsv"),
            "missing": str(args.run_dir / "missing_aggregate_from_done_status.tsv"),
            "cron": str(args.run_dir / "cron_status.json"),
        },
    }
    write_json(args.run_dir / "summary.json", summary)
    write_json(args.run_dir / "progress.json", summary)
    log("aggregate audit complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
