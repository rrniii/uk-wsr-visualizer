#!/usr/bin/env bash
set -euo pipefail

TOOLKIT_DIR="${TOOLKIT_DIR:-$HOME/uk-wsr-visualizer}"
PYTHON_BIN="${PYTHON_BIN:-/apps/jasmin/jaspy/miniforge_envs/jaspy3.12/mf3-25.3.0-3/bin/python}"
RADAR="${RADAR:-chenies}"
YEAR="${YEAR:-2018}"
RADAR_NUM="${RADAR_NUM:-05}"
AGGREGATE_BASE="${AGGREGATE_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}"
CONFIG="${CONFIG:-configs/object_store.ncas-radar-o.toml}"
DATA_DIR="${DATA_DIR:-data/uk-wsr-visualizer}"
PUBLIC_BASE="${PUBLIC_BASE:-https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public}"
MONTHS="${MONTHS:-}"
DATES="${DATES:-}"
RAW_ONLY="${RAW_ONLY:-0}"

cd "$TOOLKIT_DIR"
export PYTHONPATH="$PWD/.deps:$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

catalog="$DATA_DIR/catalog-${RADAR}-${YEAR}-fast.json"
backfill_dir="$DATA_DIR/object-store/backfill/${RADAR}-${YEAR}"
sha256_cache="$backfill_dir/sha256-cache.json"
mkdir -p "$backfill_dir"

verified_manifest_complete() {
  "$PYTHON_BIN" -B - "$1" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
objects = payload.get("objects", [])
raise SystemExit(0 if objects and all(obj.get("status") == "verified" for obj in objects) else 1)
PY
}

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) building fast catalog ${catalog}"
"$PYTHON_BIN" -B -m uk_wsr_visualizer.cli catalog build \
  --aggregate-base "$AGGREGATE_BASE" \
  --output "$catalog" \
  --radar "$RADAR" \
  --year "$YEAR" \
  --metadata-mode fast \
  --object-store-base "$PUBLIC_BASE"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) splitting catalog by day"
"$PYTHON_BIN" -B - "$catalog" "$backfill_dir" "$MONTHS" "$DATES" <<'PY'
import json
import sys
from collections import defaultdict
from pathlib import Path

catalog_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
requested = {m.strip() for m in sys.argv[3].split(",") if m.strip()}
requested_dates = {d.strip().replace("-", "") for d in sys.argv[4].split(",") if d.strip()}
payload = json.loads(catalog_path.read_text(encoding="utf-8"))
by_day = defaultdict(list)
for item in payload["items"]:
    month = item["date"][:6]
    date = item["date"]
    if requested and month not in requested:
        continue
    if requested_dates and date not in requested_dates:
        continue
    by_day[date].append(item)
for date, items in sorted(by_day.items()):
    path = out_dir / f"catalog-{date}.json"
    path.write_text(json.dumps({"version": payload.get("version", 1), "items": items}, indent=2, sort_keys=True), encoding="utf-8")
    byte_count = sum(item["file_size"] for item in items)
    print(f"{date} items={len(items)} bytes={byte_count}")
PY

for batch_catalog in "$backfill_dir"/catalog-"$YEAR"????.json; do
  [ -e "$batch_catalog" ] || continue
  batch="$(basename "$batch_catalog" .json | sed 's/^catalog-//')"
  plan="$backfill_dir/plan-${batch}.json"
  raw_plan="$backfill_dir/plan-${batch}-aggregate-only.json"
  synced="$backfill_dir/synced-${batch}.json"
  verified="$backfill_dir/verified-${batch}.json"
  run_id="${RADAR}-${batch}-raw-$(date -u +%Y%m%dT%H%M%SZ)"

  if [ -f "$verified" ] && verified_manifest_complete "$verified"; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skipping ${batch}; verified manifest already complete"
    continue
  fi

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) planning raw aggregate upload for ${batch}"
  "$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store plan \
    --config "$CONFIG" \
    --catalog "$batch_catalog" \
    --staging-dir "$backfill_dir/staging-${batch}" \
    --preview-dir "$backfill_dir/empty-previews" \
    --tile-dir "$backfill_dir/empty-tiles" \
    --validation-dir "$backfill_dir/empty-validation" \
    --run-id "$run_id" \
    --sha256-cache "$sha256_cache" \
    --output "$plan"

  "$PYTHON_BIN" -B - "$plan" "$raw_plan" <<'PY'
import sys
from pathlib import Path
from uk_wsr_visualizer.object_store_manifest import load_plan, write_plan

plan = load_plan(Path(sys.argv[1]))
plan.objects = [obj for obj in plan.objects if obj.kind == "aggregate_h5"]
write_plan(Path(sys.argv[2]), plan)
print(f"aggregate_objects={len(plan.objects)} byte_count={sum(obj.size for obj in plan.objects)}")
PY

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) syncing ${batch}"
  "$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store sync \
    --execute \
    --skip-existing \
    --config "$CONFIG" \
    --plan "$raw_plan" \
    --manifest "$synced"

  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) verifying ${batch}"
  "$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store verify \
    --execute \
    --config "$CONFIG" \
    --manifest "$synced" \
    --output "$verified"
done

if [ "$RAW_ONLY" = "1" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) complete ${RADAR} ${YEAR} raw aggregate backfill; RAW_ONLY=1 so skipping cumulative metadata publish"
  exit 0
fi

