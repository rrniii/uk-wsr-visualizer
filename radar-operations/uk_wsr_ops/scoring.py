"""Gate-level scores with explicit labelled, uncertain and unsupported coverage."""

import numpy as np


def polygon_mask(shape, vertices):
    v = np.asarray(vertices, dtype=float)
    if v.ndim != 2 or v.shape[1] != 2 or len(v) < 3 or not np.isfinite(v).all():
        raise ValueError("Polygon requires at least three finite [ray, gate] vertices")
    if np.any(v < 0) or np.any(v[:, 0] > shape[0]) or np.any(v[:, 1] > shape[1]):
        raise ValueError("Polygon outside gate geometry")
    y, x = np.indices(shape, dtype=float)
    y += 0.5
    x += 0.5
    inside = np.zeros(shape, bool)
    previous = v[-1]
    for point in v:
        ya, xa = previous
        yb, xb = point
        if ya != yb:
            inside ^= ((ya > y) != (yb > y)) & (
                x < (xb - xa) * (y - ya) / (yb - ya) + xa
            )
        previous = point
    return inside


def score(decision, regions):
    shape = decision["remove"].shape
    retain, artefact, ignored = [np.zeros(shape, bool) for _ in range(3)]
    classes = {}
    for region in regions:
        mask = polygon_mask(shape, region["vertices"])
        action = region["action"]
        if action not in ("retain", "remove", "ignore"):
            raise ValueError("Unknown annotation action")
        if action == "ignore":
            ignored |= mask
        elif action == "retain":
            retain |= mask
        else:
            artefact |= mask
        classes.setdefault(region["label"], np.zeros(shape, bool))
        classes[region["label"]] |= mask
    ignored |= retain & artefact
    eligible = decision["valid"] & decision["supported"] & ~ignored
    retain &= eligible
    artefact &= eligible
    removed = decision["remove"]

    def ratio(n, d):
        return float(n / d) if d else None

    def summarize(mask):
        r, a = retain & mask, artefact & mask
        tp, fp = int((removed & a).sum()), int((removed & r).sum())
        return {
            "retain_gates": int(r.sum()),
            "artefact_gates": int(a.sum()),
            "true_removals": tp,
            "false_removals": fp,
            "useful_echo_loss": ratio(fp, int(r.sum())),
            "artefact_removal": ratio(tp, int(a.sum())),
            "removal_precision": ratio(tp, tp + fp),
        }

    return {
        **summarize(np.ones(shape, bool)),
        "by_label": {k: summarize(v) for k, v in classes.items()},
        "valid_gates": int(decision["valid"].sum()),
        "supported_gates": int((decision["supported"] & decision["valid"]).sum()),
        "labelled_gates": int((retain | artefact).sum()),
        "ignored_gates": int(ignored.sum()),
        "uncertain_decision_gates": int(decision["uncertain"].sum()),
    }
