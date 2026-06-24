#!/usr/bin/env python3
"""Summarize ODIM HDF5 data quantities without reading array payloads."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import h5py
import numpy as np


DATA_RE = re.compile(
    r"^(?P<pulse>[^/]+)/(?P<time>\d{4})/dataset(?P<dataset>\d+)/"
    r"(?P<field_type>data|quality)(?P<data>\d+)$"
)


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


def summarize_file(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    with h5py.File(path, "r") as h5:
        root_keys = list(h5.keys())
        root_attrs = {k: scalar(v) for k, v in h5.attrs.items()}

        def visit(name: str, obj: h5py.Group | h5py.Dataset) -> None:
            if not isinstance(obj, h5py.Group):
                return
            match = DATA_RE.match(name)
            if not match:
                return
            rows.append(
                {
                    **match.groupdict(),
                    "quantity": quantity_from_data_group(obj),
                    "shape": list(obj["data"].shape) if "data" in obj else None,
                    "dtype": str(obj["data"].dtype) if "data" in obj else None,
                }
            )

        h5.visititems(visit)

    by_pulse: dict[str, Any] = {}
    for pulse in sorted({row["pulse"] for row in rows}):
        pulse_rows = [row for row in rows if row["pulse"] == pulse]
        times = sorted({row["time"] for row in pulse_rows})
        quantities_by_time = defaultdict(set)
        for row in pulse_rows:
            quantities_by_time[row["time"]].add(row["quantity"])
        signatures = Counter(tuple(sorted(values)) for values in quantities_by_time.values())
        by_pulse[pulse] = {
            "time_count": len(times),
            "first_time": times[0] if times else None,
            "last_time": times[-1] if times else None,
            "quantities": sorted({row["quantity"] for row in pulse_rows}),
            "quantity_signature_counts": [
                {"quantities": list(signature), "time_count": count}
                for signature, count in signatures.most_common()
            ],
            "sample_rows": pulse_rows[:20],
        }

    return {
        "file": str(path),
        "root_keys": root_keys,
        "root_attrs": root_attrs,
        "data_group_count": len(rows),
        "by_pulse": by_pulse,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    records = [summarize_file(path) for path in args.files]
    print(json.dumps(records if len(records) > 1 else records[0], indent=args.indent, sort_keys=True))


if __name__ == "__main__":
    main()
