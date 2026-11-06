"""Archive entrypoints for independently installed radar processors.

Run with the selected vendor's interpreter/environment. No cross-tool runtime
imports occur: only the selected branch imports its vendor package.
"""

import argparse
import os
import sys
from pathlib import Path

import h5py

from .core import atomic, audit_case, manifest, output_path, read, sha, text


def enrich(case):
    source = Path(case["source_path"])
    if sha(source) != case["source_sha256"]:
        raise ValueError("Source changed before processing")
    with h5py.File(source, "r") as h:
        date = text(h["what"].attrs["date"])
        clock = text(h["what"].attrs["time"])
    return {
        **case,
        "date": date,
        "filename": source.name,
        "source_size_bytes": source.stat().st_size,
        "timestamp_utc": f"{date[:4]}-{date[4:6]}-{date[6:]}T{clock[:2]}:{clock[2:4]}:{clock[4:6]}Z",
    }


def process(config, doc, case, processor):
    settings = config["processors"][processor]
    sys.path.insert(0, str(Path(settings["project_root"]) / "src"))
    case = enrich(case)
    case.setdefault("corpus_id", doc.get("manifest_id", "uk_wsr_ops_archive_manifest"))
    destination = output_path(config, case, processor)
    existing = audit_case(config, case, processor)
    if existing["status"] == "integrity_verified":
        return existing
    if destination.exists():
        raise ValueError(
            "Invalid existing evidence requires explicit repair or a new output namespace"
        )
    if processor == "pyrad":
        from uk_wsr_pyrad.cleaning import process_clean_pvol

        process_clean_pvol(
            source=case["source_path"],
            output=destination,
            case=case,
            manifest_hash=doc["manifest_sha256"],
            assets_root=settings["assets_root"],
            scratch_root=settings.get("scratch_root"),
            require_pyrad=True,
        )
    elif processor == "baltrad":
        from uk_wsr_baltrad.processing import process_case, output_path_for_case

        parent = Path(settings["output_root"]).parent
        if output_path_for_case(case, parent) != destination:
            raise ValueError("BALTRAD archive hierarchy mismatch")
        process_case(
            case,
            output_root=parent,
            maps_dir=settings["maps_dir"],
            options_path=settings["options_path"],
            runtime_digest=settings["runtime_digest"],
            slurm_job_id=os.environ.get("SLURM_JOB_ID"),
        )
    elif processor == "lrose":
        from uk_wsr_lrose.processor_v2 import process_entry_v2
        from uk_wsr_lrose.processor import output_path as lrose_output

        root = Path(settings["output_root"])
        if lrose_output(case, root) != destination:
            raise ValueError("LROSE archive hierarchy mismatch")
        process_entry_v2(
            case,
            root,
            Path(settings["scratch_root"]),
            Path(settings["lrose_bin"]),
            Path(settings["era5_root"]),
            Path(settings["coefficients"]),
            Path(settings["cband_thresholds"]),
            Path(settings["noise_config"]),
            Path(settings["map_set"]),
        )
    elif processor == "rack":
        from uk_wsr_rack.manifest import Case
        from uk_wsr_rack.processing import process_case
        from .prepare import merge_rack

        # RACK's processing API accepts the manifest interface; the frozen
        # benchmark loader is deliberately not used to reinterpret archive cases.
        class ArchiveInput:
            raw = {"manifest_id": doc.get("manifest_id", "uk_wsr_ops_archive_manifest")}
            sha256 = doc["manifest_sha256"]

            def case(self, case_id):
                if case_id != case["case_id"]:
                    raise KeyError(case_id)
                return Case(
                    case_id,
                    case["radar"],
                    case["pulse"],
                    case.get("season", "archive"),
                    case["source_path"],
                    case["source_sha256"],
                    case["source_size_bytes"],
                )

            def verify_source(self, case_id):
                c = self.case(case_id)
                if sha(c.source_path) != c.source_sha256:
                    raise ValueError("Archive source changed")
                return Path(c.source_path)

        generated_root = Path(settings["generated_root"])
        result = process_case(
            ArchiveInput(),
            case["case_id"],
            generated_root,
            container_image=settings["image"],
        )
        generated = generated_root / Path(case["source_path"]).relative_to(
            config["source_root"]
        )
        provenance = read(generated.with_suffix(".provenance.json"))
        merge_rack(case["source_path"], generated, destination, provenance)
    else:
        raise ValueError("Unknown processor")
    result = audit_case(config, case, processor)
    if result["status"] != "integrity_verified":
        raise ValueError(str(result["errors"]))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--processor", required=True)
    args = parser.parse_args()
    config = read(args.config)
    doc = manifest(config["manifest"])
    case = next(c for c in doc["cases"] if c["case_id"] == args.case_id)
    result = process(config, doc, case, args.processor)
    atomic(
        Path(config["state_root"])
        / "vendor-records"
        / args.processor
        / (case["case_id"] + ".json"),
        result,
    )
    print(result["status"])


if __name__ == "__main__":
    main()
