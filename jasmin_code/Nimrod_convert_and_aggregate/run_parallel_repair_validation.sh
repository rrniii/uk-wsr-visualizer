#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN=${PYTHON_BIN:-/home/users/rrniii/miniforge3_20250830/envs/nimrod/bin/python}
BASE=${BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet}
RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
MAX_PARALLEL=${MAX_PARALLEL:-8}
PROGRESS_EVERY=${PROGRESS_EVERY:-500}
OUTPUT=${OUTPUT:-${LOG_DIR}/aggregate_repair_candidates_parallel_${RUN_STAMP}.tsv}
PART_DIR=${PART_DIR:-${LOG_DIR}/aggregate_repair_candidates_parallel_${RUN_STAMP}_parts}

mkdir -p "$LOG_DIR" "$PART_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting parallel aggregate validation"
echo "base=$BASE"
echo "output=$OUTPUT"
echo "part_dir=$PART_DIR"
echo "max_parallel=$MAX_PARALLEL"
echo "progress_every=$PROGRESS_EVERY"

run_radar() {
    local radar_dir=$1
    local radar=$2
    local out="$PART_DIR/${radar}.tsv"
    local log="$PART_DIR/${radar}.log"
    local err="$PART_DIR/${radar}.err"
    local status="$PART_DIR/${radar}.status"

    rm -f "$out" "$log" "$err" "$status"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] start radar=$radar"
    if "$PYTHON_BIN" find_aggregate_repair_candidates.py \
        --base "$radar_dir" \
        --output "$out" \
        --progress-every "$PROGRESS_EVERY" > "$log" 2> "$err"; then
        echo "0" > "$status"
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] done radar=$radar"
    else
        local rc=$?
        echo "$rc" > "$status"
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] failed radar=$radar status=$rc"
    fi
}

for radar_dir in "$BASE"/*; do
    [ -d "$radar_dir" ] || continue
    radar=$(basename "$radar_dir")
    run_radar "$radar_dir" "$radar" &
    while [ "$(jobs -pr | wc -l)" -ge "$MAX_PARALLEL" ]; do
        sleep 5
    done
done

wait

failed=0
for status in "$PART_DIR"/*.status; do
    [ -f "$status" ] || continue
    if [ "$(cat "$status")" != "0" ]; then
        echo "ERROR: failed part $(basename "$status" .status) status=$(cat "$status")" >&2
        failed=1
    fi
done

if [ "$failed" -ne 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] parallel aggregate validation failed"
    exit 1
fi

{
    printf "path\tradar\tdate\tradar_num\tpulse\ttime\tissue\tdetail\n"
    for part in "$PART_DIR"/*.tsv; do
        [ -f "$part" ] || continue
        awk 'NR > 1' "$part"
    done
} > "$OUTPUT"

scanned_files=$(awk -F= '/^scanned_files=/ {sum += $2} END {print sum + 0}' "$PART_DIR"/*.log 2>/dev/null || true)
candidate_files=$(awk -F= '/^candidate_files=/ {sum += $2} END {print sum + 0}' "$PART_DIR"/*.log 2>/dev/null || true)
issue_rows=$(awk 'NR > 1 {count++} END {print count + 0}' "$OUTPUT")

echo "scanned_files=$scanned_files"
echo "candidate_files=$candidate_files"
echo "issue_rows=$issue_rows"
echo "output=$OUTPUT"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] parallel aggregate validation complete"
