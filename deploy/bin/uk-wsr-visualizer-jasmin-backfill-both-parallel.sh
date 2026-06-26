#!/usr/bin/env bash
set -u -o pipefail

TOOLKIT_DIR="${TOOLKIT_DIR:-$HOME/uk-wsr-visualizer}"
PYTHON_BIN="${PYTHON_BIN:-/apps/jasmin/jaspy/miniforge_envs/jaspy3.12/mf3-25.3.0-3/bin/python}"
AGGREGATE_BASE="${AGGREGATE_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}"
RAW_VOLUME_BASE="${RAW_VOLUME_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site}"
CONFIG="${CONFIG:-configs/object_store.ncas-radar-o.toml}"
DATA_DIR="${DATA_DIR:-data/uk-wsr-visualizer}"
PUBLIC_BUCKET="${PUBLIC_BUCKET:-uk-wsr-visualizer-public}"
PUBLIC_BASE="${PUBLIC_BASE:-https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public}"
ENDPOINT_URL="${ENDPOINT_URL:-http://ncas-radar-o.s3.jc.rl.ac.uk}"
AWS_PROFILE_NAME="${AWS_PROFILE_NAME:-ncas-radar-o}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_DIR="${STATE_DIR:-$DATA_DIR/object-store/backfill/all-available-both}"
RAW_RUN_ROOT="${RAW_RUN_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/raw-volume-backfill}"
AGGREGATE_RUNNER="${AGGREGATE_RUNNER:-deploy/bin/uk-wsr-visualizer-jasmin-backfill-year.sh}"
RAW_RUNNER="${RAW_RUNNER:-tools/raw_volume_object_store_backfill.py}"
CONCURRENCY="${CONCURRENCY:-4}"
MAX_PAIRS="${MAX_PAIRS:-}"
RAW_VOLUME_AWS_DIRECTORY_COMMAND="${RAW_VOLUME_AWS_DIRECTORY_COMMAND:-sync}"
RAW_VOLUME_AWS_EXTRA_ARGS="${RAW_VOLUME_AWS_EXTRA_ARGS:---no-progress}"
RAW_VOLUME_SKIP_PUBLIC_HEAD="${RAW_VOLUME_SKIP_PUBLIC_HEAD:-1}"
DISCOVER_ONLY="${DISCOVER_ONLY:-0}"
PUBLISH_ONLY="${PUBLISH_ONLY:-0}"
RUN_SINGLE_PAIR="${RUN_SINGLE_PAIR:-0}"
PAIR_RADAR="${PAIR_RADAR:-}"
PAIR_YEAR="${PAIR_YEAR:-}"
PUBLISH_AFTER_PAIR="${PUBLISH_AFTER_PAIR:-1}"

cd "$TOOLKIT_DIR" || exit 1
export PYTHONPATH="$PWD/.deps:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p \
  "$STATE_DIR/logs" \
  "$STATE_DIR/pair-complete" \
  "$STATE_DIR/aggregate-complete" \
  "$STATE_DIR/raw-complete" \
  "$STATE_DIR/locks"

PAIR_LIST="$STATE_DIR/available-radar-years.txt"
FAILED_LIST="$STATE_DIR/failed-radar-years.txt"
RUN_LOG="$STATE_DIR/backfill-both-parallel.log"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$RUN_LOG"
}

discover_pairs() {
  "$PYTHON_BIN" -B - "$AGGREGATE_BASE" "$RAW_VOLUME_BASE" "$PAIR_LIST" <<'PY'
import sys
from pathlib import Path

aggregate_base = Path(sys.argv[1])
raw_volume_base = Path(sys.argv[2])
out = Path(sys.argv[3])
pairs = set()

for radar_dir in sorted(path for path in aggregate_base.iterdir() if path.is_dir()) if aggregate_base.exists() else []:
    for year_dir in sorted(path for path in radar_dir.iterdir() if path.is_dir()):
        if year_dir.name.isdigit() and len(year_dir.name) == 4 and any(year_dir.glob("*_aggregate.h5")):
            pairs.add((radar_dir.name, year_dir.name))

for radar_dir in sorted(path for path in raw_volume_base.iterdir() if path.is_dir()) if raw_volume_base.exists() else []:
    for year_dir in sorted(path for path in radar_dir.iterdir() if path.is_dir()):
        if not (year_dir.name.isdigit() and len(year_dir.name) == 4):
            continue
        if any(path.is_dir() and path.name.isdigit() and len(path.name) == 8 for path in year_dir.iterdir()):
            pairs.add((radar_dir.name, year_dir.name))

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(f"{radar} {year}" for radar, year in sorted(pairs)) + "\n", encoding="utf-8")
print(f"discovered {len(pairs)} radar/year pairs")
PY
}

