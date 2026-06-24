#!/usr/bin/env python3
"""Print a compact JSON inventory for HDF5 files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np


def jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        if value.size <= 20:
            return [jsonable(v) for v in value.tolist()]
        return {"shape": list(value.shape), "dtype": str(value.dtype)}
    return value


def attrs(obj: h5py.Dataset | h5py.Group) -> dict[str, Any]:
    return {key: jsonable(value) for key, value in obj.attrs.items()}


def dataset_record(path: str, dset: h5py.Dataset, include_attrs: bool) -> dict[str, Any]:
    dtype = dset.dtype
    fields = list(dtype.fields or [])
    record = {
        "path": path,
        "shape": list(dset.shape),
        "dtype": str(dtype),
        "fields": fields,
    }
    if include_attrs:
        record["attrs"] = attrs(dset)
    return record


def inventory(path: Path, include_attrs: bool) -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []

    with h5py.File(path, "r") as h5:
        root_attrs = attrs(h5) if include_attrs else {}

        def visit(name: str, obj: h5py.Dataset | h5py.Group) -> None:
            full_path = "/" + name
            if isinstance(obj, h5py.Dataset):
                datasets.append(dataset_record(full_path, obj, include_attrs))
            elif isinstance(obj, h5py.Group):
                record = {"path": full_path}
                if include_attrs:
                    record["attrs"] = attrs(obj)
                groups.append(record)

        h5.visititems(visit)

    return {
        "file": str(path),
        "root_attrs": root_attrs,
        "groups": groups,
        "datasets": datasets,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--indent", type=int, default=2)
    parser.add_argument("--attrs", action="store_true", help="Include HDF5 attributes.")
    args = parser.parse_args()

    records = [inventory(path, args.attrs) for path in args.files]
    print(json.dumps(records if len(records) > 1 else records[0], indent=args.indent, sort_keys=True))


if __name__ == "__main__":
    main()
