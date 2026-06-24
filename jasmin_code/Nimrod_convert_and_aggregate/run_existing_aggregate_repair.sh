#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN=${PYTHON_BIN:-/home/users/rrniii/miniforge3_20250830/envs/nimrod/bin/python}
RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet}
CANDIDATES=${CANDIDATES:-${LOG_DIR}/aggregate_repair_candidates_${RUN_STAMP}.tsv}
SCAN_LOG=${SCAN_LOG:-${LOG_DIR}/aggregate_repair_candidates_${RUN_STAMP}.log}
REPAIR_LOG=${REPAIR_LOG:-${LOG_DIR}/nimrod_repair_candidates_${RUN_STAMP}.log}
DAILY_BLOCK_FILE=${DAILY_BLOCK_FILE:-${LOG_DIR}/nimrod_daily_update.block}
MAX_ACTIVE=${MAX_ACTIVE:-4000}
if ! [[ "$MAX_ACTIVE" =~ ^[0-9]+$ ]] || [ "$MAX_ACTIVE" -lt 1 ]; then
    echo "ERROR: MAX_ACTIVE must be a positive integer" >&2
    exit 1
fi
if [ "$MAX_ACTIVE" -gt 4000 ]; then
    MAX_ACTIVE=4000
fi

mkdir -p "$LOG_DIR"

cleanup_daily_block() {
    rm -f "$DAILY_BLOCK_FILE"
}

{
    echo "reason=existing aggregate repair workflow"
    echo "run_stamp=$RUN_STAMP"
    echo "host=$(hostname -f 2>/dev/null || hostname)"
    echo "pid=$$"
    echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$DAILY_BLOCK_FILE"
trap cleanup_daily_block EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scanning existing aggregates"
echo "candidate_file=$CANDIDATES"
echo "scan_log=$SCAN_LOG"
echo "repair_log=$REPAIR_LOG"
echo "daily_block_file=$DAILY_BLOCK_FILE"
echo

"$PYTHON_BIN" find_aggregate_repair_candidates.py --output "$CANDIDATES" > "$SCAN_LOG" 2>&1
cat "$SCAN_LOG"

candidate_rows=$(awk 'NR > 1 {print}' "$CANDIDATES" | wc -l)
repair_files=$(awk -F '\t' 'NR > 1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {print $2 "\t" $3}' "$CANDIDATES" | sort -u | wc -l)

echo
echo "candidate_issue_rows=$candidate_rows"
echo "unique_radar_dates_to_repair=$repair_files"

if [ "$repair_files" -eq 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] no existing aggregate repairs needed"
    exit 0
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submitting forced repairs"
LOG="$REPAIR_LOG" MAX_ACTIVE="$MAX_ACTIVE" ./submit_repair_candidates.sh "$CANDIDATES"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] repair submission workflow complete"
