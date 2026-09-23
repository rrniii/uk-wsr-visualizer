"""Prepare native-preserving RACK evidence without modifying the original pilot."""

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import h5py
import numpy as np
from .core import (
    atomic,
    fields,
    manifest,
    output_path,
    preserved,
    read,
    sha,
    sweeps,
    text,
)


def merge_rack(source, evidence, destination, upstream):
    """Copy only RACK-owned quality groups onto an untouched copy of the source."""
    destination = Path(destination)
    if destination.resolve() in (Path(source).resolve(), Path(evidence).resolve()):
        raise ValueError("Merge destination must be separate")
    if (
        sha(source) != upstream["source_sha256"]
        or sha(evidence) != upstream["output_sha256"]
    ):
        raise ValueError("Unverified RACK inputs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        temporary = Path(tmp) / destination.name
        shutil.copy2(source, temporary)
        count = 0
        with h5py.File(evidence, "r") as src, h5py.File(temporary, "r+") as dst:
            if sweeps(src) != sweeps(dst):
                raise ValueError("RACK sweep set differs")
            for sweep in sweeps(dst):
                for key in ("elangle", "rstart", "rscale", "nrays", "nbins"):
                    if (
                        key not in src[sweep]["where"].attrs
                        or key not in dst[sweep]["where"].attrs
                        or not np.array_equal(
                            src[sweep]["where"].attrs[key],
                            dst[sweep]["where"].attrs[key],
                        )
                    ):
                        raise ValueError("RACK sweep geometry differs")
                source_fields, target_fields = fields(src[sweep]), fields(dst[sweep])
                pairs = [(src[sweep], dst[sweep])]
                for quantity, target in target_fields.items():
                    if (
                        quantity not in source_fields
                        or target["data"].shape != source_fields[quantity]["data"].shape
                    ):
                        raise ValueError("RACK moment geometry differs")
                    pairs.append((source_fields[quantity], target))
                for a, b in pairs:
                    for name, group in a.items():
                        if not re.fullmatch(r"quality\d+", name) or "how" not in group:
                            continue
                        if not text(group["how"].attrs.get("task", "")).startswith(
                            "fi.fmi.Rack"
                        ):
                            continue
                        expected_shape = (
                            b["data"].shape
                            if "data" in b
                            else target_fields["DBZH"]["data"].shape
                        )
                        if "data" not in group or group["data"].shape != expected_shape:
                            raise ValueError("RACK quality geometry differs")
                        index = 1
                        while f"quality{index}" in b:
                            index += 1
                        src.copy(group, b, name=f"quality{index}")
                        count += 1
        if count == 0:
            raise ValueError("No RACK quality evidence found")
        preserved(source, temporary)
        os.replace(temporary, destination)
    record = {
        **upstream,
        "output_path": str(destination),
        "output_sha256": sha(destination),
        "upstream_output_sha256": upstream["output_sha256"],
        "adapter": "native-preserving-rack-merge-v1",
        "adapter_sha256": sha(__file__),
        "quality_groups_copied": count,
    }
    atomic(destination.with_suffix(".provenance.json"), record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--rack-project", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--existing-root", required=True)
    args = parser.parse_args()
    config = read(args.config)
    doc = manifest(config["manifest"])
    case = doc["cases"][args.index]
    sys.path.insert(0, str(Path(args.rack_project) / "src"))
    from uk_wsr_rack.manifest import BenchmarkManifest
    from uk_wsr_rack.processing import process_case, validate_output

    destination = output_path(config, case, "rack")
    if destination.exists() and destination.with_suffix(".provenance.json").exists():
        record = read(destination.with_suffix(".provenance.json"))
        if record.get("output_sha256") == sha(destination) and record.get(
            "source_sha256"
        ) == sha(case["source_path"]):
            preserved(case["source_path"], destination)
            print("Already verified", case["case_id"])
            return
    relative = Path(case["source_path"]).relative_to(config["source_root"])
    existing = Path(args.existing_root) / relative
    if not existing.exists():
        generated = Path(config["state_root"]) / "rack-generated" / "single-site"
        process_case(
            BenchmarkManifest.load(config["manifest"]),
            case["case_id"],
            generated,
            container_image=args.image,
        )
        existing = generated / relative
    validate_output(Path(case["source_path"]), existing)
    print(
        merge_rack(
            case["source_path"],
            existing,
            destination,
            read(existing.with_suffix(".provenance.json")),
        )
    )


if __name__ == "__main__":
    main()
