#!/usr/bin/env python3
"""Create a compact, stratified subset of blinded temporal review targets."""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.qc_temporal_review import temporal_review_counts


ELEVATION_SEQUENCE = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 9.0, 89.9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, default=24)
    args = parser.parse_args()

    review = json.loads(args.input.read_text(encoding="utf-8"))
    subset = build_subset(review, size=args.size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(subset, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"target_count": subset["target_count"], "output": str(args.output)}))
    return 0


def build_subset(review: dict[str, Any], *, size: int) -> dict[str, Any]:
    """Select a small review set with radar, pulse, elevation and date diversity."""

    targets = list(review.get("targets", ()))
    if size < 4:
        raise ValueError("size must be at least four")
    if size > len(targets):
        raise ValueError("size exceeds available targets")

    by_radar: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        by_radar[str(target["radar"])].append(target)
    radar_names = sorted(by_radar)
    if size < len(radar_names):
        raise ValueError("size must cover every radar at least once")

    chosen: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    # Preserve the exceptional regression cases before filling the routine
    # archive strata. They are the only currently available second-date scans.
    for target in sorted(
        (item for item in targets if str(item["date"]) != "20250101"),
        key=lambda item: (str(item["date"]), str(item["target_id"])),
    ):
        if len(chosen) == size:
            break
        chosen.append(target)
        used_ids.add(str(target["target_id"]))
    for index, radar in enumerate(radar_names):
        if any(str(item["radar"]) == radar for item in chosen):
            continue
        chosen.append(
            _best_candidate(
                by_radar[radar],
                used_ids,
                pulse=("lp", "sp")[index % 2],
                elevation=ELEVATION_SEQUENCE[index % len(ELEVATION_SEQUENCE)],
                prefer_distinct_date=True,
            )
        )
        used_ids.add(str(chosen[-1]["target_id"]))

    extra_index = 0
    while len(chosen) < size:
        index = extra_index
        radar = radar_names[index % len(radar_names)]
        preferred_pulse = ("lp", "sp")[extra_index % 2]
        selected = _best_candidate(
            by_radar[radar],
            used_ids,
            pulse=preferred_pulse,
            elevation=ELEVATION_SEQUENCE[(index + 3) % len(ELEVATION_SEQUENCE)],
            prefer_distinct_date=True,
        )
        chosen.append(selected)
        used_ids.add(str(selected["target_id"]))
        extra_index += 1

    # Keep the review order deterministic while avoiding radar-by-radar blocks.
    chosen.sort(key=lambda item: (str(item["pulse"]), float(item["elevation_deg"]), str(item["radar"])))
    result = copy.deepcopy(review)
    result["targets"] = chosen
    result["target_count"] = len(chosen)
    result["geometry_count"] = len({str(item["geometry_id"]) for item in chosen})
    result["expected_geometry_count"] = result["geometry_count"]
    result["counts"] = temporal_review_counts(chosen)
    result["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result.setdefault("selection", {})["compact_subset"] = {
        "method": "radar_pulse_elevation_stratified",
        "target_count": len(chosen),
        "radar_count": len(radar_names),
    }
    return result


def _best_candidate(
    candidates: list[dict[str, Any]],
    used_ids: set[str],
    *,
    pulse: str,
    elevation: float,
    prefer_distinct_date: bool,
) -> dict[str, Any]:
    available = [item for item in candidates if str(item["target_id"]) not in used_ids]
    if not available:
        raise ValueError("insufficient unique targets for compact subset")

    def score(item: dict[str, Any]) -> tuple[float, ...]:
        item_elevation = float(item["elevation_deg"])
        return (
            0.0 if str(item["pulse"]) == pulse else 1.0,
            abs(item_elevation - elevation),
            0.0 if prefer_distinct_date and str(item["date"]) != "20250101" else 1.0,
            float(item_elevation),
            float(item["time"]),
            str(item["target_id"]),
        )

    return min(available, key=score)


if __name__ == "__main__":
    raise SystemExit(main())
