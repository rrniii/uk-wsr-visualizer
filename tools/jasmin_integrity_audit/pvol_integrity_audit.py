#!/usr/bin/env python3
"""Full pvol integrity, coverage, catalog, and cron audit for Avocet on JASMIN."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path


PVOL_RE = re.compile(
    r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate_(?P<pulse>lp|sp)_(?P<hhmm>[0-9]{4})\.h5$"
)
STATUS_MARKER_RE = re.compile(
    r"^(?P<radar>.+)_(?P<date>[0-9]{8})\.(?P<status>done|failed|skipped|raw_missing|stalled|no_space)$"
)
NORMALISED_COHERENT_POWER_QUANTITIES = {
    "SQI",
    "SQIH",
    "SQIV",
    "NCP",
    "NCPH",
    "NCPV",
    "NORMALISED_COHERENT_POWER",
    "NORMALIZED_COHERENT_POWER",
}
FIELDS = [
    "path",
    "radar",
    "year",
    "date",
    "pulse_dir",
    "file_date",
    "radar_num",
    "file_pulse",
    "hhmm",
    "size_bytes",
    "mtime_epoch",
    "status",
    "issues",
    "quantities",
    "has_sqi",
    "has_normalised_coherent_power",
    "compression_checked_datasets",
    "gzip4_shuffle_ok",
]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def safe_cell(value: object) -> str:
    return str(value).replace("\t", " ").replace("\n", " ")


def clean_attr(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    return str(value)


def parse_manifest_rows(path: Path) -> tuple[dict[tuple[str, str, str], dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    by_day: dict[tuple[str, str], dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"radar", "date", "radar_num"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise RuntimeError(f"expected manifest is missing required columns: {path}")
        for row in reader:
            radar = (row.get("radar") or "").strip()
            date = (row.get("date") or "").strip()
            radar_num = (row.get("radar_num") or "").strip()
            if radar and date and radar_num:
                normalized = {key: (value or "").strip() for key, value in row.items()}
                by_key[(radar, date, radar_num)] = normalized
                by_day[(radar, date)] = normalized
    return by_key, by_day


def load_expected_outputs(
    manifest_path: Path, status_dir: Path | None
) -> tuple[set[tuple[str, str, str]], Counter[str], list[dict[str, str]]]:
    manifest_by_key, manifest_by_day = parse_manifest_rows(manifest_path)
    if not status_dir:
        return set(manifest_by_key), Counter({"manifest_rows": len(manifest_by_key)}), []

    expected: set[tuple[str, str, str]] = set()
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
        row = {
            "radar": radar,
            "date": date,
            "radar_num": radar_num,
            "status": status,
            "marker": str(marker),
            "path": (manifest_row or {}).get("path", ""),
        }
        if status == "done":
            if radar_num:
                expected.add((radar, date, radar_num))
            else:
                unresolved_done.append(row)
        else:
            non_done_markers.append(row)
    marker_counts["done_unresolved_in_manifest"] = len(unresolved_done)
    non_done_markers.extend(unresolved_done)
    return expected, marker_counts, non_done_markers


def parse_pvol_path(root: Path, path: Path) -> dict[str, str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = rel.parts
    row = {
        "path": str(path),
        "radar": parts[0] if len(parts) > 0 else "",
        "year": parts[1] if len(parts) > 1 else "",
        "date": parts[2] if len(parts) > 2 else "",
        "pulse_dir": parts[3] if len(parts) > 3 else "",
        "file_date": "",
        "radar_num": "",
        "file_pulse": "",
        "hhmm": "",
    }
    match = PVOL_RE.match(path.name)
    if match:
        row.update(
            {
                "file_date": match.group("date"),
                "radar_num": match.group("num"),
                "file_pulse": match.group("pulse"),
                "hhmm": match.group("hhmm"),
            }
        )
    return row


def iter_pvol_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if name.startswith(".") or not name.endswith(".h5"):
                continue
            yield Path(dirpath) / name


def hdf5_probe(path_text: str, compression_sample: int) -> tuple[list[str], Counter[str], int, int]:
    import h5py

    issues: list[str] = []
    quantities: Counter[str] = Counter()
    compression_checked = 0
    compression_ok = 1
    with h5py.File(path_text, "r") as h5:
        saw_dataset = False

        def visitor(name, obj):
            nonlocal saw_dataset, compression_checked, compression_ok
            if isinstance(obj, h5py.Dataset):
                saw_dataset = True
                if name.endswith("/data") and compression_checked < compression_sample:
                    compression_checked += 1
                    if obj.compression != "gzip" or obj.compression_opts != 4 or not obj.shuffle:
                        compression_ok = 0
                return
            if not isinstance(obj, h5py.Group):
                return
            if name.endswith("/what") and "quantity" in obj.attrs:
                quantity = clean_attr(obj.attrs.get("quantity")).upper()
                if quantity:
                    quantities[quantity] += 1

        h5.visititems(visitor)
        if not saw_dataset:
            issues.append("no_hdf5_datasets")
        if compression_sample > 0 and compression_checked == 0:
            compression_ok = 0
            issues.append("no_data_datasets_checked")
    return issues, quantities, compression_checked, compression_ok


def audit_one(path_text: str, root_text: str, compression_sample: int) -> dict[str, str]:
    path = Path(path_text)
    root = Path(root_text)
    row = parse_pvol_path(root, path)
    issues: list[str] = []
    try:
        stat = path.stat()
        row["size_bytes"] = str(stat.st_size)
        row["mtime_epoch"] = str(int(stat.st_mtime))
    except OSError as exc:
        row["size_bytes"] = ""
        row["mtime_epoch"] = ""
        issues.append(f"stat_error:{type(exc).__name__}:{exc}")

    if not PVOL_RE.match(path.name):
        issues.append("filename_not_pvol_pattern")
    if row["file_date"] and row["date"] and row["file_date"] != row["date"]:
        issues.append("date_path_filename_mismatch")
    if row["year"] and row["date"] and row["date"][:4] != row["year"]:
        issues.append("year_path_date_mismatch")
    if row["file_pulse"] and row["pulse_dir"] and row["file_pulse"] != row["pulse_dir"]:
        issues.append("pulse_path_filename_mismatch")
    if row["hhmm"]:
        hh, mm = int(row["hhmm"][:2]), int(row["hhmm"][2:])
        if hh > 23 or mm > 59:
            issues.append("bad_hhmm")

    quantities: Counter[str] = Counter()
    compression_checked = 0
    compression_ok = ""
    if not any(issue.startswith("stat_error") for issue in issues):
        try:
            probe_issues, quantities, compression_checked, compression_ok_int = hdf5_probe(path_text, compression_sample)
            issues.extend(probe_issues)
            compression_ok = str(compression_ok_int)
        except Exception as exc:
            issues.append(f"hdf5_open_error:{type(exc).__name__}:{exc}")
            compression_ok = "0"

    has_sqi = int(any(q in quantities for q in ("SQI", "SQIH", "SQIV")))
    has_ncp = int(any(q in quantities for q in NORMALISED_COHERENT_POWER_QUANTITIES))
    if not has_sqi:
        issues.append("missing_sqi")
    if not has_ncp:
        issues.append("missing_normalised_coherent_power")

    row["status"] = "ok" if not issues else ("unreadable_or_invalid_hdf5" if any("hdf5_open_error" in issue for issue in issues) else "issue")
    row["issues"] = ";".join(issues)
    row["quantities"] = ",".join(sorted(quantities))
    row["has_sqi"] = str(has_sqi)
    row["has_normalised_coherent_power"] = str(has_ncp)
    row["compression_checked_datasets"] = str(compression_checked)
    row["gzip4_shuffle_ok"] = str(compression_ok)
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
    parser.add_argument("--pvol-root", type=Path, required=True)
    parser.add_argument("--expected-manifest", type=Path, required=True)
    parser.add_argument("--status-dir", type=Path, default=None)
    parser.add_argument("--cron-log-dir", type=Path, required=True)
    parser.add_argument("--block-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--compression-sample", type=int, default=8)
    parser.add_argument("--progress-every", type=int, default=10000)
    args = parser.parse_args()

    args.run_dir.mkdir(parents=True, exist_ok=True)
    log(f"pvol audit run_dir={args.run_dir}")
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

    day_counts: Counter[tuple[str, str, str]] = Counter()
    pulse_counts: Counter[tuple[str, str, str, str]] = Counter()
    day_bytes: Counter[tuple[str, str, str]] = Counter()
    status_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    file_count = 0
    bad = 0

    progress = {
        "started_at": utc_now(),
        "expected_done_days": len(expected),
        "status_marker_counts": dict(marker_counts),
        "scanned": 0,
        "bad": 0,
    }
    write_json(args.run_dir / "progress.json", progress)

    with (args.run_dir / "pvol_issues.tsv").open("w", encoding="utf-8") as issue_out:
        issue_out.write("\t".join(FIELDS) + "\n")
        with ProcessPoolExecutor(max_workers=max(1, args.workers)) as executor:
            pending = set()
            iterator = iter_pvol_files(args.pvol_root)

            def submit_until_full() -> None:
                while len(pending) < max(1, args.workers) * 8:
                    try:
                        path = next(iterator)
                    except StopIteration:
                        return
                    pending.add(executor.submit(audit_one, str(path), str(args.pvol_root), args.compression_sample))

            submit_until_full()
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    row = future.result()
                    file_count += 1
                    status = row.get("status", "")
                    status_counts[status] += 1
                    radar = row.get("radar", "")
                    date = row.get("date", "")
                    radar_num = row.get("radar_num", "")
                    pulse = row.get("file_pulse", "") or row.get("pulse_dir", "")
                    if radar and date and radar_num:
                        key = (radar, date, radar_num)
                        day_counts[key] += 1
                        pulse_counts[(radar, date, radar_num, pulse)] += 1
                        try:
                            day_bytes[key] += int(row.get("size_bytes") or 0)
                        except ValueError:
                            pass
                    issues = [item for item in row.get("issues", "").split(";") if item]
                    for issue in issues:
                        issue_counts[issue.split(":", 1)[0]] += 1
                    if status != "ok" or row.get("gzip4_shuffle_ok") == "0":
                        bad += 1
                        issue_out.write("\t".join(row.get(field, "") for field in FIELDS) + "\n")
                    if args.progress_every and file_count % args.progress_every == 0:
                        progress.update(
                            {
                                "updated_at": utc_now(),
                                "scanned": file_count,
                                "bad": bad,
                                "status_counts": dict(status_counts),
                                "top_issue_counts": dict(issue_counts.most_common(20)),
                            }
                        )
                        write_json(args.run_dir / "progress.json", progress)
                        log(f"scanned={file_count} bad={bad}")
                submit_until_full()

    missing = sorted(expected - set(day_counts))
    extra = sorted(set(day_counts) - expected)
    with (args.run_dir / "missing_pvol_days_from_done_status.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\n")
        for key in missing:
            out.write("\t".join(key) + "\n")
    with (args.run_dir / "extra_pvol_days_not_in_done_status.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\tfile_count\tbytes\n")
        for key in extra:
            out.write("\t".join((*key, str(day_counts[key]), str(day_bytes[key]))) + "\n")
    with (args.run_dir / "pvol_day_summary.tsv").open("w", encoding="utf-8") as out:
        out.write("radar\tdate\tradar_num\tfile_count\tbytes\tlp_count\tsp_count\n")
        for key in sorted(day_counts):
            lp_count = pulse_counts.get((*key, "lp"), 0)
            sp_count = pulse_counts.get((*key, "sp"), 0)
            out.write("\t".join((*key, str(day_counts[key]), str(day_bytes[key]), str(lp_count), str(sp_count))) + "\n")

    summary = {
        "finished_at": utc_now(),
        "expected_done_days": len(expected),
        "status_marker_counts": dict(marker_counts),
        "pvol_days": len(day_counts),
        "pvol_files_scanned": file_count,
        "missing_days_from_done_status": len(missing),
        "extra_days_not_in_done_status": len(extra),
        "bad_or_compression_issue": bad,
        "status_counts": dict(status_counts),
        "top_issue_counts": dict(issue_counts.most_common(50)),
        "outputs": {
            "pvol_issues": str(args.run_dir / "pvol_issues.tsv"),
            "missing": str(args.run_dir / "missing_pvol_days_from_done_status.tsv"),
            "day_summary": str(args.run_dir / "pvol_day_summary.tsv"),
            "cron": str(args.run_dir / "cron_status.json"),
        },
    }
    write_json(args.run_dir / "summary.json", summary)
    write_json(args.run_dir / "progress.json", summary)
    log("pvol audit complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
