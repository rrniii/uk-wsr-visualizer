#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

RUN_DIR=${1:?Usage: run_validate_after_direct_repair.sh <direct-repair-run-dir>}

PYTHON_BIN=${PYTHON_BIN:-/home/users/rrniii/miniforge3_20250830/envs/nimrod/bin/python}
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_WAIT_HOURS=${MAX_WAIT_HOURS:-96}
VALIDATION_RETRIES=${VALIDATION_RETRIES:-6}
VALIDATION_RETRY_SECONDS=${VALIDATION_RETRY_SECONDS:-600}
DIRECT_PROCESS_PATTERN=${DIRECT_PROCESS_PATTERN:-run_direct_repair_candidates.sh}

TASKS="${RUN_DIR}/tasks.tsv"
STATUS_DIR="${RUN_DIR}/status"
LOG_FILE="${RUN_DIR}/validate_after_direct_repair.log"

exec >> "$LOG_FILE" 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting validation-after-direct-repair monitor"
echo "run_dir=$RUN_DIR"
echo "tasks=$TASKS"
echo "status_dir=$STATUS_DIR"
echo "python_bin=$PYTHON_BIN"
echo "poll_seconds=$POLL_SECONDS"
echo "max_wait_hours=$MAX_WAIT_HOURS"
echo

if [ ! -f "$TASKS" ]; then
    echo "ERROR: tasks file not found: $TASKS"
    exit 1
fi
if [ ! -d "$STATUS_DIR" ]; then
    echo "ERROR: status directory not found: $STATUS_DIR"
    exit 1
fi
if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: missing python: $PYTHON_BIN"
    exit 1
fi

task_count=$(awk 'NF > 0 {count++} END {print count + 0}' "$TASKS")
deadline=$(( $(date +%s) + MAX_WAIT_HOURS * 3600 ))

while true; do
    done_count=$(find "$STATUS_DIR" -type f -name '*.done' 2>/dev/null | wc -l)
    failed_count=$(
        find "$STATUS_DIR" -type f -name '*.failed' 2>/dev/null |
            while IFS= read -r failed_file; do
                done_file="${failed_file%.failed}.done"
                if [ ! -f "$done_file" ]; then
                    printf '%s\n' "$failed_file"
                fi
            done |
            wc -l
    )
    skipped_count=$(
        find "$STATUS_DIR" -type f -name '*.skipped' 2>/dev/null |
            while IFS= read -r skipped_file; do
                done_file="${skipped_file%.skipped}.done"
                if [ ! -f "$done_file" ]; then
                    printf '%s\n' "$skipped_file"
                fi
            done |
            wc -l
    )
    status_count=$((done_count + failed_count + skipped_count))
    active_direct=$(pgrep -u "$USER" -af "$DIRECT_PROCESS_PATTERN" | grep -v "$$" | wc -l || true)

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] task_count=$task_count done=$done_count failed=$failed_count skipped=$skipped_count active_direct_processes=$active_direct"

    if [ "$active_direct" -eq 0 ]; then
        if [ "$failed_count" -gt 0 ]; then
            echo "ERROR: direct repair has unresolved failed tasks; not validating"
            exit 1
        fi
        if [ "$status_count" -lt "$task_count" ]; then
            echo "ERROR: direct repair process ended before all tasks reported status"
            exit 1
        fi
        if [ "$skipped_count" -gt 0 ]; then
            echo "ERROR: direct repair skipped tasks; not validating"
            exit 1
        fi
        break
    fi

    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "ERROR: timed out waiting for direct repair to finish"
        exit 1
    fi
    sleep "$POLL_SECONDS"
done

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] direct repair complete; validating aggregate/raw coverage"

COVERAGE_TSV="${RUN_DIR}/aggregate_raw_coverage_after_direct_repair.tsv"
coverage_ok=0
for attempt in $(seq 1 "$VALIDATION_RETRIES"); do
    if "$PYTHON_BIN" check_aggregate_raw_coverage.py --output "$COVERAGE_TSV"; then
        coverage_ok=1
        break
    fi

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] aggregate coverage validation failed on attempt $attempt/$VALIDATION_RETRIES"
    if [ "$attempt" -lt "$VALIDATION_RETRIES" ]; then
        sleep "$VALIDATION_RETRY_SECONDS"
    fi
done

if [ "$coverage_ok" -ne 1 ]; then
    echo "ERROR: aggregate coverage validation failed"
    exit 1
fi

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] running post-repair candidate scan"
REPAIR_TSV="${RUN_DIR}/aggregate_repair_candidates_after_direct_repair.tsv"
REPAIR_LOG="${RUN_DIR}/aggregate_repair_candidates_after_direct_repair.log"
if ! "$PYTHON_BIN" find_aggregate_repair_candidates.py --output "$REPAIR_TSV" > "$REPAIR_LOG" 2>&1; then
    cat "$REPAIR_LOG"
    echo "ERROR: post-repair candidate scan failed"
    exit 1
fi
cat "$REPAIR_LOG"

repair_rows=$(awk 'NR > 1 {count++} END {print count + 0}' "$REPAIR_TSV")
repair_files=$(awk -F '\t' 'NR > 1 && $2 != "" && $3 ~ /^[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]$/ {print $2 "\t" $3}' "$REPAIR_TSV" | sort -u | wc -l)
echo "post_validation_repair_issue_rows=$repair_rows"
echo "post_validation_repair_files=$repair_files"

if [ "$repair_files" -gt 0 ]; then
    echo "ERROR: repair candidates remain after direct repair"
    exit 1
fi

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] direct repair validation passed"
