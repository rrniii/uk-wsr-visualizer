#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

VALIDATION_PID=${1:?Usage: run_forced_repair_after_validation.sh <validation-pid> <candidate-tsv>}
CANDIDATES=${2:?Usage: run_forced_repair_after_validation.sh <validation-pid> <candidate-tsv>}

POLL_SECONDS=${POLL_SECONDS:-60}
MAX_ACTIVE=${MAX_ACTIVE:-4000}
if ! [[ "$MAX_ACTIVE" =~ ^[0-9]+$ ]] || [ "$MAX_ACTIVE" -lt 1 ]; then
    echo "ERROR: MAX_ACTIVE must be a positive integer" >&2
    exit 1
fi
if [ "$MAX_ACTIVE" -gt 4000 ]; then
    MAX_ACTIVE=4000
fi
FORCE_RUN_STAMP=${FORCE_RUN_STAMP:-forced_after_validation_$(date -u +%Y%m%dT%H%M%SZ)}
LOG_DIR=${LOG_DIR:-$(dirname "$CANDIDATES")}
WATCH_LOG=${WATCH_LOG:-${LOG_DIR}/run_forced_repair_after_validation_${FORCE_RUN_STAMP}.log}
REPAIR_LOG=${REPAIR_LOG:-${LOG_DIR}/nimrod_forced_repair_candidates_${FORCE_RUN_STAMP}.log}
STATUS_DIR=${STATUS_DIR:-${LOG_DIR}/forced_repair_status_${FORCE_RUN_STAMP}}

mkdir -p "$LOG_DIR" "$STATUS_DIR"

{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for validation before forced repair"
    echo "validation_pid=$VALIDATION_PID"
    echo "candidate_file=$CANDIDATES"
    echo "poll_seconds=$POLL_SECONDS"
    echo "max_active=$MAX_ACTIVE"
    echo "force_run_stamp=$FORCE_RUN_STAMP"
    echo "repair_log=$REPAIR_LOG"
    echo "status_dir=$STATUS_DIR"
} | tee -a "$WATCH_LOG"

while ps -p "$VALIDATION_PID" >/dev/null 2>&1; do
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] validation still running" | tee -a "$WATCH_LOG"
    sleep "$POLL_SECONDS"
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] validation process has exited" | tee -a "$WATCH_LOG"

if [ ! -f "$CANDIDATES" ]; then
    echo "ERROR: validation candidate file was not created: $CANDIDATES" | tee -a "$WATCH_LOG"
    exit 1
fi

issue_rows=$(awk 'NR > 1 {count++} END {print count + 0}' "$CANDIDATES")
unique_tasks=$(awk -F '\t' 'NR > 1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {print $2 "\t" $3}' "$CANDIDATES" | sort -u | wc -l)
{
    echo "issue_rows=$issue_rows"
    echo "unique_tasks=$unique_tasks"
} | tee -a "$WATCH_LOG"

if [ "$unique_tasks" -eq 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] no forced repairs needed" | tee -a "$WATCH_LOG"
    exit 0
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting forced repair submissions" | tee -a "$WATCH_LOG"
LOG="$REPAIR_LOG" \
RUN_STAMP="$FORCE_RUN_STAMP" \
STATUS_DIR="$STATUS_DIR" \
MAX_ACTIVE="$MAX_ACTIVE" \
./submit_repair_candidates_force.sh "$CANDIDATES" 2>&1 | tee -a "$WATCH_LOG"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] forced repair submission workflow complete" | tee -a "$WATCH_LOG"
