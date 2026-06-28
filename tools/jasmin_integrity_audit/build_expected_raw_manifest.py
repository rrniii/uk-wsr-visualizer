#!/usr/bin/env python3
"""Build the expected Avocet radar-day manifest from raw NIMROD availability."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections import Counter
from pathlib import Path


RADARS = (
    ("castor-bay", "07"),
    ("chenies", "05"),
    ("clee-hill", "03"),
    ("cobbacombe", "16"),
    ("crug-y-gorrllwyn", "10"),
    ("deanhill", "21"),
    ("druima-starraig", "15"),
    ("dudwick", "14"),
    ("hameldon-hill", "04"),
    ("high-moorsley", "23"),
    ("holehead", "18"),
    ("ingham", "09"),
    ("jersey", "12"),
    ("munduff-hill", "19"),
    ("predannack", "08"),
    ("thurnham", "20"),
    ("wardon-hill", "11"),
)

RAW_RE = re.compile(
    r"^metoffice-c-band-rain-radar_(?P<radar>.+?)_"
    r"(?P<date>[0-9]{8})_raw-dual-polar-augzdr-(?P<pulse>sp|lp)\.dat\.gz\.tar$"
)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def iter_year_dirs(path: Path):
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False) and entry.name.isdigit():
                    yield Path(entry.path)
    except FileNotFoundError:
        return


def add_raw_files(directory: Path, radar: str, sp_dates: set[str], lp_dates: set[str]) -> None:
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                match = RAW_RE.match(entry.name)
                if not match or match.group("radar") != radar:
                    continue
                if match.group("pulse") == "sp":
                    sp_dates.add(match.group("date"))
                else:
                    lp_dates.add(match.group("date"))
    except FileNotFoundError:
        return


def raw_dates_for_radar(raw_by_year: Path, raw_flat: Path, radar: str) -> tuple[set[str], set[str]]:
    sp_dates: set[str] = set()
    lp_dates: set[str] = set()

    for year_dir in iter_year_dirs(raw_by_year):
        add_raw_files(year_dir / radar / "raw-dual-polar" / year_dir.name, radar, sp_dates, lp_dates)

    flat_radar_dir = raw_flat / radar / "raw-dual-polar"
    for year_dir in iter_year_dirs(flat_radar_dir):
        add_raw_files(year_dir, radar, sp_dates, lp_dates)

    return sp_dates, lp_dates


def aggregate_path(aggregate_root: Path, radar: str, radar_num: str, date: str) -> Path:
    return aggregate_root / radar / date[:4] / f"{date}_polar_pl_radar{radar_num}_aggregate.h5"


def write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-by-year", type=Path, default=Path("/badc/ukmo-nimrod/data/single-site/storage_by_year"))
    parser.add_argument("--raw-flat", type=Path, default=Path("/badc/ukmo-nimrod/data/single-site"))
    parser.add_argument(
        "--aggregate-root",
        type=Path,
        default=Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--require-both-pulses",
        action="store_true",
        help="Require both SP and LP raw files. Default is production behavior: SP-only and LP-only days are valid.",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    radar_summaries: list[dict[str, object]] = []

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "path",
            "radar",
            "date",
            "radar_num",
            "raw_status",
            "has_sp",
            "has_lp",
            "raw_pulses",
            "issues",
        ]
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()

        for radar, radar_num in RADARS:
            sp_dates, lp_dates = raw_dates_for_radar(args.raw_by_year, args.raw_flat, radar)
            expected_dates = sp_dates & lp_dates if args.require_both_pulses else sp_dates | lp_dates
            rows = 0
            for date in sorted(expected_dates):
                has_sp = date in sp_dates
                has_lp = date in lp_dates
                pulses = ",".join(pulse for pulse, present in (("sp", has_sp), ("lp", has_lp)) if present)
                if has_sp and has_lp:
                    counts["sp_lp"] += 1
                    raw_status = "raw_sp_lp"
                elif has_sp:
                    counts["sp_only"] += 1
                    raw_status = "raw_sp_only"
                else:
                    counts["lp_only"] += 1
                    raw_status = "raw_lp_only"
                writer.writerow(
                    {
                        "path": str(aggregate_path(args.aggregate_root, radar, radar_num, date)),
                        "radar": radar,
                        "date": date,
                        "radar_num": radar_num,
                        "raw_status": raw_status,
                        "has_sp": int(has_sp),
                        "has_lp": int(has_lp),
                        "raw_pulses": pulses,
                        "issues": "",
                    }
                )
                rows += 1
            counts["expected_days"] += rows
            radar_summaries.append(
                {
                    "radar": radar,
                    "radar_num": radar_num,
                    "expected_days": rows,
                    "sp_days": len(sp_dates),
                    "lp_days": len(lp_dates),
                    "first_date": min(expected_dates) if expected_dates else "",
                    "last_date": max(expected_dates) if expected_dates else "",
                }
            )

    summary = {
        "generated_at": utc_now(),
        "output": str(args.output),
        "raw_by_year": str(args.raw_by_year),
        "raw_flat": str(args.raw_flat),
        "aggregate_root": str(args.aggregate_root),
        "require_both_pulses": args.require_both_pulses,
        "counts": dict(counts),
        "radars": radar_summaries,
    }
    write_json(args.summary, summary)
    print(f"expected_manifest={args.output}")
    print(f"expected_days={counts['expected_days']}")
    print(f"sp_only={counts['sp_only']} lp_only={counts['lp_only']} sp_lp={counts['sp_lp']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
