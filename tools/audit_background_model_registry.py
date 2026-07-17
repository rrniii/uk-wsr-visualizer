#!/usr/bin/env python3
"""Audit packaged learned background models and write the qc-v2 registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from uk_wsr_visualizer.background_registry import (
    audit_background_model_registry,
    registry_audit_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("src/uk_wsr_visualizer/models/background"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Existing manifest to audit. Defaults to MODEL_DIR/manifest.json.",
    )
    parser.add_argument(
        "--ios-registry",
        type=Path,
        default=Path("ios/UKWSRVisualizer/QualifiedBackgroundModels/manifest.json"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/background_model_registry_qc_v2"),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; fail if the existing manifest differs from the audit.",
    )
    args = parser.parse_args()

    manifest_path = args.manifest or args.model_dir / "manifest.json"
    payload = audit_background_model_registry(
        args.model_dir,
        manifest_path=manifest_path,
    )
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if args.check:
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 1
        comparable = dict(payload)
        comparable["generated_at"] = current.get("generated_at")
        return 0 if current == comparable else 1

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(encoded, encoding="utf-8")
    args.ios_registry.parent.mkdir(parents=True, exist_ok=True)
    args.ios_registry.write_text(encoded, encoding="utf-8")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "summary.json").write_text(encoded, encoding="utf-8")
    (args.report_dir / "README.md").write_text(registry_audit_markdown(payload), encoding="utf-8")

    print(
        json.dumps(
            {
                "model_count": payload["model_count"],
                "eligible_model_count": payload["eligible_model_count"],
                "quarantined_model_count": payload["quarantined_model_count"],
                "manifest": str(manifest_path),
                "report": str(args.report_dir / "README.md"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
