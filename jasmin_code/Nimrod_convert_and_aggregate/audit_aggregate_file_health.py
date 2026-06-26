#!/usr/bin/env python3
"""Read-only health audit for aggregated ODIM HDF5 radar files.

The checks are intentionally metadata-heavy so they can be run over the full
aggregate tree in a Slurm array without reading every radar data array.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import h5py


DATE_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate\.h5$")
DATASET_RE = re.compile(r"^dataset(?P<num>[0-9]+)$")
DATA_RE = re.compile(r"^(data|quality)(?P<num>[0-9]+)$")
TIME_RE = re.compile(r"^[0-9]{4}$")
PULSE_STEPS = {"lp": 5, "sp": 10}
EXPECTED_QUANTITIES = {
    "lp": {"DBZH", "CI", "VRADH", "SQIH", "WRADH", "ZDR", "RHOHV", "PHIDP"},
    "sp": {"DBZH", "CI", "VRADH", "SQIH", "ZDR", "RHOHV", "PHIDP"},
}
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


def clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


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


def dataset_numbers(group: h5py.Group) -> list[int]:
    numbers = []
    for key in group.keys():
        match = DATASET_RE.match(key)
        if match:
            numbers.append(int(match.group("num")))
    return sorted(numbers)


def data_numbers(group: h5py.Group, prefix: str) -> list[int]:
    numbers = []
    for key in group.keys():
        match = DATA_RE.match(key)
        if match and key.startswith(prefix):
            numbers.append(int(match.group("num")))
    return sorted(numbers)


def quantity(group: h5py.Group, child: str) -> str:
    what = group.get(child, {}).get("what") if child in group else None
    if not isinstance(what, h5py.Group):
        return ""
    return clean(attr_scalar(what.attrs, "quantity")).upper()


def parse_elangles_map(time_group: h5py.Group) -> set[int] | None:
    where = time_group.get("where")
    if not isinstance(where, h5py.Group):
        return None
    raw = attr_scalar(where.attrs, "elangles_map")
    if raw is None:
        return None
    try:
        parsed = ast.literal_eval(clean(raw))
    except Exception:
        return None
    keys = set()
    for key in parsed:
        match = DATASET_RE.match(str(key))
        if match:
            keys.add(int(match.group("num")))
    return keys


def hhmm_to_minutes(value: str) -> int | None:
    if not TIME_RE.match(value):
        return None
    hh = int(value[:2])
    mm = int(value[2:])
    if hh > 23 or mm > 59:
        return None
    return hh * 60 + mm


def audit_file(path: Path, read_probe: bool = False, deep_quantities: bool = False) -> dict[str, str]:
    issues: list[str] = []
    issue_counts: Counter[str] = Counter()
    pulses_present: list[str] = []
    time_group_counts: dict[str, int] = {}
    dataset_total = 0
    quantity_counter: Counter[str] = Counter()
    missing_quantities: dict[str, set[str]] = defaultdict(set)
    corrupt_gap_boundaries: list[str] = []

    match = DATE_RE.match(path.name)
    date = match.group("date") if match else ""
    radar_num = match.group("num") if match else ""
    radar = path.parent.parent.name if path.parent.name.isdigit() else ""

    try:
        stat = path.stat()
    except OSError as exc:
        return {
            "path": str(path),
            "radar": radar,
            "date": date,
            "radar_num": radar_num,
            "size_bytes": "",
            "mtime_epoch": "",
            "status": "unreadable_or_invalid_hdf5",
            "issue_count": "1",
            "issues": f"stat_error:{type(exc).__name__}:{exc}",
            "pulses": "",
            "time_groups": "",
            "dataset_total": "0",
            "quantities": "",
            "missing_quantities": "",
            "has_sqi": "0",
            "has_normalised_coherent_power": "0",
            "corrupt_gap_boundaries": "",
        }

    try:
        with h5py.File(path, "r") as h5:
            for pulse in ("lp", "sp"):
                if pulse not in h5:
                    continue
                pulse_group = h5[pulse]
                if not isinstance(pulse_group, h5py.Group):
                    continue
                pulses_present.append(pulse)
                time_keys = sorted(
                    key
                    for key in pulse_group.keys()
                    if TIME_RE.match(key) and isinstance(pulse_group[key], h5py.Group)
                )
                time_group_counts[pulse] = len(time_keys)
                previous_time = None
                previous_health_ok = True

                for time_key in time_keys:
                    minutes = hhmm_to_minutes(time_key)
                    if minutes is None:
                        issues.append(f"{pulse}/{time_key}:bad_time_key")
                        issue_counts["bad_time_key"] += 1

                    if previous_time is not None and minutes is not None:
                        gap = minutes - previous_time
                        if gap < 0:
                            gap += 24 * 60
                        step = PULSE_STEPS.get(pulse)
                        if step and gap > step and not previous_health_ok:
                            boundary = f"{pulse}/{time_key}-after-gap-{gap}min"
                            corrupt_gap_boundaries.append(boundary)
                            issues.append(f"{boundary}:previous_group_unhealthy")
                            issue_counts["corrupt_gap_boundary"] += 1

                    time_group = pulse_group[time_key]
                    group_issues_before = len(issues)
                    nums = dataset_numbers(time_group)
                    dataset_total += len(nums)
                    if not nums:
                        issues.append(f"{pulse}/{time_key}:missing_datasets")
                        issue_counts["missing_datasets"] += 1
                    elif nums != list(range(1, len(nums) + 1)):
                        issues.append(f"{pulse}/{time_key}:non_contiguous_datasets:{nums}")
                        issue_counts["non_contiguous_datasets"] += 1

                    how = time_group.get("how")
                    scan_count = attr_scalar(how.attrs, "scan_count") if isinstance(how, h5py.Group) else None
                    if scan_count is None:
                        issues.append(f"{pulse}/{time_key}:missing_scan_count")
                        issue_counts["missing_scan_count"] += 1
                    else:
                        try:
                            if int(scan_count) != len(nums):
                                issues.append(
                                    f"{pulse}/{time_key}:scan_count_mismatch:{scan_count}!={len(nums)}"
                                )
                                issue_counts["scan_count_mismatch"] += 1
                        except Exception:
                            issues.append(f"{pulse}/{time_key}:bad_scan_count:{scan_count}")
                            issue_counts["bad_scan_count"] += 1

                    map_keys = parse_elangles_map(time_group)
                    if map_keys is None:
                        issues.append(f"{pulse}/{time_key}:bad_elangles_map")
                        issue_counts["bad_elangles_map"] += 1
                    elif map_keys != set(nums):
                        issues.append(f"{pulse}/{time_key}:elangles_map_mismatch")
                        issue_counts["elangles_map_mismatch"] += 1

                    dataset_quantity_sets = []
                    quantity_nums = nums if deep_quantities else nums[:1]
                    for num in quantity_nums:
                        dataset_group = time_group.get(f"dataset{num}")
                        if not isinstance(dataset_group, h5py.Group):
                            continue
                        data_nums = data_numbers(dataset_group, "data")
                        if not data_nums:
                            issues.append(f"{pulse}/{time_key}/dataset{num}:missing_data_groups")
                            issue_counts["missing_data_groups"] += 1
                        quantities = set()
                        for key in dataset_group.keys():
                            if DATA_RE.match(key):
                                q = quantity(dataset_group, key)
                                if q:
                                    quantity_counter[q] += 1
                                    quantities.add(q)
                                data = dataset_group[key].get("data") if isinstance(dataset_group[key], h5py.Group) else None
                                if not isinstance(data, h5py.Dataset):
                                    issues.append(f"{pulse}/{time_key}/dataset{num}/{key}:missing_data_dataset")
                                    issue_counts["missing_data_dataset"] += 1
                                elif read_probe:
                                    try:
                                        _ = data[0:1, 0:1]
                                    except Exception as exc:
                                        issues.append(
                                            f"{pulse}/{time_key}/dataset{num}/{key}:read_error:{type(exc).__name__}"
                                        )
                                        issue_counts["read_error"] += 1
                        expected = EXPECTED_QUANTITIES.get(pulse, set())
                        missing = expected - quantities
                        if missing:
                            missing_quantities[pulse].update(missing)
                            issues.append(
                                f"{pulse}/{time_key}/dataset{num}:missing_quantities:{','.join(sorted(missing))}"
                            )
                            issue_counts["missing_quantities"] += 1
                        dataset_quantity_sets.append(tuple(sorted(quantities)))

                    if deep_quantities and len(set(dataset_quantity_sets)) > 1:
                        issues.append(f"{pulse}/{time_key}:inconsistent_dataset_quantities")
                        issue_counts["inconsistent_dataset_quantities"] += 1

                    previous_health_ok = len(issues) == group_issues_before
                    previous_time = minutes if minutes is not None else previous_time

            if not pulses_present:
                issues.append("missing_lp_sp")
                issue_counts["missing_lp_sp"] += 1
    except Exception as exc:
        issues.append(f"hdf5_open_error:{type(exc).__name__}:{exc}")
        issue_counts["hdf5_open_error"] += 1

    has_sqi = int("SQIH" in quantity_counter or "SQIV" in quantity_counter or "SQI" in quantity_counter)
    has_ncp = int(any(q in quantity_counter for q in NORMALISED_COHERENT_POWER_QUANTITIES))
    if not has_sqi:
        issue_counts["missing_sqi"] += 1
        issues.append("file:missing_sqi")
    if not has_ncp:
        issue_counts["missing_normalised_coherent_power"] += 1
        issues.append("file:missing_normalised_coherent_power")

    if issue_counts:
        if "hdf5_open_error" in issue_counts:
            status = "unreadable_or_invalid_hdf5"
        elif "corrupt_gap_boundary" in issue_counts:
            status = "corrupt_gap_boundary"
        elif "missing_quantities" in issue_counts or "missing_normalised_coherent_power" in issue_counts:
            status = "missing_variable"
        else:
            status = "structural_issue"
    else:
        status = "ok"

    return {
        "path": str(path),
        "radar": radar,
        "date": date,
        "radar_num": radar_num,
        "size_bytes": str(stat.st_size),
        "mtime_epoch": str(int(stat.st_mtime)),
        "status": status,
        "issue_count": str(sum(issue_counts.values())),
        "issues": ";".join(issues),
        "pulses": ",".join(pulses_present),
        "time_groups": ",".join(f"{k}:{v}" for k, v in sorted(time_group_counts.items())),
        "dataset_total": str(dataset_total),
        "quantities": ",".join(sorted(quantity_counter)),
        "missing_quantities": ",".join(
            f"{pulse}:{','.join(sorted(values))}" for pulse, values in sorted(missing_quantities.items())
        ),
        "has_sqi": str(has_sqi),
        "has_normalised_coherent_power": str(has_ncp),
        "corrupt_gap_boundaries": ",".join(corrupt_gap_boundaries),
    }


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
]


def write_row(out, row: dict[str, str]) -> None:
    out.write("\t".join(row.get(field, "").replace("\t", " ") for field in FIELDS) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--read-probe", action="store_true")
    parser.add_argument(
        "--deep-quantities",
        action="store_true",
        help="Check quantities for every dataset rather than one representative dataset per time group.",
    )
    parser.add_argument("--progress-every", type=int, default=250)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    scanned = 0
    bad = 0
    with args.manifest.open("r", encoding="utf-8") as manifest, args.output.open(
        "w", encoding="utf-8"
    ) as out:
        out.write("\t".join(FIELDS) + "\n")
        for line in manifest:
            path_text = line.strip()
            if not path_text:
                continue
            scanned += 1
            row = audit_file(
                Path(path_text),
                read_probe=args.read_probe,
                deep_quantities=args.deep_quantities,
            )
            if row["status"] != "ok":
                bad += 1
            write_row(out, row)
            if args.progress_every and scanned % args.progress_every == 0:
                print(f"scanned={scanned} bad={bad}", file=sys.stderr, flush=True)
    print(f"scanned_files={scanned}")
    print(f"bad_files={bad}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
