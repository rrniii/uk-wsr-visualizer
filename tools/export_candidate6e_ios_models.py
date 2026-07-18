#!/usr/bin/env python3
"""Package date-balanced Candidate 6E models for the native iOS runtime.

Research artifacts store arrays in NPZ files. The native app intentionally
accepts self-contained JSON only, so this bridge copies every model array into
the portable inline representation and writes a quarantined registry. A
separate release review must change eligibility after real-data gates pass.
"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_model_v3 import (
    BACKGROUND_MODEL_V3_STATISTICS_VERSION,
)


REQUIRED_ARRAYS = {
    "low_ci_static_echo_date_sample_count",
    "low_ci_static_echo_date_frequency",
    "low_ci_static_echo_season_count",
    "low_ci_static_echo_time_bucket_count",
    "low_ci_static_dbzh_p10",
    "low_ci_static_dbzh_median",
    "low_ci_static_dbzh_p90",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, help="Maximum number of models to package.")
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for source in sorted(args.model_dir.glob("*.json")):
        if args.limit is not None and len(entries) >= args.limit:
            break
        model = load_background_model(source)
        if model.metadata.get("statistics_version") != BACKGROUND_MODEL_V3_STATISTICS_VERSION:
            continue
        if not REQUIRED_ARRAYS.issubset(model.arrays):
            continue
        payload = model.to_manifest()
        destination = output_dir / source.name
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        destination.write_text(encoded + "\n", encoding="utf-8")
        entries.append(
            {
                "filename": destination.name,
                "status": "quarantined",
                "qc_version": "qc-v3-candidate-6",
                "eligible_for_default": False,
                "qualification_reasons": ["awaiting_native_real_data_release_gate"],
                "array_hash": payload["array_hash"],
                "json_sha256": sha256(destination.read_bytes()).hexdigest(),
            }
        )

    registry = {
        "schema": "uk_wsr_background_model_manifest",
        "schema_version": 2,
        "model_count": len(entries),
        "eligible_model_count": 0,
        "models": entries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"model_count": len(entries), "output_dir": str(output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
