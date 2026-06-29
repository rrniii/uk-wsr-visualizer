from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time


PVOL_RE = re.compile(r"^(?P<date>[0-9]{8})_polar_pl_radar(?P<num>[0-9]{2})_aggregate_(?P<pulse>[^_]+)_(?P<time>[0-9]{4})\.h5$")
INCLUDE_RE = re.compile(r"\binclude=(?P<include>[0-9]+)\b")

RADARS = (
    ("castor-bay", "07"),
    ("chenies", "05"),
    ("clee-hill", "03"),
    ("cobbacombe", "16"),
    ("crug-y-gorrllwyn", "10"),
    ("deanhill", "21"),
    ("druima-starraig", "15"),
    ("dudwick", "14"),
    ("hameldon-hill", "04"),
    ("high-moorsley", "23"),
    ("holehead", "18"),
    ("ingham", "09"),
    ("jersey", "12"),
    ("munduff-hill", "19"),
    ("predannack", "08"),
    ("thurnham", "20"),
    ("wardon-hill", "11"),
)
RADAR_BY_SLUG = {slug for slug, _num in RADARS}
RADAR_NUM_BY_SLUG = dict(RADARS)

UPLOAD_BASE = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/pvol-fast-upload")
PVOL_BASE = Path("/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site")
PUBLIC_BASE_URL = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"
OBJECT_PREFIX = "ukmo-nimrod"
BUCKET = "uk-wsr-visualizer-public"
AWS = "/home/users/rrniii/bin/aws"
ENDPOINT = "http://ncas-radar-o.s3.jc.rl.ac.uk"
REGION = "us-east-1"
PROFILE = "ncas-radar-o"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"}


def object_key(prefix: str, *parts: str) -> str:
    return "/".join([prefix.strip("/"), *[str(part).strip("/") for part in parts if str(part).strip("/")]])