publish_combined_catalog() {
  "$PYTHON_BIN" -B - "$DATA_DIR" "$PUBLIC_BUCKET" "$STATE_DIR" "$RAW_RUN_ROOT" "$PUBLIC_BASE" "$ENDPOINT_URL" "$AWS_PROFILE_NAME" "$AWS_REGION" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

data_dir = Path(sys.argv[1])
bucket = sys.argv[2]
state_dir = Path(sys.argv[3])
raw_run_root = Path(sys.argv[4])
public_base = sys.argv[5].rstrip("/")
endpoint_url = sys.argv[6]
aws_profile = sys.argv[7]
aws_region = sys.argv[8]


def load_items(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"skip unreadable catalog {path}: {exc}")
        return []
    return list(payload.get("items", []))


def url_for(key: str) -> str:
    return f"{public_base}/{key.lstrip('/')}" if key else ""


def redact_aggregate_item(item: dict) -> dict:
    item = dict(item)
    item["path"] = ""
    if item.get("object_key") and not item.get("object_url"):
        item["object_url"] = url_for(item["object_key"])
    item["raw_volumes"] = []
    item.setdefault("raw_volume_catalog_key", "")
    item.setdefault("raw_volume_catalog_url", "")
    return item


def slim_raw_item(item: dict, catalog_key: str) -> dict:
    """Return day-level raw metadata without embedding every raw-volume object."""
    item = dict(item)
    item["path"] = ""
    item["file_size"] = int(item.get("file_size") or 0)
    item["object_key"] = ""
    item["object_url"] = ""
    item["raw_volumes"] = []
    item["quantity_records"] = []
    item["raw_volume_catalog_key"] = catalog_key
    item["raw_volume_catalog_url"] = url_for(catalog_key)
    return item


def raw_item_from_day_catalog(catalog: Path, radar: str, year: str) -> list[dict]:
    date = catalog.parent.name
    catalog_key = f"uk-radar/catalog/inventory/raw-volume/{radar}/{year}/{date}/catalog.json"
    slim_items = []
    for item in load_items(catalog):
        slim_items.append(slim_raw_item(item, catalog_key))
    return slim_items


def merge_raw_with_aggregate(raw_item: dict, aggregate_item: dict | None) -> dict:
    if aggregate_item is None:
        return raw_item
    merged = dict(raw_item)
    # Keep the aggregate HDF5 source URL as provenance/fallback while the
    # per-day raw-volume catalog remains the interactive source.
    for key in ("object_key", "object_url", "file_size", "modified_time", "path"):
        merged[key] = aggregate_item.get(key, merged.get(key, "" if key != "file_size" else 0))
    merged["raw_volume_catalog_key"] = raw_item.get("raw_volume_catalog_key", "")
    merged["raw_volume_catalog_url"] = raw_item.get("raw_volume_catalog_url", "")
    merged["source_type"] = "raw_volume_day"
    return merged


aggregate_items = []
for marker in sorted((state_dir / "aggregate-complete").glob("*.done")):
    catalog = data_dir / f"catalog-{marker.stem}-fast.json"
    aggregate_items.extend(redact_aggregate_item(item) for item in load_items(catalog))

raw_items = []
for marker in sorted((state_dir / "raw-complete").glob("*.done")):
    try:
        radar, year = marker.stem.rsplit("-", 1)
    except ValueError:
        continue
    for catalog in sorted((raw_run_root / radar / year).glob("*/catalog.json")):
        raw_items.extend(raw_item_from_day_catalog(catalog, radar, year))

raw_by_day = {(item.get("radar"), item.get("date")): item for item in raw_items}
aggregate_by_day = {(item.get("radar"), item.get("date")): item for item in aggregate_items}
merged = [merge_raw_with_aggregate(item, aggregate_by_day.get(key)) for key, item in raw_by_day.items()]
for key, item in aggregate_by_day.items():
    if key not in raw_by_day:
        merged.append(item)

for items in (aggregate_items, raw_items, merged):
    items.sort(key=lambda item: (str(item.get("radar", "")), str(item.get("date", ""))))

generated_at = datetime.now(timezone.utc).isoformat()
payloads = {
    "uk-radar/catalog/inventory/aggregate/catalog.json": {
        "version": 1,
        "generated_for": "public-object-store-aggregate-fallback",
        "generated_at": generated_at,
        "private_paths_redacted": True,
        "items": aggregate_items,
    },
    "uk-radar/catalog/inventory/raw-volume/catalog.json": {
        "version": 1,
        "generated_for": "public-object-store-raw-volume-primary",
        "generated_at": generated_at,
        "private_paths_redacted": True,
        "items": raw_items,
    },
    "uk-radar/catalog/inventory/catalog.json": {
        "version": 1,
        "generated_for": "app-raw-volume-primary-with-aggregate-fallback",
        "generated_at": generated_at,
        "private_paths_redacted": True,
        "items": merged,
    },
}
status = {
    "ok": True,
    "published_at": generated_at,
    "message": "Combined UK WSR Visualizer catalog. Raw-volume days are primary; aggregate HDF5 days are fallback.",
    "aggregate_radar_year_count": len(list((state_dir / "aggregate-complete").glob("*.done"))),
    "raw_volume_radar_year_count": len(list((state_dir / "raw-complete").glob("*.done"))),
    "aggregate_item_count": len(aggregate_items),
    "raw_volume_item_count": len(raw_items),
    "app_catalog_item_count": len(merged),
}

session = boto3.Session(profile_name=aws_profile)
client = session.client("s3", endpoint_url=endpoint_url, region_name=aws_region)
for key, payload in payloads.items():
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
        ACL="public-read",
        Metadata={"uk-wsr-kind": "catalog_inventory", "uk-wsr-run-id": "all-available-both-parallel"},
    )
