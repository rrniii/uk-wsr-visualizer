#!/usr/bin/env python3
"""Materialise a compact temporal QC review set from public PVOL sources."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.qc_benchmark import canonical_json_sha256
from subset_temporal_review_targets import build_subset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--size", type=int, default=24)
    args = parser.parse_args()

    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    temporal = [
        item
        for item in source["targets"]
        if _primary_source(item).get("source_kind") == "temporal"
    ]
    compact = build_subset({**source, "targets": temporal}, size=args.size)
    compact["targets"] = [_current_views_only(item) for item in compact["targets"]]

    data_root = args.output_root / "pvol"
    ledger_files: dict[str, dict[str, Any]] = {}
    for target in compact["targets"]:
        source_ref = _primary_source(target)
        source_id = str(source_ref["source_id"])
        destination = data_root / source_id / str(source_ref["filename"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.stat().st_size != int(source_ref["size_bytes"]):
            temporary = destination.with_suffix(destination.suffix + ".part")
            with urllib.request.urlopen(str(source_ref["url"]), timeout=120) as response:
                with temporary.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            temporary.replace(destination)
        if destination.stat().st_size != int(source_ref["size_bytes"]):
            raise ValueError(f"download size mismatch: {destination}")
        ledger_files[source_id] = {
            "source_id": source_id,
            "sha256": str(source_ref["sha256"]),
            "local_path": str(destination),
            "size_bytes": int(source_ref["size_bytes"]),
            "url": str(source_ref["url"]),
        }

    ledger = {"schema": "uk_wsr_temporal_download_ledger", "files": ledger_files}
    compact["download_ledger_sha256"] = canonical_json_sha256(ledger)
    compact["selection"]["compact_subset"]["source_views"] = "current_only"
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "download_ledger.json").write_text(
        json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_root / "review_targets.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"target_count": compact["target_count"], "source_count": len(ledger_files)}))
    return 0


def _primary_source(target: dict[str, Any]) -> dict[str, Any]:
    return next(view["source"] for view in target["review_views"] if view.get("annotation_primary"))


def _current_views_only(target: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(target)
    result["review_views"] = [view for view in result["review_views"] if view.get("role") == "current"]
    return result


if __name__ == "__main__":
    raise SystemExit(main())
