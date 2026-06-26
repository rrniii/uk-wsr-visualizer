#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN=${PYTHON_BIN:-/home/users/rrniii/miniforge3_20250830/envs/nimrod/bin/python}
BIORAD_DIR=${BIORAD_DIR:-/home/users/rrniii/ncas_radar_smf_rrniii/BioDAR/ukmo_biorad}
LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet/post_aggregate_biorad_logs}
RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
POLL_SECONDS=${POLL_SECONDS:-900}
MAX_WAIT_HOURS=${MAX_WAIT_HOURS:-96}
STABLE_POLLS=${STABLE_POLLS:-2}
VALIDATION_RETRIES=${VALIDATION_RETRIES:-6}
VALIDATION_RETRY_SECONDS=${VALIDATION_RETRY_SECONDS:-600}
SQUEUE_TIMEOUT_SECONDS=${SQUEUE_TIMEOUT_SECONDS:-60}

RUN_DIR="${LOG_DIR}/validate_and_vol2birdinput_${RUN_STAMP}"
mkdir -p "$RUN_DIR"
LOG_FILE="${RUN_DIR}/validate_and_vol2birdinput_${RUN_STAMP}.log"
exec >> "$LOG_FILE" 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting post-aggregate validation and vol2birdinput workflow"
echo "script_dir=$SCRIPT_DIR"
echo "biorad_dir=$BIORAD_DIR"
echo "run_dir=$RUN_DIR"
echo "poll_seconds=$POLL_SECONDS"
echo "max_wait_hours=$MAX_WAIT_HOURS"
echo "stable_polls=$STABLE_POLLS"
echo "validation_retries=$VALIDATION_RETRIES"
echo "validation_retry_seconds=$VALIDATION_RETRY_SECONDS"
echo "squeue_timeout_seconds=$SQUEUE_TIMEOUT_SECONDS"
echo

deadline=$(( $(date +%s) + MAX_WAIT_HOURS * 3600 ))
stable_count=0

active_aggregate_slurm_jobs() {
    if ! command -v squeue >/dev/null 2>&1; then
        echo 0
        return
    fi
    squeue_output=$(timeout "$SQUEUE_TIMEOUT_SECONDS" squeue -u "$USER" -h -o '%j' 2>&1)
    squeue_status=$?
    if [ "$squeue_status" -ne 0 ]; then
        echo "WARN: squeue failed with status=$squeue_status: $squeue_output" >&2
        echo -1
        return
    fi
    printf '%s\n' "$squeue_output" | awk '
        $1 ~ /^[0-9]{2}_[0-9]{8}(_r12h)?$/ {
            total++
        }
        END {
            print total + 0
        }
    '
}

active_aggregate_processes() {
    matches=$(
        pgrep -u "$USER" -af 'run_full_rescan_20260423.sh|run_existing_aggregate_repair.sh|submit_repair_candidates(_force)?\.sh|find_aggregate_repair_candidates.py|convert_all_files.sh|run_full_compressed_rewrite.sh|resubmit_failed_then_resume_full|failure_sweep_resubmitter' \
            || true
    )
    if [ -z "$matches" ]; then
        echo 0
    else
        printf '%s\n' "$matches" | grep -v "$$" | wc -l
    fi
}

while true; do
    slurm_jobs=$(active_aggregate_slurm_jobs)
    aggregate_processes=$(active_aggregate_processes)
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] active_aggregate_slurm_jobs=$slurm_jobs active_aggregate_processes=$aggregate_processes"

    if [ "$slurm_jobs" -lt 0 ]; then
        stable_count=0
    elif [ "$slurm_jobs" -eq 0 ] && [ "$aggregate_processes" -eq 0 ]; then
        stable_count=$((stable_count + 1))
        if [ "$stable_count" -ge "$STABLE_POLLS" ]; then
            break
        fi
    else
        stable_count=0
    fi

    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] timed out waiting for aggregate work to finish"
        exit 1
    fi
    sleep "$POLL_SECONDS"
done

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] aggregate work appears idle; validating coverage"

COVERAGE_TSV="${RUN_DIR}/aggregate_raw_coverage_${RUN_STAMP}.tsv"
coverage_ok=0
for attempt in $(seq 1 "$VALIDATION_RETRIES"); do
    if "$PYTHON_BIN" check_aggregate_raw_coverage.py --output "$COVERAGE_TSV"; then
        coverage_ok=1
        break
    fi

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] aggregate coverage validation failed on attempt $attempt/$VALIDATION_RETRIES"
    if [ "$attempt" -lt "$VALIDATION_RETRIES" ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] retrying coverage validation in ${VALIDATION_RETRY_SECONDS}s"
        sleep "$VALIDATION_RETRY_SECONDS"
    fi
done

if [ "$coverage_ok" -ne 1 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] aggregate coverage validation failed; not running vol2birdinput"
    exit 1
fi

REPAIR_TSV="${RUN_DIR}/aggregate_repair_candidates_post_${RUN_STAMP}.tsv"
REPAIR_LOG="${RUN_DIR}/aggregate_repair_candidates_post_${RUN_STAMP}.log"
if ! "$PYTHON_BIN" find_aggregate_repair_candidates.py --output "$REPAIR_TSV" > "$REPAIR_LOG" 2>&1; then
    cat "$REPAIR_LOG"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] aggregate repair candidate scan failed; not running vol2birdinput"
    exit 1
fi
cat "$REPAIR_LOG"

repair_rows=$(awk 'NR > 1 {count++} END {print count + 0}' "$REPAIR_TSV")
repair_files=$(awk -F '\t' 'NR > 1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {print $2 "\t" $3}' "$REPAIR_TSV" | sort -u | wc -l)
echo "post_validation_repair_issue_rows=$repair_rows"
echo "post_validation_repair_files=$repair_files"

if [ "$repair_files" -gt 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] repair candidates remain; not running vol2birdinput"
    exit 1
fi

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] validation passed; running vol2birdinput update"
cd "$BIORAD_DIR"
./submit_biorad_vol2birdinput.sh --update-stale
status=$?

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] vol2birdinput update finished with status=$status"
exit "$status"