client.put_object(
    Bucket=bucket,
    Key="uk-radar/status.json",
    Body=json.dumps(status, indent=2, sort_keys=True).encode("utf-8"),
    ContentType="application/json",
    ACL="public-read",
)
print(json.dumps(status, indent=2, sort_keys=True))
PY
}

append_failure() {
  local radar="$1"
  local year="$2"
  local reason="$3"
  (
    flock 8
    printf '%s %s %s\n' "$radar" "$year" "$reason" >> "$FAILED_LIST"
  ) 8>"$STATE_DIR/failures.lock"
}

run_aggregate_pair() {
  local radar="$1"
  local year="$2"
  local marker="$STATE_DIR/aggregate-complete/${radar}-${year}.done"
  local pair_log="$STATE_DIR/logs/${radar}-${year}.aggregate.log"

  if [ -f "$marker" ]; then
    log "skip aggregate ${radar} ${year}; already complete"
    return 0
  fi

  log "aggregate start ${radar} ${year}"
  if env \
    TOOLKIT_DIR="$TOOLKIT_DIR" \
    PYTHON_BIN="$PYTHON_BIN" \
    AGGREGATE_BASE="$AGGREGATE_BASE" \
    CONFIG="$CONFIG" \
    DATA_DIR="$DATA_DIR" \
    PUBLIC_BASE="$PUBLIC_BASE" \
    RAW_ONLY=1 \
    RADAR="$radar" \
    YEAR="$year" \
    bash "$AGGREGATE_RUNNER" >> "$pair_log" 2>&1; then
    touch "$marker"
    log "aggregate complete ${radar} ${year}"
    return 0
  fi

  local status
  status=$?
  log "aggregate failed ${radar} ${year} exit=${status}"
  append_failure "$radar" "$year" "aggregate_exit=${status}"
  return "$status"
}

run_raw_pair() {
  local radar="$1"
  local year="$2"
  local marker="$STATE_DIR/raw-complete/${radar}-${year}.done"
  local pair_log="$STATE_DIR/logs/${radar}-${year}.raw-volume.log"

  if [ -f "$marker" ]; then
    log "skip raw-volume ${radar} ${year}; already complete"
    return 0
  fi

  if [ ! -d "$RAW_VOLUME_BASE/$radar/$year" ]; then
    log "skip raw-volume ${radar} ${year}; no raw-volume source directory"
    touch "$marker"
    return 0
  fi

  log "raw-volume start ${radar} ${year}"
  if env \
    PYTHONPATH="$PYTHONPATH" \
    AWS_PROFILE_NAME="$AWS_PROFILE_NAME" \
    AWS_REGION="$AWS_REGION" \
    AWS_MAX_ATTEMPTS="${AWS_MAX_ATTEMPTS:-10}" \
    RAW_VOLUME_AWS_DIRECTORY_COMMAND="$RAW_VOLUME_AWS_DIRECTORY_COMMAND" \
    RAW_VOLUME_AWS_EXTRA_ARGS="$RAW_VOLUME_AWS_EXTRA_ARGS" \
    RAW_VOLUME_SKIP_PUBLIC_HEAD="$RAW_VOLUME_SKIP_PUBLIC_HEAD" \
    "$PYTHON_BIN" -B "$RAW_RUNNER" \
      --radar "$radar" \
      --year "$year" \
      --raw-volume-base "$RAW_VOLUME_BASE" \
      --run-root "$RAW_RUN_ROOT" \
      --public-base-url "$PUBLIC_BASE" \
      --endpoint-url "$ENDPOINT_URL" \
      --bucket "$PUBLIC_BUCKET" \
      --aws-profile "$AWS_PROFILE_NAME" \
      --aws-region "$AWS_REGION" \
      --aws-directory-command "$RAW_VOLUME_AWS_DIRECTORY_COMMAND" \
      --aws-extra-args="$RAW_VOLUME_AWS_EXTRA_ARGS" \
      $([ "$RAW_VOLUME_SKIP_PUBLIC_HEAD" = "1" ] && printf '%s' "--skip-public-head-check") \
      --keep-going >> "$pair_log" 2>&1; then
    touch "$marker"
    log "raw-volume complete ${radar} ${year}"
    return 0
  fi

  local status
  status=$?
  log "raw-volume failed ${radar} ${year} exit=${status}"
  append_failure "$radar" "$year" "raw_volume_exit=${status}"
  return "$status"
}

