#!/usr/bin/env python3
"""Check aggregate HDF5 coverage against raw LP/SP NIMROD tar files."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
import re
import sys
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
AGG_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate\.h5$")


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


def aggregate_dates_for_radar(aggregate_base: Path, radar: str, radar_num: str) -> set[str]:
    dates: set[str] = set()
    radar_dir = aggregate_base / radar
    for year_dir in iter_year_dirs(radar_dir):
        try:
            with os.scandir(year_dir) as entries:
                for entry in entries:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    match = AGG_RE.match(entry.name)
                    if match and match.group("num") == radar_num:
                        dates.add(match.group("date"))
        except FileNotFoundError:
            continue
    return dates


def fmt(value: str | None) -> str:
    return value or ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-by-year",
        type=Path,
        default=Path("/badc/ukmo-nimrod/data/single-site/storage_by_year"),
    )
    parser.add_argument(
        "--raw-flat",
        type=Path,
        default=Path("/badc/ukmo-nimrod/data/single-site"),
    )
    parser.add_argument(
        "--aggregate-base",
        type=Path,
        default=Path(
            "/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--missing-output",
        type=Path,
        help="Optional TSV containing every raw SP+LP date with no aggregate file.",
    )
    parser.add_argument("--sample-size", type=int, default=10)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.missing_output:
        args.missing_output.parent.mkdir(parents=True, exist_ok=True)
    failed = False

    with ExitStack() as stack:
        out = stack.enter_context(args.output.open("w", encoding="utf-8"))
        missing_out = None
        if args.missing_output:
            missing_out = stack.enter_context(args.missing_output.open("w", encoding="utf-8"))
            missing_out.write("path\tradar\tdate\tradar_num\n")

        out.write(
            "radar\tradar_num\tlatest_raw_both\tlatest_aggregate\traw_both_count\t"
            "aggregate_count\tmissing_count\textra_count\tstatus\tmissing_sample\n"
        )
        for radar, radar_num in RADARS:
            sp_dates, lp_dates = raw_dates_for_radar(args.raw_by_year, args.raw_flat, radar)
            raw_both = sp_dates & lp_dates
            aggregate_dates = aggregate_dates_for_radar(args.aggregate_base, radar, radar_num)
            missing = sorted(raw_both - aggregate_dates)
            extra = sorted(aggregate_dates - raw_both)
            latest_raw = max(raw_both) if raw_both else None
            latest_aggregate = max(aggregate_dates) if aggregate_dates else None
            status = "OK"
            if missing or (latest_raw and (not latest_aggregate or latest_aggregate < latest_raw)):
                status = "MISSING"
                failed = True
            if missing_out:
                for missing_date in missing:
                    target = (
                        args.aggregate_base
                        / radar
                        / missing_date[:4]
                        / f"{missing_date}_polar_pl_radar{radar_num}_aggregate.h5"
                    )
                    missing_out.write(
                        "\t".join([str(target), radar, missing_date, radar_num]) + "\n"
                    )
            out.write(
                "\t".join(
                    [
                        radar,
                        radar_num,
                        fmt(latest_raw),
                        fmt(latest_aggregate),
                        str(len(raw_both)),
                        str(len(aggregate_dates)),
                        str(len(missing)),
                        str(len(extra)),
                        status,
                        ",".join(missing[: args.sample_size]),
                    ]
                )
                + "\n"
            )
            print(
                f"{radar}: status={status} latest_raw={fmt(latest_raw)} "
                f"latest_aggregate={fmt(latest_aggregate)} missing={len(missing)}"
            )

    print(f"output={args.output}")
    if args.missing_output:
        print(f"missing_output={args.missing_output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
