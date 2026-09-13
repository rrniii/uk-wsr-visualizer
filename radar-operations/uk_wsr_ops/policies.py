"""Explicit evaluation policies. Thresholds are hypotheses, not calibrated probabilities."""

import numpy as np
from .core import fields, physical, text, digest

POLICIES = {
    "pyrad": {"version": "echo-clean-v3-existing", "decision": "QC_DECISION_PYRAD_V3"},
    "baltrad": {
        "version": "ppc-compound-eval-v1",
        "clutter_min": 0.99,
        "residual_min": 0.5,
    },
    "lrose": {"version": "lrose-compound-eval-v1", "flag_min": 0.5},
    "rack": {
        "version": "rack-compound-eval-v1",
        "response_min": 0.95,
        "max_elevation": 2.0,
    },
}


def quality(sweep):
    result = {}

    def visit(name, obj):
        if hasattr(obj, "keys") and "data" in obj and "what" in obj and "how" in obj:
            task = text(obj["how"].attrs.get("task", ""))
            if task:
                # Multiple instances are retained: ambiguous detector identities must fail.
                result.setdefault(task, []).append(physical(obj))

    sweep.visititems(visit)
    return result


def coherent_echo(dbzh):
    """Conservative protection hypothesis: complete, smooth 3x3 echo neighbourhood.

    Azimuth wraps; range never wraps. This protects some clutter too, intentionally.
    It is not a biological classifier and cannot establish scientific acceptance.
    """
    count = np.zeros(dbzh.shape, dtype=int)
    minimum = np.full(dbzh.shape, np.inf)
    maximum = np.full(dbzh.shape, -np.inf)
    for ray in (-1, 0, 1):
        for gate in (-1, 0, 1):
            shifted = np.roll(np.roll(dbzh, ray, axis=0), gate, axis=1).copy()
            if gate == -1:
                shifted[:, -1] = np.nan
            elif gate == 1:
                shifted[:, 0] = np.nan
            valid = np.isfinite(shifted)
            count += valid
            minimum = np.minimum(minimum, np.where(valid, shifted, np.inf))
            maximum = np.maximum(maximum, np.where(valid, shifted, -np.inf))
    return (count == 9) & ((maximum - minimum) <= 3)


def decide(sweep, processor):
    ff = fields(sweep)
    if "DBZH" not in ff:
        raise ValueError("DBZH unavailable")
    dbzh = physical(ff["DBZH"])
    shape = dbzh.shape
    valid = np.isfinite(dbzh)
    supported = np.zeros(shape, bool)
    remove = np.zeros(shape, bool)
    uncertain = np.zeros(shape, bool)
    reasons = np.zeros(shape, np.uint16)
    policy = POLICIES[processor]
    if processor == "pyrad":
        if policy["decision"] in ff:
            decision = physical(ff[policy["decision"]])
            if decision.shape != shape or np.any(
                np.isfinite(decision) & ~np.isin(decision, [0, 1, 2])
            ):
                raise ValueError("Invalid PyRAD decision geometry or values")
            supported = valid & np.isfinite(decision)
            remove = supported & (decision == 1)
            uncertain = supported & (decision == 2)
            reasons[remove] = 1
    else:
        hypotheses = []

        def pair(a, b, threshold_a, threshold_b, bit):
            if a is None or b is None:
                return
            if a.shape != shape or b.shape != shape:
                raise ValueError("Detector geometry mismatch")
            coverage = valid & np.isfinite(a) & np.isfinite(b)
            both = coverage & (a >= threshold_a) & (b >= threshold_b)
            suspicion = coverage & ((a >= threshold_a) | (b >= threshold_b))
            hypotheses.append((coverage, both, suspicion, bit))

        def quantity(name):
            return physical(ff[name]) if name in ff else None

        if processor == "baltrad":
            pair(
                quantity("CLUTTER_PROB_BALTRAD_V1"),
                quantity("RESIDUAL_CLUTTER_MASK_BALTRAD_V1"),
                policy["clutter_min"],
                policy["residual_min"],
                2,
            )
        elif processor == "lrose":
            pair(
                quantity("PERSISTENT_CLUTTER_FLAG_LROSE_V2"),
                quantity("GROUND_CLUTTER_PID_FLAG_LROSE_V2"),
                0.5,
                0.5,
                4,
            )
            pair(
                quantity("SEA_CLUTTER_FLAG_LROSE_V2"),
                quantity("GROUND_CLUTTER_PID_FLAG_LROSE_V2"),
                0.5,
                0.5,
                8,
            )
        elif (
            processor == "rack"
            and float(sweep["where"].attrs["elangle"]) <= policy["max_elevation"]
            and int(sweep.name.rsplit("dataset", 1)[-1]) <= 3
        ):
            qq = quality(sweep)

            def detector(suffix):
                candidates = [
                    array
                    for task, arrays in qq.items()
                    if task.endswith(suffix)
                    for array in arrays
                ]
                if len(candidates) > 1:
                    raise ValueError("Ambiguous RACK detector identity")
                return candidates[0] if candidates else None

            pair(detector("EmitterOp"), detector("JammingOp"), 0.95, 0.95, 16)
            pair(detector("ShipOp"), detector("SpeckleOp"), 0.95, 0.95, 32)
        protected = coherent_echo(dbzh)
        if "RHOHV" in ff:
            rho = physical(ff["RHOHV"])
            if rho.shape == shape:
                protected |= rho >= 0.95
        for coverage, both, suspicion, bit in hypotheses:
            supported |= coverage
            accepted = both & ~protected
            remove |= accepted
            uncertain |= suspicion & ~accepted
            reasons[accepted] |= bit
        uncertain &= ~remove
    return {
        "remove": remove,
        "uncertain": uncertain,
        "supported": supported,
        "valid": valid,
        "reasons": reasons,
        "policy_sha256": digest(policy),
    }
