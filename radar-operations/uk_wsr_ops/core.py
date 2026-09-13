from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import h5py
import numpy as np

BENCHMARK_HASH = "dd04f81a81167077df92cbaec66603ee2bfb745b9cbc6dcf82be626da128194e"
PROCESSORS = ("baltrad", "pyrad", "lrose", "rack")
SIDECARS = {
    "baltrad": ".provenance.json",
    "pyrad": ".pyrad.json",
    "lrose": ".json",
    "rack": ".provenance.json",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,180}", value
    ):
        raise ValueError("Invalid identifier")
    return value


def manifest(path):
    doc = read(path)
    content = {k: v for k, v in doc.items() if k != "manifest_sha256"}
    if digest(content) != doc.get("manifest_sha256"):
        raise ValueError("Manifest checksum mismatch")
    cases = doc.get("cases", [])
    if not cases or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Empty or duplicate case manifest")
    for c in cases:
        safe_id(c["case_id"])
        if not re.fullmatch("[0-9a-f]{64}", c["source_sha256"]):
            raise ValueError("Invalid source checksum")
    if doc.get("manifest_id") == "uk-wsr-processing-fast-v1":
        if doc["manifest_sha256"] != BENCHMARK_HASH or len(cases) != 68:
            raise ValueError("Frozen benchmark changed")
    elif doc.get("schema") != "uk_wsr_ops_archive_manifest":
        raise ValueError("Unknown manifest schema")
    return doc


def output_path(config, case, processor):
    relative = (
        Path(case["source_path"])
        .resolve()
        .relative_to(Path(config["source_root"]).resolve())
    )
    destination = (
        Path(config["processors"][processor]["output_root"]).resolve() / relative
    )
    if destination == Path(case["source_path"]).resolve():
        raise ValueError("Output cannot overwrite source")
    return destination


def text(value):
    return value.decode() if isinstance(value, bytes) else str(value)


def sweeps(handle):
    return sorted(
        (k for k in handle if re.fullmatch(r"dataset\d+", k)), key=lambda k: int(k[7:])
    )


def fields(sweep):
    return {
        text(g["what"].attrs["quantity"]): g
        for n, g in sweep.items()
        if re.fullmatch(r"data\d+", n)
        and isinstance(g, h5py.Group)
        and "data" in g
        and "what" in g
        and "quantity" in g["what"].attrs
    }


def physical(group):
    raw = group["data"][()]
    attrs = group["what"].attrs
    result = raw.astype(float) * float(attrs.get("gain", 1)) + float(
        attrs.get("offset", 0)
    )
    # Undetect is no measured echo, not a labelled background/noise observation.
    for name in ("nodata", "undetect"):
        if name in attrs:
            result[raw == attrs[name]] = np.nan
    return result


def same(a, b):
    try:
        return np.array_equal(a, b, equal_nan=True)
    except TypeError:
        return np.array_equal(a, b)


def preserved(source, output):
    """Check every original object, value, datatype and attribute, including quality groups."""
    with h5py.File(source, "r") as src, h5py.File(output, "r") as out:

        def check(name, obj):
            if name not in out:
                raise ValueError(f"Missing original object: {name}")
            other = out[name]
            if isinstance(obj, h5py.Dataset):
                if (
                    not isinstance(other, h5py.Dataset)
                    or obj.dtype != other.dtype
                    or not same(obj[()], other[()])
                ):
                    raise ValueError(f"Original data changed: {name}")
            elif not isinstance(other, h5py.Group):
                raise ValueError(f"Original group changed: {name}")
            for key, value in obj.attrs.items():
                if key not in other.attrs or not same(value, other.attrs[key]):
                    raise ValueError(f"Original attribute changed: {name}/{key}")

        check("/", src)
        src.visititems(check)


def audit_case(config, case, processor):
    row = {
        "case_id": case["case_id"],
        "processor": processor,
        "radar": case["radar"],
        "pulse": case["pulse"],
        "season": case.get("season"),
        "status": "failed",
        "errors": [],
    }
    source = Path(case["source_path"])
    output = output_path(config, case, processor)
    row["output_path"] = str(output)
    try:
        if not source.is_file():
            row["status"] = "source_missing"
            return row
        if sha(source) != case["source_sha256"]:
            raise ValueError("Source checksum mismatch")
        if not output.is_file():
            row["status"] = "output_missing"
            return row
        sidecar = (
            output.with_suffix(".provenance.json")
            if processor == "rack"
            else Path(str(output) + SIDECARS[processor])
        )
        if not sidecar.is_file():
            row["status"] = "provenance_missing"
            return row
        provenance = read(sidecar)
        if provenance.get("source_sha256") != case["source_sha256"]:
            raise ValueError("Provenance source checksum mismatch")
        if provenance.get("output_sha256") != sha(output):
            raise ValueError("Output checksum mismatch")
        if provenance.get("case_id", case["case_id"]) != case["case_id"]:
            raise ValueError("Provenance case mismatch")
        preserved(source, output)
        row.update(
            status="integrity_verified",
            output_sha256=provenance["output_sha256"],
            provenance_sha256=sha(sidecar),
            output_bytes=output.stat().st_size,
        )
        with h5py.File(output, "r") as handle:
            row["sweeps"] = [
                {
                    "name": n,
                    "elevation": float(handle[n]["where"].attrs["elangle"]),
                    "fields": sorted(fields(handle[n])),
                }
                for n in sweeps(handle)
            ]
        # This is integrity acceptance only; scientific qualification is a separate record.
    except (OSError, ValueError, KeyError, TypeError) as exc:
        row["errors"].append(str(exc))
    return row