def join_object_url(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/{key.lstrip('/')}"


def raw_volume_object_key(radar: str, date: str, pulse: str, filename: str) -> str:
    return object_key(OBJECT_PREFIX, "pvol", radar, date[:4], date[4:6], date[6:8], pulse, filename)


def day_catalog_key(radar: str, year: str, date: str) -> str:
    return f"{OBJECT_PREFIX}/catalog/pvol/{radar}/{year}/{date[4:6]}/{date[6:8]}/catalog.json"


def day_catalog_path(catalog_root: Path, radar: str, year: str, date: str) -> Path:
    return catalog_root / radar / year / date[4:6] / date[6:8] / "catalog.json"


def read_target_from_log(run_dir: Path) -> int | None:
    log_path = run_dir / "publish.log"
    if not log_path.exists():
        return None
    target: int | None = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = INCLUDE_RE.search(line)
        if match:
            target = int(match.group("include"))
    return target


def collect_markers() -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    runs = [
        p
        for p in UPLOAD_BASE.iterdir()
        if p.is_dir() and (p.name.startswith("pvol_upload_") or p.name.startswith("pvol_supplemental_"))
    ]
    done: dict[tuple[str, str, str], dict[str, Any]] = {}
    failed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for run in sorted(runs):
        root = run / "day-status"
        if not root.exists():
            continue
        for suffix, target in [("*.done.json", done), ("*.failed.json", failed)]:
            for path in root.glob(f"*/*/{suffix}"):
                data = load_json(path)
                key = (path.parent.parent.name, path.parent.name, path.name.split(".", 1)[0])
                data["marker_path"] = str(path)
                data["run"] = run.name
                previous = target.get(key)
                if previous is None or data.get("finished_at", "") > previous.get("finished_at", ""):
                    target[key] = data
    open_failed = {
        key: failure
        for key, failure in failed.items()
        if key not in done or failure.get("finished_at", "") > done[key].get("finished_at", "")
    }
    return done, failed, open_failed


def pvol_record(path: Path) -> tuple[str, str, str, dict[str, Any]] | None:
    rel = path.relative_to(PVOL_BASE)
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
    key = raw_volume_object_key(radar, date, pulse, filename)
    return radar, date, pulse, {
        "pulse": pulse,
        "time": match.group("time"),
        "filename": filename,
        "size_bytes": stat.st_size,
        "modified_time": stat.st_mtime,
        "object_key": key,
        "object_url": join_object_url(PUBLIC_BASE_URL, key),
    }


def scan_day(radar: str, year: str, date: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    date_dir = PVOL_BASE / radar / year / date
    records: list[dict[str, Any]] = []
    pulse_counts: dict[str, int] = defaultdict(int)
    if not date_dir.exists():
        return records, {}
    for pulse_dir in sorted(path for path in date_dir.iterdir() if path.is_dir()):
        for path in sorted(pulse_dir.glob("*.h5")):
            parsed = pvol_record(path)
            if parsed is None:
                continue
            _radar, _date, pulse, record = parsed
            records.append(record)
            pulse_counts[pulse] += 1
    records.sort(key=lambda item: (item["pulse"], item["time"], item["filename"]))
    return records, dict(sorted(pulse_counts.items()))


def build_day_payload(radar: str, year: str, date: str, marker: dict[str, Any], generated_at: str) -> dict[str, Any] | None:
    records, pulse_counts = scan_day(radar, year, date)
    if not records:
        return None
    day_files = len(records)
    day_bytes = sum(int(record["size_bytes"]) for record in records)
    pvol_prefix = f"{OBJECT_PREFIX}/pvol/{radar}/{year}/{date[4:6]}/{date[6:8]}"
    return {
        "schema_version": 1,
        "kind": "pvol_day_catalog",
        "generated_at": generated_at,
        "interim": True,
        "upload_complete": False,
        "source_upload_marker": marker.get("marker_path", ""),
        "source_upload_run": marker.get("run", ""),
        "radar": radar,
        "radar_num": RADAR_NUM_BY_SLUG.get(radar, ""),
        "date": date,
        "pvol_prefix": pvol_prefix,
        "catalog_key": day_catalog_key(radar, year, date),
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


def aws_base() -> list[str]:
    return [AWS, "--profile", PROFILE, "--region", REGION, "--endpoint-url", ENDPOINT]


def run_command(cmd: list[str], env: dict[str, str] | None = None) -> None:
    log("run " + " ".join(cmd))
    merged_env = os.environ.copy()
    merged_env.update({"AWS_MAX_ATTEMPTS": "10", "AWS_RETRY_MODE": "adaptive"})
    merged_env["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
    merged_env["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"
    if env:
        merged_env.update(env)
    proc = subprocess.run(cmd, text=True, env=merged_env)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed rc={proc.returncode}: {cmd!r}")


def head_object(key: str) -> bool:
    cmd = aws_base() + ["s3api", "head-object", "--bucket", BUCKET, "--key", key, "--output", "json"]
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "AWS_MAX_ATTEMPTS": "5",
            "AWS_RETRY_MODE": "adaptive",
            "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
            "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
        },
    )
    return proc.returncode == 0


def target_items(
    run_dir: Path,
    explicit_target_days: int | None,
) -> tuple[
    list[tuple[tuple[str, str, str], dict[str, Any]]],
    dict[str, int | None],
]:
    done, failed, open_failed = collect_markers()
    include = {key: marker for key, marker in done.items() if key not in open_failed}
    log_target = read_target_from_log(run_dir)
    target_days = explicit_target_days if explicit_target_days is not None else log_target
    items = sorted(include.items())
    if target_days is not None and target_days > 0:
        items = items[:target_days]
    log(
        "markers "
        f"done={len(done)} failed={len(failed)} open_failed={len(open_failed)} "
        f"include_available={len(include)} target_days={target_days or len(include)} selected={len(items)}"
    )
    return items, {
        "done_marker_days": len(done),
        "failed_marker_days": len(failed),
        "excluded_open_failed_days": len(open_failed),
        "include_available_days": len(include),
        "target_candidate_days": target_days,
        "log_target_candidate_days": log_target,
    }


def staged_items(catalog_root: Path) -> tuple[
    list[tuple[tuple[str, str, str], dict[str, Any]]],
    dict[str, int | None],
]:
    items: list[tuple[tuple[str, str, str], dict[str, Any]]] = []
    for path in catalog_root.glob("*/*/*/*/catalog.json"):
        try:
            radar, year, month, day, filename = path.relative_to(catalog_root).parts
        except ValueError:
            continue
        if filename != "catalog.json" or radar not in RADAR_BY_SLUG:
            continue
        date = f"{year}{month}{day}"
        if not (len(date) == 8 and date.isdigit() and year == date[:4]):
            continue
        items.append(((radar, year, date), {"marker_path": "", "run": "staged"}))
    items.sort(key=lambda item: item[0])
    log(f"staged_only selected={len(items)}")
    return items, {
        "done_marker_days": None,
        "failed_marker_days": None,
        "excluded_open_failed_days": None,
        "include_available_days": None,
        "target_candidate_days": len(items),
        "log_target_candidate_days": read_target_from_log(catalog_root.parents[3]),
        "staged_only": 1,
    }


def ensure_day_catalogs(
    catalog_root: Path,
    items: list[tuple[tuple[str, str, str], dict[str, Any]]],
    generated_at: str,
) -> dict[str, Any]:
    existing = 0
    built = 0
    skipped_empty: list[dict[str, str]] = []
    for index, ((radar, year, date), marker) in enumerate(items, 1):
        path = day_catalog_path(catalog_root, radar, year, date)
        if path.exists() and path.stat().st_size > 0:
            existing += 1
        else:
            payload = build_day_payload(radar, year, date, marker, generated_at)
            if payload is None:
                skipped_empty.append({"radar": radar, "year": year, "date": date, "marker_path": marker.get("marker_path", "")})
            else:
                write_json(path, payload)
                built += 1
        if index % 500 == 0:
            log(f"resume_progress checked={index} existing={existing} built={built} skipped_empty={len(skipped_empty)} last={radar}/{date}")
    log(f"resume_day_catalogs_complete selected={len(items)} existing={existing} built={built} skipped_empty={len(skipped_empty)}")
    return {"existing_day_catalogs": existing, "built_day_catalogs": built, "skipped_empty": skipped_empty}


def load_or_rebuild_day(
    catalog_root: Path,
    radar: str,
    year: str,
    date: str,
    marker: dict[str, Any],
    generated_at: str,
    allow_rebuild: bool,
) -> tuple[dict[str, Any] | None, bool]:
    path = day_catalog_path(catalog_root, radar, year, date)
    payload = load_json(path) if path.exists() else {"read_error": "missing"}
    if payload.get("read_error") or payload.get("kind") != "pvol_day_catalog":
        if not allow_rebuild:
            return None, False
        rebuilt = build_day_payload(radar, year, date, marker, generated_at)
        if rebuilt is None:
            return None, True
        write_json(path, rebuilt)
        return rebuilt, True
    return payload, False


def build_indexes(
    run_dir: Path,
    catalog_root: Path,
    items: list[tuple[tuple[str, str, str], dict[str, Any]]],
    marker_counts: dict[str, int | None],
    ensure_result: dict[str, Any],
    generated_at: str,
    allow_rebuild: bool = True,
) -> dict[str, Any]:
    started = time.time()
    radar_totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"file_count": 0, "size_bytes": 0, "dates": [], "years": set()})
    year_days: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    coverage_rows: list[dict[str, Any]] = []
    skipped_empty = list(ensure_result["skipped_empty"])
    sample_object_keys: list[str] = []
    file_count = 0
    byte_count = 0
    day_count = 0
    rebuilt_during_index = 0

    for index, ((radar, year, date), marker) in enumerate(items, 1):
        day_payload, rebuilt = load_or_rebuild_day(catalog_root, radar, year, date, marker, generated_at, allow_rebuild)
        if rebuilt:
            rebuilt_during_index += 1
        if day_payload is None:
            skipped_empty.append({"radar": radar, "year": year, "date": date, "marker_path": marker.get("marker_path", "")})
            continue
        day_files = int(day_payload.get("file_count", 0))
        day_bytes = int(day_payload.get("size_bytes", 0))
        if day_files <= 0:
            skipped_empty.append({"radar": radar, "year": year, "date": date, "marker_path": marker.get("marker_path", "")})
            continue
        pvol_prefix = day_payload.get("pvol_prefix") or f"{OBJECT_PREFIX}/pvol/{radar}/{year}/{date[4:6]}/{date[6:8]}"
        catalog_key = day_payload.get("catalog_key") or day_catalog_key(radar, year, date)
        pulse_counts = day_payload.get("pulse_counts", {})
        year_days[(radar, year)].append(
            {
                "date": date,
                "catalog_key": catalog_key,
                "pvol_prefix": pvol_prefix,
                "file_count": day_files,
                "size_bytes": day_bytes,
                "pulse_counts": pulse_counts,
            }
        )
        rt = radar_totals[radar]
        rt["file_count"] += day_files
        rt["size_bytes"] += day_bytes
        rt["dates"].append(date)
        rt["years"].add(year)
        coverage_rows.append({"directory": pvol_prefix, "file_count": day_files, "total_bytes": day_bytes})
        file_count += day_files
        byte_count += day_bytes
        day_count += 1
        if len(sample_object_keys) < 20:
            files = day_payload.get("files", [])
            if isinstance(files, list):
                for record in files:
                    key = record.get("object_key") if isinstance(record, dict) else None
                    if key:
                        sample_object_keys.append(key)
                    if len(sample_object_keys) >= 20:
                        break
        if index % 500 == 0:
            log(f"index_progress indexed={index} days={day_count} files={file_count} TB={byte_count / 1e12:.3f} last={radar}/{date}")

    coverage_csv = catalog_root / "coverage.csv"
    with coverage_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["directory", "file_count", "total_bytes"])
        for row in sorted(coverage_rows, key=lambda item: item["directory"]):
            writer.writerow([row["directory"], row["file_count"], row["total_bytes"]])

    for (radar, year), days in sorted(year_days.items()):
        days_sorted = sorted(days, key=lambda item: item["date"])
        write_json(
            catalog_root / radar / year / "coverage.json",
            {
                "schema_version": 1,
                "kind": "pvol_year_coverage",
                "generated_at": generated_at,
                "interim": True,
                "upload_complete": False,
                "radar": radar,
                "year": year,
                "date_count": len(days_sorted),
                "file_count": sum(day["file_count"] for day in days_sorted),
                "size_bytes": sum(day["size_bytes"] for day in days_sorted),
                "days": days_sorted,
            },
        )

    radars = []
    for radar, row in sorted(radar_totals.items()):
        dates = sorted(row["dates"])
        years = sorted(row["years"])
        radars.append(
            {
                "radar": radar,
                "radar_num": RADAR_NUM_BY_SLUG.get(radar, ""),
                "file_count": row["file_count"],
                "size_bytes": row["size_bytes"],
                "date_count": len(dates),
                "years": years,
                "first_date": dates[0] if dates else "",
                "last_date": dates[-1] if dates else "",
                "coverage_keys": [f"{OBJECT_PREFIX}/catalog/pvol/{radar}/{year}/coverage.json" for year in years],
            }
        )

    root_catalog = {
        "schema_version": 1,
        "kind": "pvol_catalog",
        "generated_at": generated_at,
        "interim": True,
        "upload_complete": False,
        "dataset": "ukmo-nimrod",
        "product": "pvol",
        "description": "Interim uploaded-only PVOL catalog for app smoke testing while the full upload is still running.",
        "object_prefix": f"{OBJECT_PREFIX}/pvol",
        "catalog_prefix": f"{OBJECT_PREFIX}/catalog/pvol",
        "coverage_csv_key": f"{OBJECT_PREFIX}/catalog/pvol/coverage.csv",
        "file_count": file_count,
        "size_bytes": byte_count,
        "size_TB": byte_count / 1e12,
        "size_TiB": byte_count / (1024**4),
        "day_count": day_count,
        "radar_count": len(radars),
        "radars": radars,
        "included_done_days": day_count,
        "candidate_done_days": len(items),
        "skipped_empty_done_days": len(skipped_empty),
        "source_upload_base": str(UPLOAD_BASE),
        **marker_counts,
    }
    write_json(catalog_root / "catalog.json", root_catalog)
    write_json(catalog_root / "coverage.json", {**root_catalog, "coverage_csv_key": f"{OBJECT_PREFIX}/catalog/pvol/coverage.csv"})

    summary = {
        "ok": True,
        "interim": True,
        "generated_at": generated_at,
        "seconds": time.time() - started,
        "run_dir": str(run_dir),
        "stage_root": str(catalog_root.parent.parent.parent),
        "catalog_root": str(catalog_root),
        "catalog_key": f"{OBJECT_PREFIX}/catalog/pvol/catalog.json",
        "coverage_csv_key": f"{OBJECT_PREFIX}/catalog/pvol/coverage.csv",
        "file_count": file_count,
        "day_count": day_count,
        "radar_count": len(radars),
        "size_bytes": byte_count,
        "size_TB": byte_count / 1e12,
        "size_TiB": byte_count / (1024**4),
        "candidate_done_days": len(items),
        "skipped_empty_done_days": len(skipped_empty),
        "rebuilt_during_index": rebuilt_during_index,
        "sample_object_keys": sample_object_keys[:10],
        "skipped_empty_examples": skipped_empty[:20],
        **ensure_result,
        **marker_counts,
    }
    write_json(run_dir / "interim_catalog_build_summary.json", summary)
    log(
        f"build_complete days={day_count} files={file_count} TB={byte_count / 1e12:.3f} "
        f"skipped_empty={len(skipped_empty)} rebuilt_during_index={rebuilt_during_index}"
    )
    return summary


