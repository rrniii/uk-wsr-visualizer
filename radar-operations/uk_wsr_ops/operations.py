"""Versioned operational publication. Scientific approval is an explicit input."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import h5py
import numpy as np

from .core import (
    atomic,
    audit_case,
    digest,
    fields,
    output_path,
    physical,
    preserved,
    read,
    safe_id,
    sha,
    sweeps,
)
from .policies import POLICIES, decide


def code_digest():
    return digest({p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))})


def geometry_id(source):
    with h5py.File(source, "r") as h:
        values = [
            {
                "name": n,
                "shape": list(fields(h[n])["DBZH"]["data"].shape)
                if "DBZH" in fields(h[n])
                else None,
                "where": {
                    k: float(h[n]["where"].attrs[k])
                    for k in ("elangle", "rstart", "rscale", "nrays", "nbins")
                    if k in h[n]["where"].attrs
                },
            }
            for n in sweeps(h)
        ]
    return digest(values)


def approved(decision, processor):
    if decision.get("status") != "approved" or decision.get("processor") != processor:
        raise ValueError("A scientific decision selecting this processor is required")
    safe_id(decision.get("reviewer"))
    if (
        not decision.get("rationale")
        or decision.get("blocking_failures") != []
        or decision.get("coherent_echo_loss_accepted") is not False
    ):
        raise ValueError("Scientific decision has unresolved acceptance conditions")
    if (
        decision.get("policy_sha256") != digest(POLICIES[processor])
        or decision.get("code_sha256") != code_digest()
    ):
        raise ValueError("Scientific decision does not match exact code and policy")
    if not decision.get("supported_groups") or not decision.get(
        "review_evidence_sha256"
    ):
        raise ValueError("Scientific decision lacks scope or review evidence")
    evidence_path = decision.get("review_evidence_path")
    if (
        not evidence_path
        or not Path(evidence_path).is_file()
        or sha(evidence_path) != decision["review_evidence_sha256"]
    ):
        raise ValueError("Scientific review evidence is missing or changed")
    evidence = read(evidence_path)
    if (
        not isinstance(evidence, list)
        or not evidence
        or not any(
            r.get("source_first") and r.get("action") == "retain" for r in evidence
        )
        or not any(
            r.get("source_first") and r.get("action") == "remove" for r in evidence
        )
    ):
        raise ValueError(
            "Scientific review requires source-first retain and artefact evidence"
        )


def append_field(sweep, name, data):
    if name in fields(sweep):
        raise ValueError("Derived quantity already exists")
    index = 1
    while f"data{index}" in sweep:
        index += 1
    group = sweep.create_group(f"data{index}")
    what = group.create_group("what")
    for key, value in {
        "quantity": name,
        "gain": 1.0,
        "offset": 0.0,
        "nodata": -9999.0,
        "undetect": -9998.0,
    }.items():
        what.attrs[key] = value
    group.create_dataset(
        "data",
        data=np.where(np.isfinite(data), data, -9999.0).astype("float32"),
        compression="gzip",
    )


def clean_product(source, evidence, destination, processor):
    """Append canonical cleaned views to source; never modify original groups."""
    destination = Path(destination)
    if destination.resolve() in (Path(source).resolve(), Path(evidence).resolve()):
        raise ValueError("Cleaned destination must be separate")
    preserved(source, evidence)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stats = []
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary_dir:
        temporary = Path(temporary_dir) / destination.name
        shutil.copy2(source, temporary)
        with h5py.File(evidence, "r") as src, h5py.File(temporary, "r+") as dst:
            for sweep in sweeps(dst):
                ff = fields(dst[sweep])
                if "DBZH" not in ff:
                    stats.append({"sweep": sweep, "status": "unsupported_no_dbzh"})
                    continue
                decision = decide(src[sweep], processor)
                shape = decision["remove"].shape
                cleaned = []
                for name, group in list(ff.items()):
                    if (
                        name
                        not in (
                            "DBZH",
                            "TH",
                            "ZDR",
                            "RHOHV",
                            "VRADH",
                            "WRADH",
                            "PHIDP",
                            "SQIH",
                        )
                        or group["data"].shape != shape
                    ):
                        continue
                    data = physical(group)
                    data[decision["remove"]] = np.nan
                    append_field(dst[sweep], name + "_CLEAN_OPS", data)
                    cleaned.append(name)
                values = np.where(
                    decision["supported"],
                    np.where(
                        decision["remove"], 1, np.where(decision["uncertain"], 2, 0)
                    ),
                    3,
                ).astype(float)
                values[~decision["valid"]] = np.nan
                append_field(dst[sweep], "QC_DECISION_OPS", values)
                append_field(
                    dst[sweep], "QC_REASON_OPS", decision["reasons"].astype(float)
                )
                stats.append(
                    {
                        "sweep": sweep,
                        "cleaned_fields": cleaned,
                        "valid": int(decision["valid"].sum()),
                        "supported": int(decision["supported"].sum()),
                        "removed": int(decision["remove"].sum()),
                        "uncertain": int(decision["uncertain"].sum()),
                    }
                )
        preserved(source, temporary)
        validate_cleaned(source, evidence, temporary, processor)
        os.replace(temporary, destination)
    return stats


def validate_cleaned(source, evidence, product, processor):
    preserved(source, product)
    with (
        h5py.File(source, "r") as native,
        h5py.File(evidence, "r") as diagnostics,
        h5py.File(product, "r") as output,
    ):
        for sweep in sweeps(native):
            ff, out = fields(native[sweep]), fields(output[sweep])
            if "DBZH" not in ff:
                continue
            decision = decide(diagnostics[sweep], processor)
            for name, group in ff.items():
                if (
                    name
                    not in (
                        "DBZH",
                        "TH",
                        "ZDR",
                        "RHOHV",
                        "VRADH",
                        "WRADH",
                        "PHIDP",
                        "SQIH",
                    )
                    or group["data"].shape != decision["remove"].shape
                ):
                    continue
                if name + "_CLEAN_OPS" not in out:
                    raise ValueError("Missing cleaned moment")
                expected = physical(group)
                expected[decision["remove"]] = np.nan
                actual = physical(out[name + "_CLEAN_OPS"])
                if not np.array_equal(
                    np.isfinite(actual), np.isfinite(expected)
                ) or not np.allclose(
                    actual, expected, equal_nan=True, atol=1e-5, rtol=1e-6
                ):
                    raise ValueError("Cleaned mask or retained values differ")


def run_one(config, release_path, case, decision):
    release_path = Path(release_path)
    processor = decision["processor"]
    approved(decision, processor)
    dependencies = config["processors"][processor].get("dependency_sha256", {})
    if not dependencies or decision.get("runtime_identity_sha256") != digest(
        dependencies
    ):
        raise ValueError("Selected runtime/calibration identity is not frozen")
    for dependency, expected in dependencies.items():
        if sha(dependency) != expected:
            raise ValueError("Runtime/calibration dependency changed: " + dependency)
    group = f"{case['radar']}|{case['pulse']}|{geometry_id(case['source_path'])}"
    if group not in decision["supported_groups"]:
        raise ValueError("Radar/pulse group is not approved")
    release_id = digest({"decision": decision, "code": code_digest()})[:20]
    root = release_path / release_id
    root.mkdir(parents=True, exist_ok=True)
    safe_id(case["case_id"])
    record_path = root / "records" / (case["case_id"] + ".json")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(record_path) + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        relative = (
            Path(case["source_path"])
            .resolve()
            .relative_to(Path(config["source_root"]).resolve())
        )
        output = root / "single-site" / relative
        if record_path.exists():
            old = read(record_path)
            evidence = output_path(config, case, processor)
            if (
                old.get("status") == "validated"
                and old.get("source_sha256") == sha(case["source_path"])
                and output.is_file()
                and old.get("output_sha256") == sha(output)
                and evidence.exists()
                and old.get("evidence_sha256") == sha(evidence)
            ):
                return old
        row = {
            "case_id": case["case_id"],
            "radar": case["radar"],
            "pulse": case["pulse"],
            "release_id": release_id,
            "source_sha256": case["source_sha256"],
            "status": "running",
            "started": time.time(),
        }
        atomic(record_path, row)
        try:
            audit = audit_case(config, case, processor)
            if audit["status"] != "integrity_verified":
                # Optional independently installed processor command; shell execution is forbidden.
                command = config["processors"][processor].get("command")
                if not command:
                    raise ValueError(
                        "Upstream evidence not verified; processor command is not configured"
                    )
                values = {
                    "config": config.get("_config_path", ""),
                    "source": case["source_path"],
                    "output": str(output_path(config, case, processor)),
                    "case_id": case["case_id"],
                    "manifest": config["manifest"],
                }
                if any("{config}" in arg for arg in command) and not values["config"]:
                    raise ValueError(
                        "Processor command requires the active configuration path"
                    )
                for attempt in range(3):
                    completed = subprocess.run(
                        [arg.format_map(values) for arg in command],
                        capture_output=True,
                        text=True,
                        env={
                            **os.environ,
                            **config["processors"][processor].get("environment", {}),
                        },
                    )
                    if completed.returncode == 0:
                        break
                    if completed.returncode not in (75, 124):
                        raise ValueError(
                            "Processor failed deterministically: "
                            + completed.stderr[-1000:]
                        )
                audit = audit_case(config, case, processor)
                if audit["status"] != "integrity_verified":
                    raise ValueError(
                        "Upstream evidence failed validation: " + str(audit["errors"])
                    )
            row["sweeps"] = clean_product(
                case["source_path"], audit["output_path"], output, processor
            )
            row.update(
                status="validated",
                output_path=str(output),
                output_sha256=sha(output),
                runtime_identity_sha256=digest(dependencies),
                evidence_sha256=audit["output_sha256"],
                code_sha256=code_digest(),
                policy_sha256=digest(POLICIES[processor]),
                completed=time.time(),
            )
            atomic(record_path, row)
            return row
        except Exception as exc:
            row.update(status="failed", error=str(exc), completed=time.time())
            atomic(record_path, row)
            raise


def publish_catalog(release_root, doc, decision):
    processor = decision["processor"]
    approved(decision, processor)
    root = (
        Path(release_root) / digest({"decision": decision, "code": code_digest()})[:20]
    )
    entries, pending = [], []
    for case in doc["cases"]:
        record_path = root / "records" / (case["case_id"] + ".json")
        if not record_path.exists():
            pending.append(case["case_id"])
            continue
        record = read(record_path)
        if record.get("status") != "validated":
            pending.append(case["case_id"])
            continue
        if (
            record["source_sha256"] != case["source_sha256"]
            or sha(record["output_path"]) != record["output_sha256"]
        ):
            raise ValueError("Catalogue references a stale or altered product")
        entries.append(record)
    if not entries:
        raise ValueError("No validated products to publish")
    catalogue = {
        "schema": "uk_wsr_ops_catalogue",
        "schema_version": 1,
        "release_id": root.name,
        "manifest_sha256": doc["manifest_sha256"],
        "entries": entries,
        "pending": pending,
        "requested_count": len(doc["cases"]),
        "validated_count": len(entries),
        "default_quantity": "DBZH_CLEAN_OPS",
        "source_fallback": False,
        "decision": decision,
    }
    atomic(root / "catalogue.json", catalogue)
    return root / "catalogue.json"


def activate(release_root, catalogue_path):
    root, path = Path(release_root).resolve(), Path(catalogue_path).resolve()
    path.relative_to(root)
    catalogue = read(path)
    approved(catalogue["decision"], catalogue["decision"]["processor"])
    if not catalogue.get("entries") or catalogue.get("source_fallback") is not False:
        raise ValueError("Not an operational cleaned catalogue")
    for entry in catalogue["entries"]:
        if sha(entry["output_path"]) != entry["output_sha256"]:
            raise ValueError("Activation product checksum mismatch")
    pointer = root / "selected.json"
    if pointer.exists():
        old = read(pointer)
        atomic(root / "history" / (str(time.time_ns()) + ".json"), old)
    atomic(
        pointer,
        {
            "catalogue_path": str(path),
            "catalogue_sha256": sha(path),
            "release_id": catalogue["release_id"],
        },
    )