run_pair() {
  local radar="$1"
  local year="$2"
  local marker="$STATE_DIR/pair-complete/${radar}-${year}.done"
  local lockdir="$STATE_DIR/locks/${radar}-${year}.lock"

  if [ -f "$marker" ]; then
    log "skip pair ${radar} ${year}; already complete"
    return 0
  fi
  if ! mkdir "$lockdir" 2>/dev/null; then
    if rmdir "$lockdir" 2>/dev/null && mkdir "$lockdir" 2>/dev/null; then
      log "recovered stale empty lock for ${radar} ${year}"
    else
      log "skip pair ${radar} ${year}; lock already held"
      return 0
    fi
  fi
  printf '%s\n' "$$" > "$lockdir/pid"
  trap 'rm -f "$lockdir/pid" 2>/dev/null || true; rmdir "$lockdir" 2>/dev/null || true' RETURN

  log "pair start ${radar} ${year}"
  run_aggregate_pair "$radar" "$year" &
  local aggregate_pid=$!
  run_raw_pair "$radar" "$year" &
  local raw_pid=$!

  wait "$aggregate_pid"
  local aggregate_status=$?
  wait "$raw_pid"
  local raw_status=$?

  if [ "$aggregate_status" -eq 0 ] && [ "$raw_status" -eq 0 ]; then
    touch "$marker"
    log "pair complete ${radar} ${year}"
    if [ "$PUBLISH_AFTER_PAIR" = "1" ]; then
      (
        flock 9
        log "publishing combined catalog after ${radar} ${year}"
        publish_combined_catalog >> "$RUN_LOG" 2>&1
      ) 9>"$STATE_DIR/publish.lock"
    else
      log "defer combined catalog publish after ${radar} ${year}"
    fi
  else
    log "pair failed ${radar} ${year}; aggregate=${aggregate_status} raw_volume=${raw_status}"
    return 1
  fi
}

discover_pairs | tee -a "$RUN_LOG"

if [ "$DISCOVER_ONLY" = "1" ]; then
  log "discovered pair list only; exiting"
  exit 0
fi

if [ "$PUBLISH_ONLY" = "1" ]; then
  (
    flock 9
    log "publishing combined catalog only"
    publish_combined_catalog >> "$RUN_LOG" 2>&1
  ) 9>"$STATE_DIR/publish.lock"
  log "finished publish-only combined catalog"
  exit 0
fi

if [ "$RUN_SINGLE_PAIR" = "1" ]; then
  if [ -z "$PAIR_RADAR" ] || [ -z "$PAIR_YEAR" ]; then
    log "RUN_SINGLE_PAIR requires PAIR_RADAR and PAIR_YEAR"
    exit 2
  fi
  run_pair "$PAIR_RADAR" "$PAIR_YEAR"
  exit $?
fi

: > "$FAILED_LIST"

started=0
while read -r radar year; do
  [ -n "${radar:-}" ] || continue
  if [ -f "$STATE_DIR/pair-complete/${radar}-${year}.done" ]; then
    continue
  fi
  started=$((started + 1))
  if [ -n "$MAX_PAIRS" ] && [ "$started" -gt "$MAX_PAIRS" ]; then
    log "stopping launch after MAX_PAIRS=${MAX_PAIRS}"
    break
  fi
  while [ "$(jobs -rp | wc -l | tr -d ' ')" -ge "$CONCURRENCY" ]; do
    wait -n
  done
  run_pair "$radar" "$year" &
done < "$PAIR_LIST"

while [ "$(jobs -rp | wc -l | tr -d ' ')" -gt 0 ]; do
  wait -n
done

(
  flock 9
  log "publishing final combined catalog"
  publish_combined_catalog >> "$RUN_LOG" 2>&1
) 9>"$STATE_DIR/publish.lock"

log "finished combined all-available loop; failures=$(wc -l < "$FAILED_LIST" | tr -d ' ')"
