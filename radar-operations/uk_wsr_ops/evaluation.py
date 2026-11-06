from itertools import combinations
from pathlib import Path

import h5py
import numpy as np

from .core import PROCESSORS, atomic, digest, fields, physical, read, sweeps
from .policies import POLICIES, coherent_echo, decide


def characterize(config, case, rows):
    result = []
    handles = {}
    try:
        for row in rows:
            if row["status"] == "integrity_verified":
                handles[row["processor"]] = h5py.File(row["output_path"], "r")
        with h5py.File(case["source_path"], "r") as source:
            for sweep in sweeps(source):
                ff = fields(source[sweep])
                if "DBZH" not in ff:
                    continue
                dbzh = physical(ff["DBZH"])
                plausible_echo = coherent_echo(dbzh)
                if "RHOHV" in ff:
                    rho = physical(ff["RHOHV"])
                    if rho.shape == dbzh.shape:
                        plausible_echo |= rho >= 0.95
                decisions, metrics, failures = {}, {}, {}
                for processor, handle in handles.items():
                    try:
                        d = decide(handle[sweep], processor)
                        decisions[processor] = d
                        metrics[processor] = {
                            "valid": int(d["valid"].sum()),
                            "supported": int(d["supported"].sum()),
                            "removed": int(d["remove"].sum()),
                            "uncertain": int(d["uncertain"].sum()),
                            "detectors": {
                                name: {
                                    "supported": int(value["supported"].sum()),
                                    "positive": int(value["positive"].sum()),
                                    "positive_removed": int(
                                        (value["positive"] & d["remove"]).sum()
                                    ),
                                    "positive_retained": int(
                                        (value["positive"] & ~d["remove"]).sum()
                                    ),
                                }
                                for name, value in d.get("detectors", {}).items()
                            },
                            "potential_useful_echo_loss": int(
                                (d["remove"] & plausible_echo).sum()
                            ),
                            "range_quartiles": [
                                {
                                    "valid": int(d["valid"][:, sl].sum()),
                                    "removed": int(d["remove"][:, sl].sum()),
                                }
                                for sl in np.array_split(np.arange(dbzh.shape[1]), 4)
                            ],
                        }
                    except (ValueError, KeyError) as exc:
                        failures[processor] = str(exc)
                pair_scores = []
                for a, b in combinations(decisions, 2):
                    da, db = decisions[a], decisions[b]
                    common = (
                        da["supported"] & db["supported"] & da["valid"] & db["valid"]
                    )
                    if common.any():
                        pair_scores.append(
                            float(
                                ((da["remove"] ^ db["remove"]) & common).sum()
                                / common.sum()
                            )
                        )
                valid_count = int(np.isfinite(dbzh).sum())
                risk = max(
                    (
                        m["potential_useful_echo_loss"] / max(valid_count, 1)
                        for m in metrics.values()
                    ),
                    default=0,
                )
                result.append(
                    {
                        "case_id": case["case_id"],
                        "radar": case["radar"],
                        "pulse": case["pulse"],
                        "season": case.get("season"),
                        "sweep": sweep,
                        "shape": list(dbzh.shape),
                        "elevation": float(source[sweep]["where"].attrs["elangle"]),
                        "candidate_count": len(decisions),
                        "metrics": metrics,
                        "failures": failures,
                        "disagreement": max(pair_scores, default=0),
                        "potential_damage_proxy": risk,
                    }
                )
    finally:
        for handle in handles.values():
            handle.close()
    return {
        "case_id": case["case_id"],
        "policy_hashes": {p: digest(v) for p, v in POLICIES.items()},
        "sweeps": result,
    }


def build_pack(config, doc):
    state = Path(config["state_root"])
    all_rows = []
    expected_hashes = {p: digest(v) for p, v in POLICIES.items()}
    for case in doc["cases"]:
        path = state / "metrics" / (case["case_id"] + ".json")
        if path.exists():
            entry = read(path)
            if entry["policy_hashes"] != expected_hashes:
                raise ValueError("Stale candidate metrics")
            all_rows.extend(entry["sweeps"])
    eligible = [
        r
        for r in all_rows
        if r["candidate_count"] == 4
        and all(r["metrics"].get(p, {}).get("supported", 0) > 0 for p in PROCESSORS)
    ]
    # Representative cards retain SP/high-sweep capability tests; targeted ranking
    # uses only comparisons with nonzero support in all four approaches.
    ordered = sorted(
        (r for r in all_rows if r["candidate_count"] == 4),
        key=lambda r: digest([doc["manifest_sha256"], r["case_id"], r["sweep"]]),
    )
    selected = []
    used = set()
    radars = set()
    strata = [("lp", "winter"), ("sp", "winter"), ("lp", "summer"), ("sp", "summer")]
    for i in range(12):
        pulse, season = strata[i % 4]
        pool = [
            r
            for r in ordered
            if r["case_id"] not in used
            and r["pulse"] == pulse
            and r["season"] == season
        ]
        fresh = [r for r in pool if r["radar"] not in radars]
        if not pool:
            continue
        r = (fresh or pool)[0]
        used.add(r["case_id"])
        radars.add(r["radar"])
        selected.append({**r, "selection": "representative"})
    for kind, key, count in [
        ("disagreement", "disagreement", 8),
        ("potential_damage", "potential_damage_proxy", 4),
    ]:
        pool = sorted(
            (r for r in eligible if r["case_id"] not in used),
            key=lambda r: (-r[key], digest([r["case_id"], r["sweep"]])),
        )
        added = 0
        for r in pool:
            if r["case_id"] in used:
                continue
            used.add(r["case_id"])
            selected.append({**r, "selection": kind})
            added += 1
            if added == count:
                break
    pack = {
        "schema": "uk_wsr_ops_decision_pack",
        "manifest_sha256": doc["manifest_sha256"],
        "policy_hashes": expected_hashes,
        "cards": selected,
        "target_cards": 24,
        "complete": len(selected) == 24,
        "eligible_sweeps": len(eligible),
        "interpretation": "Potential damage is an automated review prompt, not a biological/weather ground-truth label. Representative and targeted cards must be scored separately.",
    }
    atomic(state / "decision-pack.json", pack)
    return pack
