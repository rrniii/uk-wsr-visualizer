"""Operational health from recorded processing evidence, never inferred job success."""

import time
from collections import Counter
from pathlib import Path

from .core import atomic, read, sha


def status(config):
    state = Path(config["state_root"])
    root = Path(config.get("releases_root", str(state / "releases")))
    pointer = root / "selected.json"
    result = {
        "observed_at": time.time(),
        "state": "awaiting_scientific_selection",
        "releases": [],
        "alerts": [],
    }
    for directory in sorted(root.glob("*")):
        if not directory.is_dir() or directory.name == "history":
            continue
        records = [read(p) for p in (directory / "records").glob("*.json")]
        result["releases"].append(
            {
                "release_id": directory.name,
                "counts": dict(Counter(r["status"] for r in records)),
                "runtime_seconds": sum(
                    r.get("completed", r.get("started", 0)) - r.get("started", 0)
                    for r in records
                ),
                "failures": [
                    {"case_id": r["case_id"], "error": r.get("error")}
                    for r in records
                    if r["status"] == "failed"
                ],
            }
        )
    if pointer.exists():
        try:
            selected = read(pointer)
            if sha(selected["catalogue_path"]) != selected["catalogue_sha256"]:
                raise ValueError("Selected catalogue changed")
            catalogue = read(selected["catalogue_path"])
            result.update(
                state="operational",
                selected_release=selected["release_id"],
                requested=catalogue["requested_count"],
                validated=catalogue["validated_count"],
                pending=len(catalogue["pending"]),
            )
            for entry in catalogue["entries"]:
                if not Path(entry["output_path"]).is_file():
                    result["alerts"].append(
                        {"case_id": entry["case_id"], "type": "product_missing"}
                    )
                valid = sum(s.get("valid", 0) for s in entry.get("sweeps", []))
                removed = sum(s.get("removed", 0) for s in entry.get("sweeps", []))
                bounds = config.get("drift_bounds", {}).get(
                    entry["radar"] + "|" + entry["pulse"]
                )
                if (
                    bounds
                    and valid
                    and not bounds["min_removed_fraction"]
                    <= removed / valid
                    <= bounds["max_removed_fraction"]
                ):
                    result["alerts"].append(
                        {
                            "case_id": entry["case_id"],
                            "type": "removal_fraction_outside_reviewed_bounds",
                            "fraction": removed / valid,
                        }
                    )
        except (OSError, ValueError, KeyError) as exc:
            result.update(state="failed")
            result["alerts"].append({"type": "selection_integrity", "error": str(exc)})
    result["drift_bounds_configured"] = bool(config.get("drift_bounds"))
    atomic(state / "operations-status.json", result)
    return result
