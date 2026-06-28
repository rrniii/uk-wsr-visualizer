#!/usr/bin/env python3
"""Build the public pvol catalog mirror for the UKMO NIMROD object-store layout."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.object_store import join_object_url, raw_volume_object_key
from uk_wsr_visualizer.object_store_config import load_object_store_config
from uk_wsr_visualizer.object_store_manifest import sha256_file
from uk_wsr_visualizer.object_store_sync import create_s3_client
from uk_wsr_visualizer.radars import RADAR_BY_SLUG, RADAR_NUM_BY_SLUG

PVOL_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate_(?P<pulse>[^_]+)_(?P<time>[0-9]{4})\.h5$")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def pvol_record(path: Path, base: Path, object_prefix: str, public_base_url: str) -> tuple[str, str, str, dict[str, Any]] | None:
    rel = path.relative_to(base)
    if len(rel.parts) != 5:
        return None
    radar, year, date, pulse, filename = rel.parts
    if radar not in RADAR_BY_SLUG or year != date[:4]:
        return None
    match = PVOL_RE.match(filename)
    if not match:
        return None
    if match.group("date") != date or match.group("pulse") != pulse:
        return None
    if match.group("num") != RADAR_NUM_BY_SLUG.get(radar):
        return None
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    key = raw_volume_object_key(radar, date, pulse, filename, object_prefix)
    return radar, date, pulse, {
        "pulse": pulse,
        "time": match.group("time"),
        "filename": filename,
        "size_bytes": stat.st_size,
        "modified_time": stat.st_mtime,
        "object_key": key,
        "object_url": join_object_url(public_base_url, key),
    }


def iter_date_dirs(base: Path, radar_filter: str | None, year_filter: str | None, date_filter: str | None):
    radar_dirs = [base / radar_filter] if radar_filter else sorted(path for path in base.iterdir() if path.is_dir())
    for radar_dir in radar_dirs:
        radar = radar_dir.name
        if radar not in RADAR_BY_SLUG or not radar_dir.exists():
            continue
        year_dirs = [radar_dir / year_filter] if year_filter else sorted(path for path in radar_dir.iterdir() if path.is_dir())
        for year_dir in year_dirs:
            if not year_dir.exists() or not year_dir.name.isdigit():
                continue
            date_dirs = [year_dir / date_filter] if date_filter else sorted(path for path in year_dir.iterdir() if path.is_dir())
            for date_dir in date_dirs:
                if not date_dir.exists() or not date_dir.name.isdigit() or len(date_dir.name) != 8:
                    continue
                yield radar, year_dir.name, date_dir.name, date_dir


def scan_day(date_dir: Path, base: Path, object_prefix: str, public_base_url: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    pulse_counts: dict[str, int] = defaultdict(int)
    for pulse_dir in sorted(path for path in date_dir.iterdir() if path.is_dir()):
        for path in sorted(pulse_dir.glob("*.h5")):
            parsed = pvol_record(path, base, object_prefix, public_base_url)
            if parsed is None:
                continue
            _radar, _date, pulse, record = parsed
            records.append(record)
            pulse_counts[pulse] += 1
    records.sort(key=lambda item: (item["pulse"], item["time"], item["filename"]))
    return records, dict(sorted(pulse_counts.items()))


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    base = args.pvol_base
    stage_root = args.stage_root
    catalog_root = stage_root / args.object_prefix / "catalog" / "pvol"
    public_base_url = args.public_base_url.rstrip("/")
    generated_at = utc_now()
    log(f"building pvol catalog base={base} stage_root={stage_root}")

    radar_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"file_count": 0, "size_bytes": 0, "dates": [], "years": set()})
    year_days: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    coverage_rows: list[dict[str, Any]] = []
    file_count = 0
    byte_count = 0
    day_count = 0
    started = time.time()

    for radar, year, date, date_dir in iter_date_dirs(base, args.radar, args.year, args.date):
        if args.max_days is not None and day_count >= args.max_days:
            break
        records, pulse_counts = scan_day(date_dir, base, args.object_prefix, public_base_url)
        if not records:
            continue
        day_count += 1
        day_files = len(records)
        day_bytes = sum(int(record["size_bytes"]) for record in records)
        mm = date[4:6]
        dd = date[6:8]
        pvol_prefix = f"{args.object_prefix}/pvol/{radar}/{year}/{mm}/{dd}"
        catalog_key = f"{args.object_prefix}/catalog/pvol/{radar}/{year}/{mm}/{dd}/catalog.json"
        day_payload = {
            "schema_version": 1,
            "kind": "pvol_day_catalog",
            "generated_at": generated_at,
            "radar": radar,
            "radar_num": RADAR_NUM_BY_SLUG.get(radar, ""),
            "date": date,
            "pvol_prefix": pvol_prefix,
            "catalog_key": catalog_key,
            "file_count": day_files,
            "size_bytes": day_bytes,
            "pulses": sorted(pulse_counts),
            "pulse_counts": pulse_counts,
            "times_by_pulse": {
                pulse: sorted(record["time"] for record in records if record["pulse"] == pulse)
                for pulse in sorted(pulse_counts)
            },
            "files": records,
        }
        write_json(catalog_root / radar / year / mm / dd / "catalog.json", day_payload)
        year_days[(radar, year)].append({
            "date": date,
            "catalog_key": catalog_key,
            "pvol_prefix": pvol_prefix,
            "file_count": day_files,
            "size_bytes": day_bytes,
            "pulse_counts": pulse_counts,
        })
        rt = radar_totals[radar]
        rt["file_count"] += day_files
        rt["size_bytes"] += day_bytes
        rt["dates"].append(date)
        rt["years"].add(year)
        coverage_rows.append({"directory": pvol_prefix, "file_count": day_files, "total_bytes": day_bytes})
        file_count += day_files
        byte_count += day_bytes
        if day_count % args.progress_days == 0 or file_count % args.progress_every < day_files:
            log(f"scan_progress days={day_count} files={file_count} TB={byte_count/1e12:.3f} last={radar}/{date}")

    log(f"writing coverage summaries days={day_count} files={file_count} TB={byte_count/1e12:.3f}")
    coverage_csv = catalog_root / "coverage.csv"
    coverage_csv.parent.mkdir(parents=True, exist_ok=True)
    with coverage_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["directory", "file_count", "total_bytes"])
        for row in sorted(coverage_rows, key=lambda item: item["directory"]):
            writer.writerow([row["directory"], row["file_count"], row["total_bytes"]])

    for (radar, year), days in sorted(year_days.items()):
        days_sorted = sorted(days, key=lambda item: item["date"])
        payload = {
            "schema_version": 1,
            "kind": "pvol_year_coverage",
            "generated_at": generated_at,
            "radar": radar,
            "year": year,
            "date_count": len(days_sorted),
            "file_count": sum(day["file_count"] for day in days_sorted),
            "size_bytes": sum(day["size_bytes"] for day in days_sorted),
            "days": days_sorted,
        }
        write_json(catalog_root / radar / year / "coverage.json", payload)

    radars = []
    for radar, row in sorted(radar_totals.items()):
        dates = sorted(row["dates"])
        years = sorted(row["years"])
        radars.append({
            "radar": radar,
            "radar_num": RADAR_NUM_BY_SLUG.get(radar, ""),
            "file_count": row["file_count"],
            "size_bytes": row["size_bytes"],
            "date_count": len(dates),
            "years": years,
            "first_date": dates[0] if dates else "",
            "last_date": dates[-1] if dates else "",
            "coverage_keys": [f"{args.object_prefix}/catalog/pvol/{radar}/{year}/coverage.json" for year in years],
        })

    root_catalog = {
        "schema_version": 1,
        "kind": "pvol_catalog",
        "generated_at": generated_at,
        "dataset": "ukmo-nimrod",
        "product": "pvol",
        "description": "Per-volume ODIM-like HDF5 files prepared as input for vol2bird/bioRad processing.",
        "object_prefix": f"{args.object_prefix}/pvol",
        "catalog_prefix": f"{args.object_prefix}/catalog/pvol",
        "coverage_csv_key": f"{args.object_prefix}/catalog/pvol/coverage.csv",
        "file_count": file_count,
        "size_bytes": byte_count,
        "size_TB": byte_count / 1e12,
        "size_TiB": byte_count / (1024 ** 4),
        "day_count": day_count,
        "radar_count": len(radars),
        "radars": radars,
    }
    write_json(catalog_root / "catalog.json", root_catalog)
    write_json(catalog_root / "coverage.json", {**root_catalog, "coverage_csv_key": f"{args.object_prefix}/catalog/pvol/coverage.csv"})

    summary = {
        "ok": True,
        "generated_at": generated_at,
        "seconds": time.time() - started,
        "stage_root": str(stage_root),
        "catalog_root": str(catalog_root),
        "catalog_key": f"{args.object_prefix}/catalog/pvol/catalog.json",
        "coverage_csv_key": f"{args.object_prefix}/catalog/pvol/coverage.csv",
        "file_count": file_count,
        "day_count": day_count,
        "radar_count": len(radars),
        "size_bytes": byte_count,
        "size_TB": byte_count / 1e12,
        "size_TiB": byte_count / (1024 ** 4),
    }
    write_json(args.run_dir / "pvol_catalog_build_summary.json", summary)
    log(f"build_complete files={file_count} days={day_count} TB={byte_count/1e12:.3f} catalog_root={catalog_root}")
    return summary


def upload_catalog(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    if not args.upload:
        log("upload skipped")
        return
    cfg = load_object_store_config(args.config)
    client = create_s3_client(cfg, internal=True)
    catalog_root = Path(summary["catalog_root"])
    stage_root = args.stage_root
    files = sorted(path for path in catalog_root.rglob("*") if path.is_file())
    log(f"uploading catalog files={len(files)} bucket={cfg.public_bucket}")
    for index, path in enumerate(files, 1):
        key = str(path.relative_to(stage_root))
        suffix = path.suffix.lower()
        content_type = "application/json" if suffix == ".json" else "text/csv" if suffix == ".csv" else "application/octet-stream"
        extra = {"ACL": "public-read", "ContentType": content_type, "Metadata": {"uk-wsr-kind": "pvol_catalog", "sha256": sha256_file(path)}}
        client.upload_file(str(path), cfg.public_bucket, key, ExtraArgs=extra)
        if index % args.upload_progress_every == 0:
            log(f"upload_progress files={index}/{len(files)} last={key}")
    uploaded = dict(summary)
    uploaded.update({"uploaded": True, "uploaded_at": utc_now(), "uploaded_file_count": len(files)})
    write_json(args.run_dir / "pvol_catalog_upload_summary.json", uploaded)
    log(f"upload_complete files={len(files)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an ALOFT-style pvol catalog mirror and optionally upload it to the object store.")
    parser.add_argument("--pvol-base", type=Path, default=Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site"))
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("/home/users/rrniii/uk-wsr-visualizer/configs/object_store.ncas-radar-o.toml"))
    parser.add_argument("--object-prefix", default="ukmo-nimrod")
    parser.add_argument("--public-base-url", default="https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public")
    parser.add_argument("--radar")
    parser.add_argument("--year")
    parser.add_argument("--date")
    parser.add_argument("--max-days", type=int)
    parser.add_argument("--progress-every", type=int, default=100000)
    parser.add_argument("--progress-days", type=int, default=1000)
    parser.add_argument("--upload-progress-every", type=int, default=1000)
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    args.stage_root.mkdir(parents=True, exist_ok=True)
    summary = build_catalog(args)
    upload_catalog(args, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
