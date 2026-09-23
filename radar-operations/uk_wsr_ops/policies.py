"""Explicit evaluation policies. Thresholds are hypotheses, not calibrated probabilities."""

import numpy as np
from .core import fields, physical, text, digest

POLICIES = {
    "pyrad": {"version": "echo-clean-v3-existing", "decision": "QC_DECISION_PYRAD_V3"},
    "baltrad": {
        "version": "ppc-fuzzy-protected-eval-v2",
        "quality_min": 0.75,
        "preprocess_z_min": -20.0,
        "threshold_source": "frozen ppc-qc-v1.xml",
        "residual_action": "uncertain_retained_not_independent_clutter_vote",
    },
    "lrose": {"version": "lrose-compound-eval-v2", "flag_min": 0.5},
    "rack": {
        "version": "rack-compound-eval-v2",
        "response_min": 0.95,
        "max_elevation": 2.0,
        "composition": "intersections_unchanged_pending_detector_review",
    },
}
for _processor, _policy in POLICIES.items():
    _policy["decoding"] = "field-specific-diagnostics-v2"
    if _processor != "pyrad":
        _policy["protection"] = {"dbzh_3x3_spread_max": 3.0, "rhohv_min": 0.95}

LROSE_BINARY_FLAGS = {
    "PERSISTENT_CLUTTER_FLAG_LROSE_V2",
    "GROUND_CLUTTER_PID_FLAG_LROSE_V2",
    "SEA_CLUTTER_FLAG_LROSE_V2",
    "RLAN_FLAG_LROSE_V2",
}
RACK_TASKS = {
    "fi.fmi.Rack.AnDRe." + name + "Op"
    for name in ("Emitter", "Jamming", "Ship", "Speckle")
}


def diagnostic(group):
    """Decode only the reserved values whose meanings are established here."""
    name = text(group["what"].attrs.get("quantity", ""))
    task = text(group["how"].attrs.get("task", "")) if "how" in group else ""
    if name in LROSE_BINARY_FLAGS:
        data = physical(group, undetect_value=0.0)
    elif name == "RESIDUAL_CLUTTER_MASK_BALTRAD_V1":
        # PPC mask-nodata is -1, distinct from the wrapper's ODIM nodata -999.
        data = physical(group, missing_codes=(-1,))
    elif task in RACK_TASKS:
        # Emitter's encoded zero would otherwise decode to -0.004. The reserved
        # no-detection code denotes a physical response of zero, not that offset.
        return physical(group, undetect_value=0.0)
    else:
        return physical(group)
    if np.any(np.isfinite(data) & ~np.isin(data, [0, 1])):
        raise ValueError(f"Invalid binary diagnostic: {name}")
    return data


def quality(sweep):
    result = {}

    def visit(name, obj):
        if hasattr(obj, "keys") and "data" in obj and "what" in obj and "how" in obj:
            task = text(obj["how"].attrs.get("task", ""))
            if task:
                # Multiple instances are retained: ambiguous detector identities must fail.
                result.setdefault(task, []).append(diagnostic(obj))

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
    detectors = {}
    policy = POLICIES[processor]

    def observe(name, data, positive):
        if data is None:
            return
        if data.shape != shape:
            raise ValueError("Detector geometry mismatch")
        coverage = valid & np.isfinite(data)
        detectors[name] = {"supported": coverage, "positive": coverage & positive}

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
            if "QC_BITMASK_PYRAD_V3" in ff:
                values = physical(ff["QC_BITMASK_PYRAD_V3"])
                if values.shape != shape or np.any(
                    np.isfinite(values)
                    & ((values < 0) | (values > 63) | (values != np.floor(values)))
                ):
                    raise ValueError("Invalid PyRAD detector bitmask")
                bits = np.where(np.isfinite(values), values, 0).astype(np.uint16)
                for bit, name in [
                    (1, "receiver"),
                    (2, "static"),
                    (4, "radial"),
                    (8, "speckle"),
                    (16, "protected"),
                ]:
                    observe(name, values, (bits & bit) != 0)
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
            return diagnostic(ff[name]) if name in ff else None

        if processor == "baltrad":
            clutter = quantity("CLUTTER_PROB_BALTRAD_V1")
            qind = quantity("QIND_BALTRAD_V1")
            residual = quantity("RESIDUAL_CLUTTER_MASK_BALTRAD_V1")
            if residual is not None:
                observe("residual_nonretained", residual, residual == 0)
            if clutter is not None and qind is not None:
                if clutter.shape != shape or qind.shape != shape:
                    raise ValueError("Detector geometry mismatch")
                finite = np.isfinite(clutter) & np.isfinite(qind)
                if np.any(
                    finite & ((clutter < 0) | (clutter > 1) | (qind < 0) | (qind > 1))
                ) or not np.allclose(
                    qind[finite], 1 - clutter[finite], atol=1e-6, rtol=0
                ):
                    raise ValueError("BALTRAD quality/clutter complement mismatch")
                th = quantity("TH") if "TH" in ff else dbzh
                if th.shape != shape:
                    raise ValueError("BALTRAD input reflectivity geometry mismatch")
                # PPC blanked these inputs before fuzzy classification. A finite
                # output below that cutoff is not usable evidence about the echo.
                coverage = (
                    valid
                    & finite
                    & np.isfinite(th)
                    & (th >= policy["preprocess_z_min"])
                )
                fuzzy_reject = coverage & (qind < policy["quality_min"])
                observe("fuzzy_reject", np.where(coverage, qind, np.nan), fuzzy_reject)
                suspicion = fuzzy_reject.copy()
                if residual is not None:
                    suspicion |= coverage & np.isfinite(residual) & (residual == 0)
                hypotheses.append((coverage, fuzzy_reject, suspicion, 2))
        elif processor == "lrose":
            for name in sorted(LROSE_BINARY_FLAGS):
                data = quantity(name)
                if data is not None:
                    observe(name, data, data >= policy["flag_min"])
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
                    if task in RACK_TASKS and task.endswith(suffix)
                    for array in arrays
                ]
                if len(candidates) > 1:
                    raise ValueError("Ambiguous RACK detector identity")
                data = candidates[0] if candidates else None
                if data is not None:
                    observe(suffix, data, data >= policy["response_min"])
                return data

            pair(
                detector("EmitterOp"),
                detector("JammingOp"),
                policy["response_min"],
                policy["response_min"],
                16,
            )
            pair(
                detector("ShipOp"),
                detector("SpeckleOp"),
                policy["response_min"],
                policy["response_min"],
                32,
            )
        protected = coherent_echo(dbzh)
        if "RHOHV" in ff:
            rho = physical(ff["RHOHV"])
            if rho.shape == shape:
                protected |= rho >= policy["protection"]["rhohv_min"]
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
        "detectors": detectors,
    }
