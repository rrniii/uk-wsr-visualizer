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
CONCURRENCY="${CONCURRENCY:-3}"
MAX_PAIRS="${MAX_PAIRS:-}"

cd "$TOOLKIT_DIR" || exit 1
export PYTHONPATH="$PWD/.deps:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$STATE_DIR/logs" "$STATE_DIR/complete" "$STATE_DIR/locks"
PAIR_LIST="$STATE_DIR/available-radar-years.txt"
FAILED_LIST="$STATE_DIR/failed-radar-years.txt"
RUN_LOG="$STATE_DIR/backfill-all-parallel.log"

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

publish_completed_catalog() {
  "$PYTHON_BIN" -B - "$DATA_DIR" "$PUBLIC_BUCKET" "$STATE_DIR/complete" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

data_dir = Path(sys.argv[1])
bucket = sys.argv[2]
complete_dir = Path(sys.argv[3])
completed = {path.stem for path in complete_dir.glob("*.done")}
items = []

for marker in sorted(completed):
    catalog = data_dir / f"catalog-{marker}-fast.json"
    if not catalog.exists():
        print(f"skip missing completed catalog {catalog}")
        continue
    try:
        payload = json.loads(catalog.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"skip unreadable catalog {catalog}: {exc}")
        continue
    items.extend(payload.get("items", []))

items.sort(key=lambda item: (str(item.get("radar", "")), str(item.get("date", ""))))
payload = {
    "generated_for": "public-object-store",
    "items": items,
    "private_paths_redacted": True,
    "version": 1,
}
status = {
    "ok": True,
    "completed_radar_year_count": len(completed),
    "catalog_item_count": len(items),
    "published_at": datetime.now(timezone.utc).isoformat(),
    "message": "Incremental completed-year UK WSR Visualizer catalog.",
}

session = boto3.Session(profile_name="ncas-radar-o")
client = session.client("s3", endpoint_url="http://ncas-radar-o.s3.jc.rl.ac.uk", region_name="us-east-1")
client.put_object(
    Bucket=bucket,
    Key="uk-radar/catalog/inventory/catalog.json",
    Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
    ContentType="application/json",
    ACL="public-read",
    Metadata={"uk-wsr-kind": "catalog_inventory", "uk-wsr-run-id": "all-available-parallel-incremental"},
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

run_pair() {
  local radar="$1"
  local year="$2"
  local marker="$STATE_DIR/complete/${radar}-${year}.done"
  local lockdir="$STATE_DIR/locks/${radar}-${year}.lock"
  local pair_log="$STATE_DIR/logs/${radar}-${year}.log"

  if [ -f "$marker" ]; then
    log "skip ${radar} ${year}; already complete"
    return 0
  fi
  if ! mkdir "$lockdir" 2>/dev/null; then
    log "skip ${radar} ${year}; lock already held"
    return 0
  fi
  trap 'rmdir "$lockdir" 2>/dev/null || true' RETURN

  log "worker start ${radar} ${year}"
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
    bash "$SINGLE_RUNNER" >> "$pair_log" 2>&1; then
    touch "$marker"
    log "worker complete ${radar} ${year}"
    (
      flock 9
      log "publishing completed-year catalog after ${radar} ${year}"
      publish_completed_catalog >> "$RUN_LOG" 2>&1
    ) 9>"$STATE_DIR/publish.lock"
  else
    local status=$?
    log "worker failed ${radar} ${year} exit=${status}"
    append_failure "$radar" "$year" "exit=${status}"
  fi
}

discover_pairs | tee -a "$RUN_LOG"
: > "$FAILED_LIST"

started=0
while read -r radar year; do
  [ -n "${radar:-}" ] || continue
  if [ -f "$STATE_DIR/complete/${radar}-${year}.done" ]; then
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
  log "publishing final completed-year catalog"
  publish_completed_catalog >> "$RUN_LOG" 2>&1
) 9>"$STATE_DIR/publish.lock"

log "finished parallel all-available loop; failures=$(wc -l < "$FAILED_LIST" | tr -d ' ')"
