#!/usr/bin/env python3
"""Scan ODIM quantity signatures across Avocet aggregate HDF5 files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import h5py
import numpy as np


DATA_RE = re.compile(
    r"^(?P<pulse>[^/]+)/(?P<time>\d{4})/dataset(?P<dataset>\d+)/"
    r"(?P<kind>data|quality)(?P<index>\d+)$"
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


def iter_aggregate_files(base: Path, radar: str | None, year: str | None):
    root = base
    if radar:
        root = root / radar
    if year:
        if not radar:
            raise ValueError("--year requires --radar")
        root = root / year
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in sorted(filenames):
            if filename.endswith("_aggregate.h5"):
                yield Path(dirpath) / filename


def pulse_signatures(path: Path) -> dict[str, tuple[str, ...]]:
    rows: list[tuple[str, str, str]] = []
    with h5py.File(path, "r") as h5:
        def visit(name: str, obj: h5py.Group | h5py.Dataset) -> None:
            if not isinstance(obj, h5py.Group):
                return
            match = DATA_RE.match(name)
            if match:
                rows.append(
                    (
                        match.group("pulse"),
                        match.group("time"),
                        quantity_from_data_group(obj),
                    )
                )

        h5.visititems(visit)

    by_pulse_time: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for pulse, time, quantity in rows:
        by_pulse_time[pulse][time].add(quantity)

    signatures: dict[str, tuple[str, ...]] = {}
    for pulse, by_time in by_pulse_time.items():
        per_time = {tuple(sorted(quantities)) for quantities in by_time.values()}
        if len(per_time) == 1:
            signatures[pulse] = next(iter(per_time))
        else:
            flattened = sorted({"|".join(signature) for signature in per_time})
            signatures[pulse] = tuple(f"<mixed:{sig}>" for sig in flattened)
    return signatures


def signature_key(signatures: dict[str, tuple[str, ...]]) -> str:
    return ";".join(
        f"{pulse}:{','.join(quantities)}"
        for pulse, quantities in sorted(signatures.items())
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site"),
    )
    parser.add_argument("--radar")
    parser.add_argument("--year")
    parser.add_argument("--max-files", type=int)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    file_signature_counts: Counter[str] = Counter()
    pulse_signature_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, str] = {}
    errors: list[dict[str, str]] = []

    scanned = 0
    for path in iter_aggregate_files(args.base, args.radar, args.year):
        if args.max_files is not None and scanned >= args.max_files:
            break
        scanned += 1
        if args.progress_every and scanned % args.progress_every == 0:
            print(f"scanned {scanned}", file=sys.stderr, flush=True)
        try:
            signatures = pulse_signatures(path)
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue

        key = signature_key(signatures)
        file_signature_counts[key] += 1
        examples.setdefault(key, str(path))
        for pulse, quantities in signatures.items():
            pulse_signature_counts[pulse][",".join(quantities)] += 1

    output = {
        "base": str(args.base),
        "radar": args.radar,
        "year": args.year,
        "scanned_files": scanned,
        "readable_files": sum(file_signature_counts.values()),
        "error_count": len(errors),
        "errors": errors[:20],
        "file_signature_counts": [
            {"count": count, "signature": key, "example": examples[key]}
            for key, count in file_signature_counts.most_common()
        ],
        "pulse_signature_counts": {
            pulse: [
                {"count": count, "quantities": key.split(",") if key else []}
                for key, count in counter.most_common()
            ]
            for pulse, counter in sorted(pulse_signature_counts.items())
        },
    }
    print(json.dumps(output, indent=args.indent, sort_keys=True))


if __name__ == "__main__":
    main()
