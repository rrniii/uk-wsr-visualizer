#!/usr/bin/env python3
"""Compare raw NIMROD fields with variables present in Avocet aggregate HDF5 files."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import h5py
import numpy as np


RADAR_NUMS = {
    "castor-bay": "07",
    "chenies": "05",
    "clee-hill": "03",
    "cobbacombe": "16",
    "crug-y-gorrllwyn": "10",
    "deanhill": "21",
    "druima-starraig": "15",
    "dudwick": "14",
    "hameldon-hill": "04",
    "high-moorsley": "23",
    "holehead": "18",
    "ingham": "09",
    "jersey": "12",
    "munduff-hill": "19",
    "predannack": "08",
    "thurnham": "20",
    "wardon-hill": "11",
}

DATA_RE = re.compile(
    r"^(?P<pulse>[^/]+)/(?P<time>\d{4})/dataset(?P<dataset>\d+)/"
    r"(?P<kind>data|quality)(?P<index>\d+)$"
)

SOURCE_ROOTS = [
    Path("/badc/ukmo-nimrod/data/single-site/storage_by_year"),
    Path("/badc/ukmo-nimrod/data/single-site"),
]


def scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        if value.shape == ():
            return scalar(value.item())
        if value.size == 1:
            return scalar(value.reshape(-1)[0])
        return [scalar(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return scalar(value.item())
    return value


def quantity_from_data_group(group: h5py.Group) -> str:
    what = group.get("what")
    if isinstance(what, h5py.Group) and "quantity" in what.attrs:
        return str(scalar(what.attrs["quantity"]))
    return "<missing quantity>"


def aggregate_quantities(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    original_filenames_by_pulse: dict[str, list[str]] = defaultdict(list)
    with h5py.File(path, "r") as h5:
        root_keys = list(h5.keys())

        def visit(name: str, obj: h5py.Group | h5py.Dataset) -> None:
            if not isinstance(obj, h5py.Group):
                return
            match = DATA_RE.match(name)
            if match:
                rows.append({**match.groupdict(), "quantity": quantity_from_data_group(obj)})
                return

            parts = name.split("/")
            if (
                len(parts) == 3
                and parts[1].isdigit()
                and parts[2].startswith("dataset")
                and "original_filename" in obj.attrs
            ):
                original_filenames_by_pulse[parts[0]].append(str(scalar(obj.attrs["original_filename"])))
                return

        h5.visititems(visit)

    by_pulse: dict[str, Any] = {}
    for pulse in sorted({row["pulse"] for row in rows}):
        pulse_rows = [row for row in rows if row["pulse"] == pulse]
        quantities_by_time: dict[str, set[str]] = defaultdict(set)
        for row in pulse_rows:
            quantities_by_time[row["time"]].add(row["quantity"])
        by_pulse[pulse] = {
            "quantities": sorted({row["quantity"] for row in pulse_rows}),
            "time_count": len(quantities_by_time),
            "quantity_signatures": sorted(
                {
                    tuple(sorted(values))
                    for values in quantities_by_time.values()
                }
            ),
        }
    return {
        "path": str(path),
        "root_keys": root_keys,
        "by_pulse": by_pulse,
        "original_filenames_by_pulse": {
            pulse: sorted(set(names)) for pulse, names in original_filenames_by_pulse.items()
        },
    }


def raw_tar_path(radar: str, date: str, pulse: str, zdr_kind: str = "augzdr") -> Path | None:
    year = date[:4]
    name = f"metoffice-c-band-rain-radar_{radar}_{date}_raw-dual-polar-{zdr_kind}-{pulse}.dat.gz.tar"
    candidates = [
        SOURCE_ROOTS[0] / year / radar / "raw-dual-polar" / year / name,
        SOURCE_ROOTS[1] / radar / "raw-dual-polar" / year / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def choose_members(path: Path, sample_count: int, preferred: list[str] | None = None) -> list[str]:
    with tarfile.open(path) as tar:
        names = sorted(member.name for member in tar.getmembers() if member.isfile())
    if preferred:
        preferred_set = set(preferred)
        names_by_base = {Path(name).name: name for name in names}
        preferred_names = [names_by_base[name] for name in preferred if name in names_by_base]
        if len(preferred_names) <= sample_count:
            return preferred_names
        indexes = np.linspace(0, len(preferred_names) - 1, sample_count, dtype=int)
        return [preferred_names[int(i)] for i in indexes]
    if len(names) <= sample_count:
        return names
    if sample_count <= 1:
        return [names[0]]
    indexes = np.linspace(0, len(names) - 1, sample_count, dtype=int)
    return [names[int(i)] for i in indexes]


def raw_variable_set(rad: Any) -> dict[str, Any]:
    direct = {
        "DBZH": "decoded from nc_Zh",
        "CI": "decoded from nc_CI",
        "VRADH": "decoded from nc_vel",
        "SQIH": "decoded from nc_SQI",
        "RAW_WIDTH": "decoded from nc_width; converter comment says not encoded/useful",
        "LONG_RANGE_NOISE_DBC_H": "decoded from per-ray H noise",
        "LONG_RANGE_NOISE_DBC_V": "decoded from per-ray V noise",
    }
    if rad.derived_data_type == 2213:
        direct.update(
            {
                "ZDR": "decoded from nc_Zdr",
                "RHOHV": "decoded from nc_rhohv",
                "PHIDP": "decoded from nc_phidp",
            }
        )
    elif rad.derived_data_type == 2212:
        direct.update(
            {
                "LDR": "decoded from nc_Ldr",
                "APHIV": "decoded from nc_APhiV",
            }
        )

    derived = {}
    if rad.pulse_length != getattr(sys.modules["dualpol"], "SHORT_PULSE_LENGTH"):
        derived["WRADH"] = "calculated by converter from SQI/noise for long pulse"
    return {"direct": direct, "derived_available": derived}


def width_summary(rad: Any) -> dict[str, Any]:
    values, counts = np.unique(rad.nc_width, return_counts=True)
    order = np.argsort(counts)[::-1]
    top = [
        {"value": float(values[i]), "count": int(counts[i])}
        for i in order[:10]
    ]
    return {
        "min": float(np.nanmin(rad.nc_width)),
        "max": float(np.nanmax(rad.nc_width)),
        "unique_count": int(len(values)),
        "top_values": top,
    }


def parse_raw_samples(tar_path: Path, members: list[str], converter_path: Path) -> list[dict[str, Any]]:
    sys.path.insert(0, str(converter_path))
    from dualpol import SingleSite  # type: ignore

    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="avocet_raw_compare_") as tmp:
        tmpdir = Path(tmp)
        with tarfile.open(tar_path) as tar:
            for name in members:
                member = tar.getmember(name)
                source = tar.extractfile(member)
                if source is None:
                    continue
                tmp_file = tmpdir / Path(name).name
                tmp_file.write_bytes(source.read())
                try:
                    rad = SingleSite(str(tmp_file))
                except Exception as exc:
                    records.append(
                        {
                            "member": name,
                            "parse_error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                variables = raw_variable_set(rad)
                records.append(
                    {
                        "member": name,
                        "derived_data_type": int(rad.derived_data_type),
                        "pulse_length": float(rad.pulse_length),
                        "number_of_bins": int(rad.number_of_bins_in_ray),
                        "number_of_rays": int(rad.number_of_rays_in_scan),
                        "file_time": rad.get_file_time_str(with_seconds=True),
                        "variables": variables,
                        "width_summary": width_summary(rad),
                    }
                )
    return records


def compare_one(
    radar: str,
    date: str,
    aggregate_base: Path,
    converter_path: Path,
    sample_count: int,
    include_ldr: bool,
) -> dict[str, Any]:
    year = date[:4]
    radar_num = RADAR_NUMS[radar]
    aggregate_path = (
        aggregate_base / radar / year / f"{date}_polar_pl_radar{radar_num}_aggregate.h5"
    )
    agg = aggregate_quantities(aggregate_path)

    raw: dict[str, Any] = {}
    for pulse, zdr_kind in [("lp", "augzdr"), ("sp", "augzdr")]:
        tar_path = raw_tar_path(radar, date, pulse, zdr_kind)
        if tar_path is None:
            raw[pulse] = {"tar": None, "samples": [], "error": "missing tar"}
            continue
        members = choose_members(
            tar_path,
            sample_count,
            agg.get("original_filenames_by_pulse", {}).get(pulse),
        )
        raw[pulse] = {
            "tar": str(tar_path),
            "member_count": len(members),
            "sampled_members": members,
            "samples": parse_raw_samples(tar_path, members, converter_path),
        }
    if include_ldr:
        tar_path = raw_tar_path(radar, date, "lp", "augldr")
        if tar_path is not None:
            members = choose_members(
                tar_path,
                sample_count,
                agg.get("original_filenames_by_pulse", {}).get("ldr"),
            )
            raw["ldr"] = {
                "tar": str(tar_path),
                "member_count": len(members),
                "sampled_members": members,
                "samples": parse_raw_samples(tar_path, members, converter_path),
            }

    comparisons: dict[str, Any] = {}
    for pulse, raw_record in raw.items():
        direct: dict[str, str] = {}
        derived_available: dict[str, str] = {}
        for sample in raw_record.get("samples", []):
            if "variables" not in sample:
                continue
            direct.update(sample["variables"]["direct"])
            derived_available.update(sample["variables"]["derived_available"])
        agg_quantities = set(agg["by_pulse"].get(pulse, {}).get("quantities", []))
        direct_quantities = set(direct)
        derived_quantities = set(derived_available)
        comparisons[pulse] = {
            "raw_direct_quantities": sorted(direct_quantities),
            "raw_derived_available": sorted(derived_quantities),
            "aggregate_quantities": sorted(agg_quantities),
            "missing_direct_from_aggregate": sorted(direct_quantities - agg_quantities),
            "derived_available_but_absent": sorted(derived_quantities - agg_quantities),
            "aggregate_not_direct_raw": sorted(agg_quantities - direct_quantities),
        }

    return {
        "radar": radar,
        "date": date,
        "aggregate": agg,
        "raw": raw,
        "comparisons": comparisons,
    }


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    raw_summary: dict[str, Any] = {}
    for pulse, raw_record in result["raw"].items():
        samples = raw_record.get("samples", [])
        successful = [sample for sample in samples if "variables" in sample]
        raw_summary[pulse] = {
            "tar": raw_record.get("tar"),
            "sampled_members": raw_record.get("sampled_members", []),
            "successful_sample_count": len(successful),
            "parse_errors": [
                {"member": sample.get("member"), "parse_error": sample.get("parse_error")}
                for sample in samples
                if "parse_error" in sample
            ],
            "sample_summaries": [
                {
                    "member": sample["member"],
                    "derived_data_type": sample["derived_data_type"],
                    "pulse_length": sample["pulse_length"],
                    "number_of_bins": sample["number_of_bins"],
                    "number_of_rays": sample["number_of_rays"],
                    "width_summary": sample["width_summary"],
                }
                for sample in successful
            ],
        }

    aggregate_summary = {
        "path": result["aggregate"]["path"],
        "root_keys": result["aggregate"]["root_keys"],
        "by_pulse": result["aggregate"]["by_pulse"],
    }
    return {
        "radar": result["radar"],
        "date": result["date"],
        "aggregate": aggregate_summary,
        "raw": raw_summary,
        "comparisons": result["comparisons"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--radar", required=True, choices=sorted(RADAR_NUMS))
    parser.add_argument("--date", required=True, help="YYYYMMDD")
    parser.add_argument(
        "--aggregate-base",
        type=Path,
        default=Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site"),
    )
    parser.add_argument(
        "--converter-path",
        type=Path,
        default=Path("/home/users/rrniii/bin/Nimrod_convert_and_aggregate/Radar_ODIM_conv"),
    )
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--include-ldr", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    result = compare_one(
        args.radar,
        args.date,
        args.aggregate_base,
        args.converter_path,
        args.sample_count,
        args.include_ldr,
    )
    if args.summary:
        result = compact_result(result)
    print(json.dumps(result, indent=args.indent, sort_keys=True))


if __name__ == "__main__":
    main()
