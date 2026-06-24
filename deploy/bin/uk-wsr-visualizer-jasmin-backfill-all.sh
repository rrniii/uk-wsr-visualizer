#!/usr/bin/env bash
set -u -o pipefail

TOOLKIT_DIR="${TOOLKIT_DIR:-$HOME/uk-wsr-visualizer}"
PYTHON_BIN="${PYTHON_BIN:-/apps/jasmin/jaspy/miniforge_envs/jaspy3.12/mf3-25.3.0-3/bin/python}"
AGGREGATE_BASE="${AGGREGATE_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}"
CONFIG="${CONFIG:-configs/object_store.ncas-radar-o.toml}"
DATA_DIR="${DATA_DIR:-data/uk-wsr-visualizer}"
PUBLIC_BUCKET="${PUBLIC_BUCKET:-uk-wsr-visualizer-public}"
PUBLIC_BASE="${PUBLIC_BASE:-https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public}"
STATE_DIR="${STATE_DIR:-$DATA_DIR/object-store/backfill/all-available}"
SINGLE_RUNNER="${SINGLE_RUNNER:-deploy/bin/uk-wsr-visualizer-jasmin-backfill-year.sh}"
MAX_PAIRS="${MAX_PAIRS:-}"

cd "$TOOLKIT_DIR" || exit 1
export PYTHONPATH="$PWD/.deps:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$STATE_DIR/logs" "$STATE_DIR/complete"
PAIR_LIST="$STATE_DIR/available-radar-years.txt"
FAILED_LIST="$STATE_DIR/failed-radar-years.txt"
RUN_LOG="$STATE_DIR/backfill-all.log"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$RUN_LOG"
}

discover_pairs() {
  "$PYTHON_BIN" -B - "$AGGREGATE_BASE" "$PAIR_LIST" <<'PY'
import sys
from pathlib import Path

base = Path(sys.argv[1])
out = Path(sys.argv[2])
pairs = set()
for path in base.glob("*/*/*_aggregate.h5"):
    try:
        year = path.parent.name
        radar = path.parent.parent.name
    except Exception:
        continue
    if year.isdigit() and len(year) == 4:
        pairs.add((radar, year))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(f"{radar} {year}" for radar, year in sorted(pairs)) + "\n", encoding="utf-8")
print(f"discovered {len(pairs)} radar/year pairs")
PY
}

publish_incremental_catalog() {
  "$PYTHON_BIN" -B - "$DATA_DIR" "$PUBLIC_BUCKET" <<'PY'
import json
import sys
from pathlib import Path

import boto3

data_dir = Path(sys.argv[1])
bucket = sys.argv[2]
items = []
for path in sorted(data_dir.glob("catalog-*-????-fast.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"skip unreadable catalog {path}: {exc}")
        continue
    items.extend(payload.get("items", []))

items.sort(key=lambda item: (str(item.get("radar", "")), str(item.get("date", ""))))
catalog = {
    "generated_for": "public-object-store",
    "items": items,
    "private_paths_redacted": True,
    "version": 1,
}
status = {
    "ok": True,
    "catalog_item_count": len(items),
    "published_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    "message": "Incremental all-available UK WSR Visualizer catalog.",
}

session = boto3.Session(profile_name="ncas-radar-o")
client = session.client("s3", endpoint_url="http://ncas-radar-o.s3.jc.rl.ac.uk", region_name="us-east-1")
client.put_object(
    Bucket=bucket,
    Key="uk-radar/catalog/inventory/catalog.json",
    Body=json.dumps(catalog, indent=2, sort_keys=True).encode("utf-8"),
    ContentType="application/json",
    ACL="public-read",
    Metadata={"uk-wsr-kind": "catalog_inventory", "uk-wsr-run-id": "all-available-incremental"},
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

discover_pairs | tee -a "$RUN_LOG"
: > "$FAILED_LIST"
count=0

while read -r radar year; do
  [ -n "${radar:-}" ] || continue
  complete_marker="$STATE_DIR/complete/${radar}-${year}.done"
  pair_log="$STATE_DIR/logs/${radar}-${year}.log"
  if [ -f "$complete_marker" ]; then
    log "skip ${radar} ${year}; already marked complete"
    continue
  fi
  count=$((count + 1))
  if [ -n "$MAX_PAIRS" ] && [ "$count" -gt "$MAX_PAIRS" ]; then
    log "stopping after MAX_PAIRS=${MAX_PAIRS}"
    break
  fi

  log "start ${radar} ${year}"
  if env \
    TOOLKIT_DIR="$TOOLKIT_DIR" \
    PYTHON_BIN="$PYTHON_BIN" \
    AGGREGATE_BASE="$AGGREGATE_BASE" \
    CONFIG="$CONFIG" \
    DATA_DIR="$DATA_DIR" \
    PUBLIC_BASE="$PUBLIC_BASE" \
    RADAR="$radar" \
    YEAR="$year" \
    bash "$SINGLE_RUNNER" >> "$pair_log" 2>&1; then
    touch "$complete_marker"
    log "complete ${radar} ${year}; publishing incremental merged catalog"
    if publish_incremental_catalog >> "$RUN_LOG" 2>&1; then
      log "published incremental catalog after ${radar} ${year}"
    else
      log "incremental catalog publish failed after ${radar} ${year}"
      printf '%s %s incremental-catalog\n' "$radar" "$year" >> "$FAILED_LIST"
    fi
  else
    status=$?
    log "failed ${radar} ${year} exit=${status}; continuing"
    printf '%s %s exit=%s\n' "$radar" "$year" "$status" >> "$FAILED_LIST"
  fi
done < "$PAIR_LIST"

log "finished all-available loop; failures=$(wc -l < "$FAILED_LIST" | tr -d ' ')"
