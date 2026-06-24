#!/usr/bin/env python3
"""Find aggregate HDF5 files that should be regenerated.

The fixed converter skips incomplete LP/SP volumes and writes contiguous
dataset groups. This scanner flags existing aggregate files whose pulse/time
groups do not satisfy those invariants.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter
from pathlib import Path

import h5py


DATASET_RE = re.compile(r"^dataset([0-9]+)$")
DATE_RE = re.compile(r"^([0-9]{8})_polar_pl_radar([0-9]{2})_aggregate\.h5$")
TIME_RE = re.compile(r"^[0-9]{4}$")
PULSES = ("lp", "sp")


def dataset_numbers(group: h5py.Group) -> list[int]:
    numbers: list[int] = []
    for key in group.keys():
        match = DATASET_RE.match(key)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def attr_scalar(attrs: h5py.AttributeManager, key: str):
    if key not in attrs:
        return None
    value = attrs[key]
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def elangles_map_keys(time_group: h5py.Group) -> set[int] | None:
    where = time_group.get("where")
    if not isinstance(where, h5py.Group):
        return None
    raw = attr_scalar(where.attrs, "elangles_map")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parsed = ast.literal_eval(str(raw))
    except Exception:
        return None
    keys: set[int] = set()
    for key in parsed.keys():
        match = DATASET_RE.match(str(key))
        if match:
            keys.add(int(match.group(1)))
    return keys


def classify_file(path: Path) -> list[tuple[str, str, str, str]]:
    issues: list[tuple[str, str, str, str]] = []
    try:
        with h5py.File(path, "r") as h5:
            present_pulses = [pulse for pulse in PULSES if pulse in h5]
            if not present_pulses:
                issues.append(("", "", "missing_lp_sp", "file has no lp or sp group"))
                return issues

            for pulse in present_pulses:
                pulse_group = h5[pulse]
                time_keys = [
                    key
                    for key in pulse_group.keys()
                    if TIME_RE.match(key) and isinstance(pulse_group[key], h5py.Group)
                ]
                counts: dict[str, int] = {}
                for time_key in time_keys:
                    nums = dataset_numbers(pulse_group[time_key])
                    if nums:
                        counts[time_key] = len(nums)

                if not counts:
                    issues.append((pulse, "", "missing_datasets", "pulse has no dataset groups"))
                    continue

                count_frequency = Counter(counts.values())
                expected_count = max(count_frequency, key=lambda count: (count_frequency[count], count))
                max_count = max(counts.values())
                if max_count > expected_count:
                    expected_count = max_count

                for time_key in time_keys:
                    time_group = pulse_group[time_key]
                    nums = dataset_numbers(time_group)
                    if not nums:
                        issues.append((pulse, time_key, "missing_datasets", "time group has no datasets"))
                        continue

                    expected_nums = list(range(1, len(nums) + 1))
                    if nums != expected_nums:
                        issues.append(
                            (
                                pulse,
                                time_key,
                                "non_contiguous_datasets",
                                f"datasets={nums}; expected={expected_nums}",
                            )
                        )

                    if len(nums) < expected_count:
                        issues.append(
                            (
                                pulse,
                                time_key,
                                "partial_volume",
                                f"datasets={len(nums)}; expected={expected_count}",
                            )
                        )

                    how = time_group.get("how")
                    scan_count = None
                    if isinstance(how, h5py.Group):
                        scan_count = attr_scalar(how.attrs, "scan_count")
                    if scan_count is None:
                        issues.append((pulse, time_key, "missing_scan_count", "how/scan_count missing"))
                    elif int(scan_count) != len(nums):
                        issues.append(
                            (
                                pulse,
                                time_key,
                                "scan_count_mismatch",
                                f"scan_count={scan_count}; datasets={len(nums)}",
                            )
                        )

                    map_keys = elangles_map_keys(time_group)
                    if map_keys is None:
                        issues.append((pulse, time_key, "bad_elangles_map", "missing or unparsable"))
                    elif map_keys != set(nums):
                        issues.append(
                            (
                                pulse,
                                time_key,
                                "elangles_map_mismatch",
                                f"map={sorted(map_keys)}; datasets={nums}",
                            )
                        )
    except Exception as exc:
        issues.append(("", "", "hdf5_open_error", f"{type(exc).__name__}: {exc}"))
    return issues


def iter_files(base: Path):
    for dirpath, _dirnames, filenames in os.walk(base):
        for filename in sorted(filenames):
            if filename.endswith("_aggregate.h5"):
                yield Path(dirpath) / filename


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(
            "/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args()

    scanned = 0
    candidate_files = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        out.write("path\tradar\tdate\tradar_num\tpulse\ttime\tissue\tdetail\n")
        for path in iter_files(args.base):
            scanned += 1
            if args.progress_every and scanned % args.progress_every == 0:
                print(f"scanned {scanned}", file=sys.stderr, flush=True)

            issues = classify_file(path)
            if not issues:
                continue
            candidate_files += 1

            radar = path.parent.parent.name if path.parent.name.isdigit() else ""
            filename_match = DATE_RE.match(path.name)
            date = filename_match.group(1) if filename_match else ""
            radar_num = filename_match.group(2) if filename_match else ""
            for pulse, time_key, issue, detail in issues:
                out.write(
                    "\t".join(
                        [
                            str(path),
                            radar,
                            date,
                            radar_num,
                            pulse,
                            time_key,
                            issue,
                            detail.replace("\t", " "),
                        ]
                    )
                    + "\n"
                )

    print(f"scanned_files={scanned}")
    print(f"candidate_files={candidate_files}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
