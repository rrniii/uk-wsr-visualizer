#!/usr/bin/env bash
set -euo pipefail

REPO=${REPO:-/home/users/rrniii/uk-wsr-visualizer}
NIMROD_DIR=${NIMROD_DIR:-/home/users/rrniii/bin/Nimrod_convert_and_aggregate}
RUN_STAMP=${RUN_STAMP:-full_avocet_rebuild_$(date -u +%Y%m%dT%H%M%SZ)}
LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet/full_rebuild_logs}
LOCK_FILE=${LOCK_FILE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/avocet_full_rebuild.lock}
MAX_ACTIVE=${MAX_ACTIVE:-2500}
MIN_FREE_GB=${MIN_FREE_GB:-5000}
PVOL_UPLOAD_WORKERS=${PVOL_UPLOAD_WORKERS:-96}
PVOL_UPLOAD_HOST=${PVOL_UPLOAD_HOST:-}
PVOL_UPLOAD_RUN_BASE=${PVOL_UPLOAD_RUN_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/pvol-fast-upload}
BIORAD_JOB_REGEX=${BIORAD_JOB_REGEX:-biorad|vol2bird|vol2birdinput|pvol}
BIORAD_POLL_SECONDS=${BIORAD_POLL_SECONDS:-300}
BIORAD_MAX_WAIT_HOURS=${BIORAD_MAX_WAIT_HOURS:-168}

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"
LOG_FILE="${LOG_DIR}/${RUN_STAMP}.log"
LATEST_LOG="${LOG_DIR}/full_avocet_rebuild_latest.log"
ln -sfn "$LOG_FILE" "$LATEST_LOG"
exec >> "$LOG_FILE" 2>&1

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
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
    local current_host
    current_host=$(hostname -f 2>/dev/null || hostname)
    log "launching full pvol upload workers=${PVOL_UPLOAD_WORKERS} host=${PVOL_UPLOAD_HOST:-local}"
    if [ -z "$PVOL_UPLOAD_HOST" ] || [ "$current_host" = "$PVOL_UPLOAD_HOST" ] || [ "$(hostname 2>/dev/null)" = "${PVOL_UPLOAD_HOST%%.*}" ]; then
        cd "$REPO"
        WORKERS="$PVOL_UPLOAD_WORKERS" RUN_BASE="$PVOL_UPLOAD_RUN_BASE" bash tools/jasmin_pvol_upload/launch_fast_pvol_upload.sh
    else
        ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$PVOL_UPLOAD_HOST" \
            "cd '$REPO' && WORKERS='$PVOL_UPLOAD_WORKERS' RUN_BASE='$PVOL_UPLOAD_RUN_BASE' bash tools/jasmin_pvol_upload/launch_fast_pvol_upload.sh"
    fi
}

log "starting full Avocet rebuild"
log "repo=$REPO"
log "nimrod_dir=$NIMROD_DIR"
log "max_active=$MAX_ACTIVE"
log "min_free_gb=$MIN_FREE_GB"
log "log_file=$LOG_FILE"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another full Avocet rebuild holds the lock; skipping"
    exit 0
fi

log "running full compressed aggregate rewrite"
MAX_ACTIVE="$MAX_ACTIVE" MIN_FREE_GB="$MIN_FREE_GB" H5_COMPRESS=1 H5_GZIP_LEVEL=4 H5_VERIFY=1 \
    RUN_STAMP="$RUN_STAMP" bash "$NIMROD_DIR/run_full_compressed_rewrite.sh"

log "running aggregate validation and vol2birdinput update"
bash "$NIMROD_DIR/run_validate_and_vol2birdinput_after_aggregates.sh"

log "waiting for vol2birdinput jobs before pvol upload"
wait_for_biorad_idle

launch_pvol_upload
log "full Avocet rebuild finished"
