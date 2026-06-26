#!/usr/bin/env python3
"""Prepare aggregate repair manifests from the audit failure triage output."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


RAW_BY_YEAR = Path("/badc/ukmo-nimrod/data/single-site/storage_by_year")
RAW_FLAT = Path("/badc/ukmo-nimrod/data/single-site")


def raw_paths(radar: str, date: str) -> tuple[Path, Path, str]:
    year = date[:4]
    sp_by = (
        RAW_BY_YEAR
        / year
        / radar
        / "raw-dual-polar"
        / year
        / f"metoffice-c-band-rain-radar_{radar}_{date}_raw-dual-polar-augzdr-sp.dat.gz.tar"
    )
    lp_by = (
        RAW_BY_YEAR
        / year
        / radar
        / "raw-dual-polar"
        / year
        / f"metoffice-c-band-rain-radar_{radar}_{date}_raw-dual-polar-augzdr-lp.dat.gz.tar"
    )
    sp_flat = (
        RAW_FLAT
        / radar
        / "raw-dual-polar"
        / year
        / f"metoffice-c-band-rain-radar_{radar}_{date}_raw-dual-polar-augzdr-sp.dat.gz.tar"
    )
    lp_flat = (
        RAW_FLAT
        / radar
        / "raw-dual-polar"
        / year
        / f"metoffice-c-band-rain-radar_{radar}_{date}_raw-dual-polar-augzdr-lp.dat.gz.tar"
    )
    if sp_by.exists() or lp_by.exists():
        return sp_by, lp_by, "storage_by_year"
    return sp_flat, lp_flat, "flat"


def write_rows(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--triaged", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--canary-per-radar", type=int, default=2)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    with args.triaged.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            radar = row.get("radar", "")
            date = row.get("date", "")
            if not radar or not date:
                continue
            key = (radar, date)
            if key not in by_key:
                by_key[key] = {
                    "path": row.get("path", ""),
                    "radar": radar,
                    "date": date,
                    "radar_num": row.get("radar_num", ""),
                    "statuses": row.get("status", ""),
                    "issues": row.get("issues", ""),
                }
            else:
                current = by_key[key]
                if row.get("status", "") not in current["statuses"].split(","):
                    current["statuses"] = ",".join(filter(None, [current["statuses"], row.get("status", "")]))
                if row.get("issues", ""):
                    current["issues"] = ";".join(filter(None, [current["issues"], row.get("issues", "")]))

    fields = [
        "path",
        "radar",
        "date",
        "radar_num",
        "statuses",
        "raw_status",
        "raw_source",
        "sp_path",
        "lp_path",
        "issues",
    ]
    repair_rows: list[dict[str, str]] = []
    raw_missing_rows: list[dict[str, str]] = []
    for row in sorted(by_key.values(), key=lambda item: (item["radar"], item["date"])):
        sp_path, lp_path, source = raw_paths(row["radar"], row["date"])
        row = dict(row)
        row["raw_source"] = source
        row["sp_path"] = str(sp_path)
        row["lp_path"] = str(lp_path)
        if sp_path.exists() and lp_path.exists():
            row["raw_status"] = "raw_available"
            repair_rows.append(row)
        else:
            row["raw_status"] = "raw_missing"
            raw_missing_rows.append(row)

    by_radar: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_status: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in repair_rows:
        by_radar[row["radar"]].append(row)
        for status in row["statuses"].split(","):
            by_status[status].append(row)

    canary_keys: set[tuple[str, str]] = set()
    canary_rows: list[dict[str, str]] = []
    for radar in sorted(by_radar):
        for row in by_radar[radar][: args.canary_per_radar]:
            key = (row["radar"], row["date"])
            if key not in canary_keys:
                canary_keys.add(key)
                canary_rows.append(row)
    for status in ("unreadable_or_invalid_hdf5", "structural_issue", "corrupt_gap_boundary", "missing_variable"):
        for row in by_status.get(status, []):
            key = (row["radar"], row["date"])
            if key not in canary_keys:
                canary_keys.add(key)
                canary_rows.append(row)
                break

    full_rows = [row for row in repair_rows if (row["radar"], row["date"]) not in canary_keys]

    write_rows(args.out_dir / "repair_candidates.tsv", repair_rows, fields)
    write_rows(args.out_dir / "raw_available.tsv", repair_rows, fields)
    write_rows(args.out_dir / "raw_missing.tsv", raw_missing_rows, fields)
    write_rows(args.out_dir / "canary_candidates.tsv", canary_rows, fields)
    write_rows(args.out_dir / "full_repair_candidates.tsv", full_rows, fields)

    with (args.out_dir / "prepare_summary.txt").open("w", encoding="utf-8") as out:
        out.write(f"unique_failed_tasks={len(by_key)}\n")
        out.write(f"raw_available={len(repair_rows)}\n")
        out.write(f"raw_missing={len(raw_missing_rows)}\n")
        out.write(f"canary_tasks={len(canary_rows)}\n")
        out.write(f"full_repair_tasks={len(full_rows)}\n")

    print(f"out_dir={args.out_dir}")
    print(f"unique_failed_tasks={len(by_key)}")
    print(f"raw_available={len(repair_rows)}")
    print(f"raw_missing={len(raw_missing_rows)}")
    print(f"canary_tasks={len(canary_rows)}")
    print(f"full_repair_tasks={len(full_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