full_plan="$backfill_dir/plan-${RADAR}-${YEAR}-full.json"
full_synced="$backfill_dir/synced-${RADAR}-${YEAR}-full.json"
full_verified="$backfill_dir/verified-${RADAR}-${YEAR}-full.json"
full_nonaggregate_plan="$backfill_dir/plan-${RADAR}-${YEAR}-nonaggregate.json"
full_nonaggregate_synced="$backfill_dir/synced-${RADAR}-${YEAR}-nonaggregate.json"
full_nonaggregate_verified="$backfill_dir/verified-${RADAR}-${YEAR}-nonaggregate.json"
published="$backfill_dir/published-${RADAR}-${YEAR}-full.json"
run_id="${RADAR}-${YEAR}-full-$(date -u +%Y%m%dT%H%M%SZ)"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) planning cumulative full-year release"
"$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store plan \
  --config "$CONFIG" \
  --catalog "$catalog" \
  --staging-dir "$backfill_dir/staging-full" \
  --preview-dir "$DATA_DIR/previews" \
  --tile-dir "$DATA_DIR/tiles" \
  --validation-dir "$DATA_DIR/validation/wct" \
  --run-id "$run_id" \
  --sha256-cache "$sha256_cache" \
  --output "$full_plan"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) extracting non-aggregate cumulative release objects"
"$PYTHON_BIN" -B - "$full_plan" "$full_nonaggregate_plan" <<'PY'
import sys
from pathlib import Path
from uk_wsr_visualizer.object_store_manifest import load_plan, write_plan

plan = load_plan(Path(sys.argv[1]))
plan.objects = [obj for obj in plan.objects if obj.kind != "aggregate_h5"]
write_plan(Path(sys.argv[2]), plan)
print(f"nonaggregate_objects={len(plan.objects)} byte_count={sum(obj.size for obj in plan.objects)}")
PY

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) syncing non-aggregate cumulative release objects with skip-existing"
"$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store sync \
  --execute \
  --skip-existing \
  --config "$CONFIG" \
  --plan "$full_nonaggregate_plan" \
  --manifest "$full_nonaggregate_synced"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) verifying non-aggregate cumulative release objects"
"$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store verify \
  --execute \
  --config "$CONFIG" \
  --manifest "$full_nonaggregate_synced" \
  --output "$full_nonaggregate_verified"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) merging daily raw verifications into cumulative full-year release"
"$PYTHON_BIN" -B - "$full_plan" "$full_nonaggregate_synced" "$full_nonaggregate_verified" "$full_synced" "$full_verified" "$backfill_dir" "$YEAR" <<'PY'
import copy
import json
import sys
from pathlib import Path
from uk_wsr_visualizer.object_store_manifest import load_plan, write_plan

full = load_plan(Path(sys.argv[1]))
nonaggregate_synced = load_plan(Path(sys.argv[2]))
nonaggregate_verified = load_plan(Path(sys.argv[3]))
synced_output = Path(sys.argv[4])
verified_output = Path(sys.argv[5])
backfill_dir = Path(sys.argv[6])
year = sys.argv[7]

daily_verified = {}
for path in sorted(backfill_dir.glob(f"verified-{year}????.json")):
    plan = load_plan(path)
    for obj in plan.objects:
        if obj.kind == "aggregate_h5" and obj.status == "verified":
            daily_verified[obj.key] = obj

nonaggregate_synced_by_key = {obj.key: obj for obj in nonaggregate_synced.objects}
nonaggregate_verified_by_key = {obj.key: obj for obj in nonaggregate_verified.objects}

def copy_state(target, source):
    target.status = source.status
    target.message = source.message
    target.uploaded_at = source.uploaded_at
    target.verified_at = source.verified_at

synced = copy.deepcopy(full)
verified = copy.deepcopy(full)
missing = []

for obj in synced.objects:
    if obj.kind == "aggregate_h5":
        source = daily_verified.get(obj.key)
        if source and source.size == obj.size and source.sha256 == obj.sha256:
            obj.status = "skipped_existing"
            obj.message = "raw aggregate covered by daily verified manifest"
            obj.uploaded_at = source.uploaded_at
            obj.verified_at = source.verified_at
        else:
            missing.append(obj.key)
    else:
        source = nonaggregate_synced_by_key.get(obj.key)
        if source:
            copy_state(obj, source)
        else:
            missing.append(obj.key)

for obj in verified.objects:
    if obj.kind == "aggregate_h5":
        source = daily_verified.get(obj.key)
        if source and source.size == obj.size and source.sha256 == obj.sha256:
            obj.status = "verified"
            obj.message = ""
            obj.uploaded_at = source.uploaded_at
            obj.verified_at = source.verified_at
        else:
            missing.append(obj.key)
    else:
        source = nonaggregate_verified_by_key.get(obj.key)
        if source:
            copy_state(obj, source)
        else:
            missing.append(obj.key)

if missing:
    print(json.dumps({"missing_or_mismatched_objects": sorted(set(missing))[:20], "count": len(set(missing))}, indent=2))
    raise SystemExit(1)

unverified = [obj.key for obj in verified.objects if obj.status != "verified"]
if unverified:
    print(json.dumps({"unverified_objects": unverified[:20], "count": len(unverified)}, indent=2))
    raise SystemExit(1)

write_plan(synced_output, synced)
write_plan(verified_output, verified)
print(json.dumps({"synced": synced.summary(), "verified": verified.summary()}, indent=2, sort_keys=True))
PY

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) publishing cumulative full-year release"
"$PYTHON_BIN" -B -m uk_wsr_visualizer.cli object-store publish \
  --execute \
  --config "$CONFIG" \
  --manifest "$full_verified" \
  --output "$published"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) complete ${RADAR} ${YEAR} backfill"