def upload_catalog(run_dir: Path, catalog_root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    root_catalog = catalog_root / "catalog.json"
    root_coverage = catalog_root / "coverage.json"
    coverage_csv = catalog_root / "coverage.csv"
    hold = run_dir / "root_hold"
    hold.mkdir(exist_ok=True)
    for root_file in [root_catalog, root_coverage]:
        held_file = hold / root_file.name
        if not root_file.exists() and held_file.exists():
            held_file.replace(root_file)
    held: list[tuple[Path, Path]] = []
    for root_file in [root_catalog, root_coverage]:
        held_file = hold / root_file.name
        if held_file.exists():
            held_file.unlink()
        root_file.replace(held_file)
        held.append((held_file, root_file))
    dest = f"s3://{BUCKET}/{OBJECT_PREFIX}/catalog/pvol/"
    try:
        run_command(
            aws_base()
            + [
                "s3",
                "sync",
                str(catalog_root) + "/",
                dest,
                "--acl",
                "public-read",
                "--only-show-errors",
                "--no-progress",
                "--exclude",
                "*.tmp",
            ]
        )
    finally:
        for held_file, root_file in held:
            if held_file.exists() and not root_file.exists():
                held_file.replace(root_file)
    run_command(
        aws_base()
        + [
            "s3",
            "cp",
            str(coverage_csv),
            dest + "coverage.csv",
            "--acl",
            "public-read",
            "--content-type",
            "text/csv",
            "--only-show-errors",
            "--no-progress",
        ]
    )
    run_command(
        aws_base()
        + [
            "s3",
            "cp",
            str(root_coverage),
            dest + "coverage.json",
            "--acl",
            "public-read",
            "--content-type",
            "application/json",
            "--only-show-errors",
            "--no-progress",
        ]
    )
    run_command(
        aws_base()
        + [
            "s3",
            "cp",
            str(root_catalog),
            dest + "catalog.json",
            "--acl",
            "public-read",
            "--content-type",
            "application/json",
            "--only-show-errors",
            "--no-progress",
        ]
    )
    uploaded = dict(summary)
    uploaded.update({"uploaded": True, "uploaded_at": utc_now()})
    write_json(run_dir / "interim_catalog_upload_summary.json", uploaded)
    log("upload_complete")
    return uploaded


def smoke_check(run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    root_key = f"{OBJECT_PREFIX}/catalog/pvol/catalog.json"
    coverage_key = f"{OBJECT_PREFIX}/catalog/pvol/coverage.csv"
    coverage_json_key = f"{OBJECT_PREFIX}/catalog/pvol/coverage.json"
    for key in [root_key, coverage_key, coverage_json_key]:
        checks.append({"kind": "catalog_object", "key": key, "head_ok": head_object(key)})
    for key in summary.get("sample_object_keys", [])[:10]:
        checks.append({"kind": "sample_pvol_object", "key": key, "head_ok": head_object(key)})
    ok = all(item["head_ok"] for item in checks)
    payload = {"ok": ok, "checked_at": utc_now(), "checks": checks}
    write_json(run_dir / "interim_catalog_smoke.json", payload)
    log(f"smoke_complete ok={ok} checks={len(checks)}")
    if not ok:
        raise RuntimeError("smoke check failed")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume and publish an uploaded-only interim PVOL catalog.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--target-days", type=int, default=None, help="Number of sorted uploaded days to publish; default reads include=N from publish.log.")
    parser.add_argument("--staged-only", action="store_true", help="Publish the day catalogs already staged, without reading upload markers or rebuilding source days.")
    parser.add_argument("--upload-only", action="store_true", help="Use the existing interim_catalog_build_summary.json and upload/smoke without rebuilding indexes.")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    run_dir = args.run_dir.resolve()
    stage_root = run_dir / "stage"
    catalog_root = stage_root / OBJECT_PREFIX / "catalog" / "pvol"
    catalog_root.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()
    log(f"resume_interim_catalog_start run_dir={run_dir}")
    if args.upload_only:
        summary = load_json(run_dir / "interim_catalog_build_summary.json")
        if summary.get("read_error"):
            raise RuntimeError(f"missing build summary: {summary['read_error']}")
    elif args.staged_only:
        items, marker_counts = staged_items(catalog_root)
        ensure_result = {"existing_day_catalogs": len(items), "built_day_catalogs": 0, "skipped_empty": []}
        summary = build_indexes(run_dir, catalog_root, items, marker_counts, ensure_result, generated_at, allow_rebuild=False)
    else:
        items, marker_counts = target_items(run_dir, args.target_days)
        ensure_result = ensure_day_catalogs(catalog_root, items, generated_at)
        summary = build_indexes(run_dir, catalog_root, items, marker_counts, ensure_result, generated_at)
    if args.skip_upload:
        log("upload_skipped")
        return 0
    uploaded = upload_catalog(run_dir, catalog_root, summary)
    if not args.skip_smoke:
        smoke_check(run_dir, uploaded)
    log("resume_interim_catalog_finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
