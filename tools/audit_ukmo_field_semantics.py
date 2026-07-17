#!/usr/bin/env python3
"""Build and run a stratified all-radar UKMO WSR field-semantics audit."""

from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.field_audit import (
    DEFAULT_SAMPLE_ANCHORS,
    PUBLIC_BASE,
    SampleAnchor,
    audit_plan,
    build_sample_plan,
    local_path_for_entry,
    write_audit_artifacts,
)

ROOT_CATALOG_URL = f"{PUBLIC_BASE}/ukmo-nimrod/catalog/pvol/catalog.json"


class CatalogCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def fetch(self, url: str) -> dict[str, Any]:
        relative = url.removeprefix(PUBLIC_BASE).lstrip("/")
        path = self.root / relative
        if not path.exists():
            _download(url, path)
        return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-catalog", type=Path, default=Path("/tmp/uk_wsr_pvol_catalog.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/uk_wsr_field_audit"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/ukmo_field_semantics_audit"),
    )
    parser.add_argument(
        "--anchor",
        action="append",
        help="YYYYMMDD:HHMM sample anchor. Repeatable. Defaults to winter night, spring day, summer night.",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, help="Limit planned files for smoke tests.")
    parser.add_argument("--reuse-plan", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = args.output_dir / "sample_plan.json"
    if args.reuse_plan and plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        if not args.root_catalog.exists():
            _download(ROOT_CATALOG_URL, args.root_catalog)
        root = json.loads(args.root_catalog.read_text(encoding="utf-8"))
        anchors = tuple(_parse_anchor(value) for value in (args.anchor or []))
        if not anchors:
            anchors = tuple(SampleAnchor(*value) for value in DEFAULT_SAMPLE_ANCHORS)
        cache = CatalogCache(args.cache_dir / "catalogs")
        plan = build_sample_plan(root, cache.fetch, anchors=anchors)
        if args.limit is not None:
            plan["files"] = plan["files"][: max(0, args.limit)]
            plan["file_count"] = len(plan["files"])
            plan["radar_count"] = len({entry["radar"] for entry in plan["files"]})
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "radar_count": plan.get("radar_count"),
                "file_count": len(plan.get("files", [])),
                "plan_errors": len(plan.get("errors", [])),
                "plan": str(plan_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if args.plan_only:
        return 1 if plan.get("errors") else 0

    failures = _download_plan(plan, args.cache_dir / "pvol", workers=max(1, args.workers))
    if failures:
        (args.output_dir / "download_errors.json").write_text(
            json.dumps(failures, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.download_only:
        return 1 if failures else 0

    summary = audit_plan(plan, cache_dir=args.cache_dir / "pvol")
    summary["download_errors"] = failures
    write_audit_artifacts(summary, args.output_dir)
    print(
        json.dumps(
            {
                "audited_file_count": summary["audited_file_count"],
                "audited_sweep_count": summary["audited_sweep_count"],
                "radar_count": summary["radar_count"],
                "audit_errors": len(summary["errors"]),
                "report": str(args.output_dir / "README.md"),
            },
            sort_keys=True,
        )
    )
    return 1 if failures or summary["errors"] else 0


def _parse_anchor(value: str) -> SampleAnchor:
    date, separator, time = value.partition(":")
    if not separator or len(date) != 8 or len(time) != 4 or not (date + time).isdigit():
        raise argparse.ArgumentTypeError(f"invalid anchor {value!r}; expected YYYYMMDD:HHMM")
    return SampleAnchor(date=date, time=time)


def _download_plan(plan: dict[str, Any], cache_dir: Path, *, workers: int) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    files = list(plan.get("files", []))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _download,
                str(entry["object_url"]),
                local_path_for_entry(cache_dir, entry),
                expected_size=int(entry.get("size_bytes") or 0),
            ): entry
            for entry in files
        }
        completed = 0
        for future in as_completed(futures):
            entry = futures[future]
            completed += 1
            try:
                future.result()
                print(
                    json.dumps(
                        {
                            "download_progress": f"{completed}/{len(files)}",
                            "radar": entry["radar"],
                            "date": entry["date"],
                            "pulse": entry["pulse"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - batch report records and continues.
                failures.append(
                    {
                        "radar": entry.get("radar"),
                        "date": entry.get("date"),
                        "pulse": entry.get("pulse"),
                        "url": entry.get("object_url"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return failures


def _download(url: str, path: Path, *, expected_size: int = 0) -> None:
    if path.exists() and (expected_size <= 0 or path.stat().st_size == expected_size):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "uk-wsr-field-audit/1"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    if expected_size > 0 and temporary.stat().st_size != expected_size:
        raise OSError(
            f"download size mismatch for {url}: got {temporary.stat().st_size}, expected {expected_size}"
        )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
