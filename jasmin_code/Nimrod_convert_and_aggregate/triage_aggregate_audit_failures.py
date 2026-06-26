#!/usr/bin/env python3
"""Triage non-ok results from the aggregate HDF5 audit.

This script is read-only. It groups failures, probes failed files, and writes
small reports that make it easier to decide what should be rebuilt or ignored.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from pathlib import Path

import h5py


BAD_STATUSES = {
    "corrupt_gap_boundary",
    "missing_variable",
    "structural_issue",
    "unreadable_or_invalid_hdf5",
}


def split_issues(text: str) -> list[str]:
    return [part for part in text.split(";") if part]


def issue_kind(issue: str) -> str:
    if ":" not in issue:
        return issue
    parts = issue.split(":")
    if len(parts) >= 2 and parts[0] in {"lp", "sp", "file"}:
        return parts[1]
    if parts[0].endswith("hdf5_open_error"):
        return "hdf5_open_error"
    return parts[0] if parts[0] else issue


def hdf5_signature(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(8).hex()
    except Exception as exc:
        return f"read_error:{type(exc).__name__}:{exc}"


def probe_file(path: Path) -> dict[str, str]:
    row: dict[str, str] = {
        "exists": "0",
        "size_bytes_now": "",
        "mtime_epoch_now": "",
        "hdf5_signature": "",
        "h5py_open": "0",
        "h5py_error": "",
        "top_keys": "",
        "pulse_time_counts": "",
    }
    try:
        stat = path.stat()
        row["exists"] = "1"
        row["size_bytes_now"] = str(stat.st_size)
        row["mtime_epoch_now"] = str(int(stat.st_mtime))
        row["hdf5_signature"] = hdf5_signature(path)
    except Exception as exc:
        row["h5py_error"] = f"stat_error:{type(exc).__name__}:{exc}"
        return row

    try:
        with h5py.File(path, "r") as h5:
            row["h5py_open"] = "1"
            row["top_keys"] = ",".join(sorted(h5.keys()))
            counts = []
            for pulse in ("lp", "sp"):
                group = h5.get(pulse)
                if not isinstance(group, h5py.Group):
                    continue
                time_count = sum(
                    1 for key in group.keys() if key.isdigit() and isinstance(group[key], h5py.Group)
                )
                counts.append(f"{pulse}:{time_count}")
            row["pulse_time_counts"] = ",".join(counts)
    except Exception as exc:
        row["h5py_error"] = f"{type(exc).__name__}:{exc}"
    return row


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sample-per-status", type=int, default=50)
    parser.add_argument("--probe-limit", type=int, default=0, help="0 means probe all failed files")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    status_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    status_issue_counts: Counter[tuple[str, str]] = Counter()
    unreadable_error_counts: Counter[str] = Counter()
    size_bucket_counts: Counter[tuple[str, str]] = Counter()
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    failed_rows: list[dict[str, str]] = []

    with args.audit.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            status = row.get("status", "")
            status_counts[status] += 1
            issues = split_issues(row.get("issues", ""))
            for issue in issues:
                kind = issue_kind(issue)
                issue_counts[kind] += 1
                status_issue_counts[(status, kind)] += 1
                if status == "unreadable_or_invalid_hdf5" and kind == "hdf5_open_error":
                    unreadable_error_counts[issue] += 1
            if status in BAD_STATUSES:
                failed_rows.append(row)
                if len(examples[status]) < args.sample_per_status:
                    examples[status].append(row)

    probe_rows: list[dict[str, str]] = []
    failed_for_probe = failed_rows if args.probe_limit == 0 else failed_rows[: args.probe_limit]
    for index, row in enumerate(failed_for_probe, start=1):
        path = Path(row["path"])
        probe = probe_file(path)
        size = probe.get("size_bytes_now", "")
        if size == "":
            bucket = "missing"
        else:
            value = int(size)
            if value == 0:
                bucket = "zero"
            elif value < 1024 * 1024:
                bucket = "lt_1MiB"
            elif value < 100 * 1024 * 1024:
                bucket = "lt_100MiB"
            elif value < 1024 * 1024 * 1024:
                bucket = "lt_1GiB"
            else:
                bucket = "ge_1GiB"
        size_bucket_counts[(row.get("status", ""), bucket)] += 1
        probe_rows.append(
            {
                **row,
                **probe,
                "probe_index": str(index),
            }
        )
        if index % 250 == 0:
            print(f"probed={index}", flush=True)

    write_tsv(
        args.out_dir / "status_counts.tsv",
        ["status", "count"],
        [{"status": key, "count": str(value)} for key, value in sorted(status_counts.items())],
    )
    write_tsv(
        args.out_dir / "issue_counts.tsv",
        ["issue", "count"],
        [{"issue": key, "count": str(value)} for key, value in issue_counts.most_common()],
    )
    write_tsv(
        args.out_dir / "status_issue_counts.tsv",
        ["status", "issue", "count"],
        [
            {"status": status, "issue": issue, "count": str(value)}
            for (status, issue), value in sorted(status_issue_counts.items())
        ],
    )
    write_tsv(
        args.out_dir / "unreadable_error_counts.tsv",
        ["error", "count"],
        [{"error": key, "count": str(value)} for key, value in unreadable_error_counts.most_common()],
    )
    write_tsv(
        args.out_dir / "size_bucket_counts.tsv",
        ["status", "size_bucket", "count"],
        [
            {"status": status, "size_bucket": bucket, "count": str(value)}
            for (status, bucket), value in sorted(size_bucket_counts.items())
        ],
    )
    if probe_rows:
        probe_fields = list(probe_rows[0].keys())
        write_tsv(args.out_dir / "failed_file_probes.tsv", probe_fields, probe_rows)

    for status, rows in examples.items():
        write_tsv(args.out_dir / f"examples_{status}.tsv", list(rows[0].keys()), rows)

    rebuild_rows = [
        {
            "path": row.get("path", ""),
            "radar": row.get("radar", ""),
            "date": row.get("date", ""),
            "radar_num": row.get("radar_num", ""),
            "status": row.get("status", ""),
            "issue_count": row.get("issue_count", ""),
            "issues": row.get("issues", ""),
        }
        for row in failed_rows
    ]
    write_tsv(
        args.out_dir / "triaged_rebuild_candidates.tsv",
        ["path", "radar", "date", "radar_num", "status", "issue_count", "issues"],
        rebuild_rows,
    )

    print(f"audit={args.audit}")
    print(f"out_dir={args.out_dir}")
    print(f"failed_files={len(failed_rows)}")
    print(f"probed_files={len(probe_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
