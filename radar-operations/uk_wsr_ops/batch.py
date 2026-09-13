"""Manifest freezing, bounded LOTUS submission and selected-product resolution."""

import shlex
import subprocess
from pathlib import Path

from .core import atomic, digest, read, safe_id, sha


def freeze_archive(case_list, destination):
    rows = read(case_list)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected a nonempty list of explicit archive cases")
    seen = set()
    cases = []
    for row in rows:
        cid = safe_id(row["case_id"])
        if cid in seen:
            raise ValueError("Duplicate archive case ID")
        seen.add(cid)
        safe_id(row["radar"])
        if row["pulse"] not in ("lp", "sp"):
            raise ValueError("Unknown pulse")
        source = Path(row["source_path"]).resolve(strict=True)
        cases.append({**row, "source_path": str(source), "source_sha256": sha(source)})
    doc = {"schema": "uk_wsr_ops_archive_manifest", "schema_version": 1, "cases": cases}
    doc["manifest_sha256"] = digest(doc)
    atomic(destination, doc)
    return doc


def submit(
    config_path, doc, decision_path, releases, interpreter, script_path, execute=False
):
    from .operations import approved

    decision = read(decision_path)
    approved(decision, decision["processor"])
    path = Path(script_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(Path(interpreter).resolve()),
        "-m",
        "uk_wsr_ops.cli",
        "--config",
        str(Path(config_path).resolve()),
        "run-one",
        "--decision",
        str(Path(decision_path).resolve()),
        "--releases",
        str(Path(releases).resolve()),
        "--index",
    ]
    # One case per array task; no interpolation of user strings into shell syntax.
    body = (
        "#!/bin/bash\nset -euo pipefail\n"
        + shlex.join(command)
        + ' "${SLURM_ARRAY_TASK_ID:?}"\n'
    )
    path.write_text(body)
    path.chmod(0o700)
    argv = [
        "sbatch",
        "--parsable",
        "--account=ncas_radar",
        "--partition=standard",
        "--qos=short",
        "--time=03:00:00",
        "--mem=12G",
        "--cpus-per-task=1",
        f"--array=0-{len(doc['cases']) - 1}%4",
        f"--output={path.parent}/archive-%A_%a.log",
        str(path),
    ]
    if not execute:
        return {"command": argv, "submitted": False}
    job_id = subprocess.check_output(argv, text=True).strip()
    result = {
        "job_id": job_id,
        "manifest_sha256": doc["manifest_sha256"],
        "decision_sha256": digest(decision),
        "submitted": True,
    }
    atomic(path.with_suffix(".submission.json"), result)
    return result


def selected_product(releases, case_id):
    safe_id(case_id)
    pointer = read(Path(releases) / "selected.json")
    if sha(pointer["catalogue_path"]) != pointer["catalogue_sha256"]:
        raise ValueError(
            "Selected catalogue changed; activate the newly validated version explicitly"
        )
    catalogue = read(pointer["catalogue_path"])
    for entry in catalogue["entries"]:
        if entry["case_id"] == case_id:
            if sha(entry["output_path"]) != entry["output_sha256"]:
                raise ValueError("Selected cleaned product changed")
            return {
                "path": entry["output_path"],
                "quantity": catalogue["default_quantity"],
                "release_id": catalogue["release_id"],
                "source_sha256": entry["source_sha256"],
            }
    raise FileNotFoundError(
        "Cleaned product unavailable; original data will not be substituted"
    )
