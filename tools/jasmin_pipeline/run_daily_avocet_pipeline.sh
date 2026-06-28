#!/usr/bin/env bash
set -euo pipefail

REPO=${REPO:-/home/users/rrniii/uk-wsr-visualizer}
NIMROD_DIR=${NIMROD_DIR:-/home/users/rrniii/bin/Nimrod_convert_and_aggregate}
LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet/daily_update_logs}
LOCK_FILE=${LOCK_FILE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/avocet_daily_pipeline.lock}
RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
PVOL_UPLOAD_LOOKBACK_DAYS=${PVOL_UPLOAD_LOOKBACK_DAYS:-14}
PVOL_UPLOAD_WORKERS=${PVOL_UPLOAD_WORKERS:-32}
PVOL_UPLOAD_HOST=${PVOL_UPLOAD_HOST:-}
PVOL_UPLOAD_RUN_BASE=${PVOL_UPLOAD_RUN_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/pvol-fast-upload}
RUN_INTEGRITY_CHECKERS=${RUN_INTEGRITY_CHECKERS:-1}
INTEGRITY_AGG_WORKERS=${INTEGRITY_AGG_WORKERS:-4}
INTEGRITY_PVOL_WORKERS=${INTEGRITY_PVOL_WORKERS:-4}
BIORAD_JOB_REGEX=${BIORAD_JOB_REGEX:-biorad|vol2bird|vol2birdinput|pvol}
BIORAD_POLL_SECONDS=${BIORAD_POLL_SECONDS:-300}
BIORAD_MAX_WAIT_HOURS=${BIORAD_MAX_WAIT_HOURS:-48}

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"
LOG_FILE="${LOG_DIR}/avocet_daily_pipeline_${RUN_STAMP}.log"
LATEST_LOG="${LOG_DIR}/avocet_daily_pipeline_latest.log"
ln -sfn "$LOG_FILE" "$LATEST_LOG"
exec >> "$LOG_FILE" 2>&1

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

date_days_ago() {
    local days=$1
    if date -u -d "${days} days ago" +%Y%m%d >/dev/null 2>&1; then
        date -u -d "${days} days ago" +%Y%m%d
    else
        python3 - "$days" <<'PY'
from datetime import datetime, timedelta, timezone
import sys
print((datetime.now(timezone.utc) - timedelta(days=int(sys.argv[1]))).strftime("%Y%m%d"))
PY
    fi
}

active_biorad_jobs() {
    if ! command -v squeue >/dev/null 2>&1; then
        echo 0
        return
    fi
    squeue -u "$USER" -h -o '%j' | awk -v pattern="$BIORAD_JOB_REGEX" '
        BEGIN { count = 0 }
        tolower($0) ~ pattern { count++ }
        END { print count + 0 }
    '
}

wait_for_biorad_idle() {
    local deadline=$(( $(date +%s) + BIORAD_MAX_WAIT_HOURS * 3600 ))
    while true; do
        local active
        active=$(active_biorad_jobs)
        log "active_biorad_jobs=${active}"
        if [ "$active" -eq 0 ]; then
            return 0
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            log "timed out waiting for biorad jobs to finish"
            return 1
        fi
        sleep "$BIORAD_POLL_SECONDS"
    done
}

launch_pvol_upload() {
    local start_date=$1
    local end_date=$2
    local current_host
    current_host=$(hostname -f 2>/dev/null || hostname)
    log "launching pvol upload start_date=${start_date} end_date=${end_date} workers=${PVOL_UPLOAD_WORKERS} host=${PVOL_UPLOAD_HOST:-local}"
    if [ -z "$PVOL_UPLOAD_HOST" ] || [ "$current_host" = "$PVOL_UPLOAD_HOST" ] || [ "$(hostname 2>/dev/null)" = "${PVOL_UPLOAD_HOST%%.*}" ]; then
        cd "$REPO"
        START_DATE="$start_date" END_DATE="$end_date" WORKERS="$PVOL_UPLOAD_WORKERS" RUN_BASE="$PVOL_UPLOAD_RUN_BASE" \
            bash tools/jasmin_pvol_upload/launch_fast_pvol_upload.sh
    else
        ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$PVOL_UPLOAD_HOST" \
            "cd '$REPO' && START_DATE='$start_date' END_DATE='$end_date' WORKERS='$PVOL_UPLOAD_WORKERS' RUN_BASE='$PVOL_UPLOAD_RUN_BASE' bash tools/jasmin_pvol_upload/launch_fast_pvol_upload.sh"
    fi
}

log "starting Avocet daily pipeline"
log "repo=$REPO"
log "nimrod_dir=$NIMROD_DIR"
log "log_file=$LOG_FILE"
log "lock_file=$LOCK_FILE"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another Avocet daily pipeline holds the lock; skipping"
    exit 0
fi

start_date=${PVOL_UPLOAD_START_DATE:-$(date_days_ago "$PVOL_UPLOAD_LOOKBACK_DAYS")}
end_date=${PVOL_UPLOAD_END_DATE:-$(date -u +%Y%m%d)}
log "pvol_upload_window=${start_date}:${end_date}"

log "running daily aggregate update"
bash "$NIMROD_DIR/run_daily_update.sh"

log "running aggregate validation and vol2birdinput update"
bash "$NIMROD_DIR/run_validate_and_vol2birdinput_after_aggregates.sh"

log "waiting for vol2birdinput jobs before pvol upload"
wait_for_biorad_idle

launch_pvol_upload "$start_date" "$end_date"
if [ "$RUN_INTEGRITY_CHECKERS" = "1" ]; then
    log "launching detached integrity checkers"
    cd "$REPO"
    RUN_STAMP="daily_integrity_${RUN_STAMP}" \
    AGG_WORKERS="$INTEGRITY_AGG_WORKERS" \
    PVOL_WORKERS="$INTEGRITY_PVOL_WORKERS" \
    WAIT_FOR_AGGREGATE_IDLE=1 \
    WAIT_FOR_BIORAD_IDLE=1 \
    WAIT_FOR_PVOL_UPLOAD=1 \
        bash tools/jasmin_pipeline/launch_integrity_checkers.sh
fi
log "Avocet daily pipeline finished"
