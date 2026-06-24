#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet/daily_update_logs}
LOCK_FILE=${LOCK_FILE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_daily_update.lock}
BLOCK_FILE=${BLOCK_FILE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_daily_update.block}
BLOCK_MAX_AGE_SECONDS=${BLOCK_MAX_AGE_SECONDS:-64800}
MAX_ACTIVE=${MAX_ACTIVE:-0}

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"

RUN_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG_FILE="${LOG_DIR}/nimrod_daily_update_${RUN_STAMP}.log"
LATEST_LOG="${LOG_DIR}/nimrod_daily_update_latest.log"
ln -sfn "$LOG_FILE" "$LATEST_LOG"

exec >> "$LOG_FILE" 2>&1

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting daily Nimrod aggregate update"
echo "host=$(hostname -f 2>/dev/null || hostname)"
echo "script_dir=$SCRIPT_DIR"
echo "env=$ENV"
echo "log_file=$LOG_FILE"
echo "lock_file=$LOCK_FILE"
echo "block_file=$BLOCK_FILE"
echo

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] another daily update holds the lock; skipping"
    exit 0
fi

if [ -f "$BLOCK_FILE" ]; then
    block_mtime=$(stat -c %Y "$BLOCK_FILE" 2>/dev/null || echo 0)
    now_epoch=$(date +%s)
    block_age=$((now_epoch - block_mtime))

    echo "daily_update_block_age_seconds=$block_age"
    echo "daily_update_block_max_age_seconds=$BLOCK_MAX_AGE_SECONDS"
    sed 's/^/daily_update_block: /' "$BLOCK_FILE" || true

    if [ "$block_age" -le "$BLOCK_MAX_AGE_SECONDS" ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] daily update block is active; skipping"
        exit 0
    fi

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] daily update block is stale; ignoring"
fi

active_jobs=0
if command -v squeue >/dev/null 2>&1; then
    active_jobs=$(
        squeue -u "$USER" -h -o '%j' | awk '
            $1 ~ /^[0-9]{2}_[0-9]{8}(_r12h)?$/ {
                total++
            }
            END {
                print total + 0
            }
        '
    )
fi

echo "active_nimrod_slurm_jobs=$active_jobs"
if [ "$active_jobs" -gt "$MAX_ACTIVE" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] active Nimrod conversion jobs are still running; skipping"
    exit 0
fi

active_processes=0
if command -v pgrep >/dev/null 2>&1; then
    process_matches=$(
        pgrep -u "$USER" -af 'run_full_rescan_20260423.sh|run_existing_aggregate_repair.sh|submit_repair_candidates.sh|find_aggregate_repair_candidates.py|convert_all_files.sh' || true
    )
    if [ -n "$process_matches" ]; then
        active_processes=$(
            printf '%s\n' "$process_matches" | awk -v self="$$" '
                $1 != self {
                    total++
                }
                END {
                    print total + 0
                }
            '
        )
    fi
fi

echo "active_nimrod_processes=$active_processes"
if [ "$active_processes" -gt "$MAX_ACTIVE" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] active Nimrod conversion or repair processes are still running; skipping"
    exit 0
fi

export H5_VERIFY="${H5_VERIFY:-1}"
export SLURM_TIME_LIMIT_OVERRIDE="${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}"
export OUT_BASE_OVERRIDE="${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}"
export SCRATCH_BASE_OVERRIDE="${SCRATCH_BASE_OVERRIDE:-/work/scratch-pw5/rrniii/ukmo-nimrod/tmp_raw_radar}"

echo "h5_verify=$H5_VERIFY"
echo "slurm_time_limit=$SLURM_TIME_LIMIT_OVERRIDE"
echo "out_base=$OUT_BASE_OVERRIDE"
echo "scratch_base=$SCRATCH_BASE_OVERRIDE"
echo

# No explicit dates: convert_all_files.sh checks each radar from its latest
# completed output year through the current day and submits missing/corrupt days.
./convert_all_files.sh all "$ENV"
status=$?

echo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] daily Nimrod aggregate update finished with status=$status"
exit "$status"
