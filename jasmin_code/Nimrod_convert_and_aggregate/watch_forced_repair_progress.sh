#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

CANDIDATES=${1:?Usage: watch_forced_repair_progress.sh <candidate-tsv>}

RUN_DIR=${RUN_DIR:-$(dirname "$CANDIDATES")}
RUN_STAMP=${RUN_STAMP:-forced_after_lotus_retry2_20260623T1853Z}
REPAIR_LOG=${REPAIR_LOG:-${RUN_DIR}/nimrod_forced_repair_candidates_${RUN_STAMP}.log}
STATUS_DIR=${STATUS_DIR:-${RUN_DIR}/forced_repair_status_${RUN_STAMP}}
SCRATCH_BASE=${SCRATCH_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/tmp_raw_radar_repair}
WATCH_LOG=${WATCH_LOG:-${RUN_DIR}/watch_forced_repair_progress_${RUN_STAMP}.log}
POLL_SECONDS=${POLL_SECONDS:-300}
MAX_ACTIVE=${MAX_ACTIVE:-4000}
SUBMIT_MARKER=${SUBMIT_MARKER:-${RUN_DIR}/watch_forced_repair_progress_${RUN_STAMP}.submitted_remaining}

RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')

radar_for_num() {
    local rnum=$1
    local i
    for i in "${!RADAR_NUMS[@]}"; do
        if [ "${RADAR_NUMS[$i]}" = "$rnum" ]; then
            printf '%s\n' "${RADARS[$i]}"
            return 0
        fi
    done
    return 1
}

active_jobs() {
    squeue -u "$USER" -h -o '%j' | grep -Ec '^[0-9]{2}_[0-9]{8}$' || true
}

submitter_running() {
    pgrep -u "$USER" -af "submit_repair_candidates_force.sh .*$(basename "$CANDIDATES")" >/dev/null 2>&1
}

status_count() {
    local suffix=$1
    find "$STATUS_DIR" -type f -name "*.${suffix}" 2>/dev/null | wc -l
}

progressing_running_logs() {
    local count=0
    local job rnum date radar out
    while IFS= read -r job; do
        rnum=${job%%_*}
        date=${job#*_}
        radar=$(radar_for_num "$rnum" 2>/dev/null || true)
        [ -n "$radar" ] || continue
        out="${SCRATCH_BASE%/}/${radar}/${date}/forced_slurm_outs_${RUN_STAMP}/convert.out"
        if [ -f "$out" ] && grep -Eq '^(target=|input_sp=|tmp_folder=|\[[0-9TZ:-]+\] completed forced repair)' "$out"; then
            count=$((count + 1))
        fi
    done < <(squeue -u "$USER" -h -o '%j' | grep -E '^[0-9]{2}_[0-9]{8}$' || true)
    printf '%s\n' "$count"
}

mkdir -p "$RUN_DIR" "$STATUS_DIR"

baseline_done=$(status_count done)
baseline_failed=$(status_count failed)
{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting forced repair progress watcher"
    echo "candidate_file=$CANDIDATES"
    echo "run_stamp=$RUN_STAMP"
    echo "repair_log=$REPAIR_LOG"
    echo "status_dir=$STATUS_DIR"
    echo "poll_seconds=$POLL_SECONDS"
    echo "max_active=$MAX_ACTIVE"
    echo "baseline_done=$baseline_done"
    echo "baseline_failed=$baseline_failed"
} >> "$WATCH_LOG"

while true; do
    active=$(active_jobs)
    done_count=$(status_count done)
    failed_count=$(status_count failed)
    progressing=$(progressing_running_logs)
    df_line=$(df -h "$RUN_DIR" | tail -1)

    {
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] active_jobs=$active done=$done_count failed=$failed_count progressing_logs=$progressing df=${df_line}"
    } >> "$WATCH_LOG"

    if [ ! -f "$SUBMIT_MARKER" ] && [ "$active" -lt "$MAX_ACTIVE" ]; then
        if [ "$progressing" -gt 0 ] || [ "$done_count" -gt "$baseline_done" ]; then
            if ! submitter_running; then
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] progress detected; starting remaining forced repair submitter" >> "$WATCH_LOG"
                {
                    echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
                    echo "reason=progress_detected"
                    echo "active_jobs=$active"
                    echo "done_count=$done_count"
                    echo "progressing_logs=$progressing"
                } > "$SUBMIT_MARKER"
                nohup env \
                    RUN_STAMP="$RUN_STAMP" \
                    LOG="$REPAIR_LOG" \
                    STATUS_DIR="$STATUS_DIR" \
                    RESUME_LOGS="$REPAIR_LOG" \
                    MAX_ACTIVE="$MAX_ACTIVE" \
                    "$SCRIPT_DIR/submit_repair_candidates_force.sh" "$CANDIDATES" \
                    >> "${RUN_DIR}/submit_remaining_after_progress_${RUN_STAMP}.log" 2>&1 &
            fi
        fi
    fi

    if [ "$active" -eq 0 ] && submitter_running; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] no active jobs but submitter still running" >> "$WATCH_LOG"
    fi

    sleep "$POLL_SECONDS"
done
