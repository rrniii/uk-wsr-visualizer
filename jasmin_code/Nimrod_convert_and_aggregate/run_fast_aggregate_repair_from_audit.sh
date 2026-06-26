#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

AUDIT_RUN_DIR=${1:?Usage: run_fast_aggregate_repair_from_audit.sh <audit-run-dir>}
TRIAGE_DIR=${TRIAGE_DIR:-${AUDIT_RUN_DIR}/failure_triage_20260625T055334Z}
TRIAGED=${TRIAGED:-${TRIAGE_DIR}/triaged_rebuild_candidates.tsv}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
RUN_STAMP=${RUN_STAMP:-fast_repair_$(date -u +%Y%m%dT%H%M%SZ)}
RUN_DIR=${RUN_DIR:-${AUDIT_RUN_DIR}/${RUN_STAMP}}
MAX_ACTIVE=${MAX_ACTIVE:-500}
CANARY_WAIT_SECONDS=${CANARY_WAIT_SECONDS:-900}
CANARY_POLL_SECONDS=${CANARY_POLL_SECONDS:-60}
SLURM_TIME_LIMIT_OVERRIDE=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
SKIP_RAW_PREFLIGHT=${SKIP_RAW_PREFLIGHT:-0}
LOG=${RUN_DIR}/fast_repair_driver.log

mkdir -p "$RUN_DIR"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"
}

status_counts() {
    local dir=$1
    if [ -d "$dir" ]; then
        find "$dir" -maxdepth 1 -type f -printf '%f\n' |
            sed -n 's/.*\.//p' |
            sort |
            uniq -c |
            awk '{print $2 "=" $1}' |
            tr '\n' ' '
    fi
}

active_repair_jobs() {
    squeue -u "$USER" -h -o '%j' | awk '$1 ~ /^[0-9]{2}_[0-9]{8}$/ {n++} END{print n+0}'
}

write_status_counts_tsv() {
    local dir=$1
    local out=$2
    {
        printf 'state\tcount\n'
        if [ -d "$dir" ]; then
            find "$dir" -maxdepth 1 -type f -printf '%f\n' |
                sed -n 's/.*\.//p' |
                sort |
                uniq -c |
                awk '{print $2 "\t" $1}'
        fi
    } > "$out"
}

log "starting fast aggregate repair"
log "audit_run_dir=$AUDIT_RUN_DIR"
log "triaged=$TRIAGED"
log "run_dir=$RUN_DIR"
log "max_active=$MAX_ACTIVE"
log "skip_raw_preflight=$SKIP_RAW_PREFLIGHT"

if [ ! -s "$TRIAGED" ]; then
    log "ERROR missing triaged rebuild candidates: $TRIAGED"
    exit 2
fi

if [ "$SKIP_RAW_PREFLIGHT" = "1" ]; then
    log "building repair manifests without /badc preflight; raw_missing will come from skipped repair statuses"
    {
        printf 'path\tradar\tdate\tradar_num\tstatuses\traw_status\traw_source\tsp_path\tlp_path\tissues\n'
        awk -F '\t' 'NR>1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {
            key=$2 "\t" $3
            if (!(key in seen)) {
                seen[key]=1
                print $1 "\t" $2 "\t" $3 "\t" $4 "\t" $5 "\tunchecked\t\t\t\t" $7
            }
        }' "$TRIAGED" | sort -t $'\t' -k2,2 -k3,3
    } > "$RUN_DIR/repair_candidates.tsv"
    awk -F '\t' '
        NR == 1 {print; next}
        {
            key=$2 "\t" $3
            if (per_radar[$2] < 2) {
                keep[key]=1
                per_radar[$2]++
            }
            row[NR]=$0
            keys[NR]=key
            status[NR]=$5
        }
        END {
            for (wanted_i=1; wanted_i<=4; wanted_i++) {
                wanted = (wanted_i == 1 ? "unreadable_or_invalid_hdf5" : wanted_i == 2 ? "structural_issue" : wanted_i == 3 ? "corrupt_gap_boundary" : "missing_variable")
                for (i=2; i<=NR; i++) {
                    if (index(status[i], wanted) && !(keys[i] in keep)) {
                        keep[keys[i]]=1
                        break
                    }
                }
            }
            for (i=2; i<=NR; i++) {
                if (keys[i] in keep) print row[i]
            }
        }
    ' "$RUN_DIR/repair_candidates.tsv" > "$RUN_DIR/canary_candidates.tsv"
    awk -F '\t' '
        NR == FNR {
            if (FNR > 1) keep[$2 "\t" $3]=1
            next
        }
        FNR == 1 {print; next}
        !(($2 "\t" $3) in keep) {print}
    ' "$RUN_DIR/canary_candidates.tsv" "$RUN_DIR/repair_candidates.tsv" > "$RUN_DIR/full_repair_candidates.tsv"
    cp "$RUN_DIR/repair_candidates.tsv" "$RUN_DIR/raw_available.tsv"
    printf 'path\tradar\tdate\tradar_num\tstatuses\traw_status\traw_source\tsp_path\tlp_path\tissues\n' > "$RUN_DIR/raw_missing.tsv"
    {
        printf 'unique_failed_tasks=%s\n' "$(awk 'NR>1{n++} END{print n+0}' "$RUN_DIR/repair_candidates.tsv")"
        printf 'raw_available=%s\n' "$(awk 'NR>1{n++} END{print n+0}' "$RUN_DIR/repair_candidates.tsv")"
        printf 'raw_missing=unknown_until_repair_skips\n'
        printf 'canary_tasks=%s\n' "$(awk 'NR>1{n++} END{print n+0}' "$RUN_DIR/canary_candidates.tsv")"
        printf 'full_repair_tasks=%s\n' "$(awk 'NR>1{n++} END{print n+0}' "$RUN_DIR/full_repair_candidates.tsv")"
    } > "$RUN_DIR/prepare_summary.txt"
else
    "$ENV/bin/python" "$SCRIPT_DIR/prepare_aggregate_repair_from_audit.py" \
        --triaged "$TRIAGED" \
        --out-dir "$RUN_DIR"
fi

CANARY=${RUN_DIR}/canary_candidates.tsv
FULL=${RUN_DIR}/full_repair_candidates.tsv
REPAIR_ALL=${RUN_DIR}/repair_candidates.tsv
CANARY_STATUS=${RUN_DIR}/forced_repair_status_${RUN_STAMP}_canary
FULL_STATUS=${RUN_DIR}/forced_repair_status_${RUN_STAMP}_full

raw_available=$(awk 'NR>1{n++} END{print n+0}' "$REPAIR_ALL")
canary_tasks=$(awk 'NR>1{n++} END{print n+0}' "$CANARY")
full_tasks=$(awk 'NR>1{n++} END{print n+0}' "$FULL")
log "raw_available=$raw_available canary_tasks=$canary_tasks full_tasks=$full_tasks"

if [ "$canary_tasks" -eq 0 ]; then
    log "no canary tasks; stopping"
    exit 0
fi

CANARY_RUN_STAMP=${RUN_STAMP}_canary
CANARY_LOG=${RUN_DIR}/nimrod_forced_repair_candidates_${CANARY_RUN_STAMP}.log
log "submitting canary"
RUN_STAMP="$CANARY_RUN_STAMP" \
LOG="$CANARY_LOG" \
STATUS_DIR="$CANARY_STATUS" \
MAX_ACTIVE="$MAX_ACTIVE" \
SLEEP_SECONDS=10 \
SLURM_TIME_LIMIT_OVERRIDE="$SLURM_TIME_LIMIT_OVERRIDE" \
H5_VERIFY=1 \
"$SCRIPT_DIR/submit_repair_candidates_force.sh" "$CANARY" 2>&1 | tee -a "$LOG"

log "monitoring canary"
deadline=$(( $(date +%s) + CANARY_WAIT_SECONDS ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    counts=$(status_counts "$CANARY_STATUS")
    active=$(active_repair_jobs)
    log "canary active_jobs=$active status_counts=${counts:-none}"
    completed=$(find "$CANARY_STATUS" -maxdepth 1 -type f \( -name '*.done' -o -name '*.failed' -o -name '*.skipped' \) 2>/dev/null | wc -l)
    if [ "$completed" -ge "$canary_tasks" ]; then
        break
    fi
    sleep "$CANARY_POLL_SECONDS"
done

write_status_counts_tsv "$CANARY_STATUS" "$RUN_DIR/canary_status_counts.tsv"
canary_done=$(find "$CANARY_STATUS" -maxdepth 1 -type f -name '*.done' 2>/dev/null | wc -l)
canary_failed=$(find "$CANARY_STATUS" -maxdepth 1 -type f -name '*.failed' 2>/dev/null | wc -l)
canary_skipped=$(find "$CANARY_STATUS" -maxdepth 1 -type f -name '*.skipped' 2>/dev/null | wc -l)
active=$(active_repair_jobs)
log "canary summary done=$canary_done failed=$canary_failed skipped=$canary_skipped active_jobs=$active"

if [ "$canary_done" -eq 0 ] && [ "$active" -gt 0 ]; then
    log "canary appears unhealthy: no completed repairs before timeout; cancelling active repair jobs"
    squeue -u "$USER" -h -o '%i %j' |
        awk '$2 ~ /^[0-9]{2}_[0-9]{8}$/ {print $1}' |
        xargs -r scancel
    while [ "$(active_repair_jobs)" -gt 0 ]; do
        log "waiting for cancelled canary jobs to clear active_jobs=$(active_repair_jobs)"
        sleep 10
    done
    awk -F '\t' 'NR>1{print $2 "\t" $3}' "$CANARY" | while IFS=$'\t' read -r radar date; do
        marker="${CANARY_STATUS}/${radar}_${date}.stalled"
        {
            printf 'state=stalled\n'
            printf 'radar=%s\n' "$radar"
            printf 'date=%s\n' "$date"
            printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            printf 'message=canary had no completed repairs before timeout\n'
        } > "$marker"
    done
    write_status_counts_tsv "$CANARY_STATUS" "$RUN_DIR/canary_status_counts.tsv"
    log "stopping before full repair because canary was unhealthy"
    exit 3
fi

if [ "$full_tasks" -eq 0 ]; then
    log "no full repair tasks after canary"
else
    FULL_RUN_STAMP=${RUN_STAMP}_full
    FULL_LOG=${RUN_DIR}/nimrod_forced_repair_candidates_${FULL_RUN_STAMP}.log
    log "submitting full repair batch"
    RUN_STAMP="$FULL_RUN_STAMP" \
    LOG="$FULL_LOG" \
    STATUS_DIR="$FULL_STATUS" \
    MAX_ACTIVE="$MAX_ACTIVE" \
    SLEEP_SECONDS=30 \
    SLURM_TIME_LIMIT_OVERRIDE="$SLURM_TIME_LIMIT_OVERRIDE" \
    H5_VERIFY=1 \
    "$SCRIPT_DIR/submit_repair_candidates_force.sh" "$FULL" 2>&1 | tee -a "$LOG"

    log "waiting for full repair jobs to finish"
    while [ "$(active_repair_jobs)" -gt 0 ]; do
        log "full active_jobs=$(active_repair_jobs) status_counts=$(status_counts "$FULL_STATUS") disk=$(df -h /gws/ssde/j25a/ncas_radar/vol2/avocet | tail -1)"
        sleep 300
    done
fi

write_status_counts_tsv "$FULL_STATUS" "$RUN_DIR/full_status_counts.tsv"
cat "$RUN_DIR/canary_status_counts.tsv" "$RUN_DIR/full_status_counts.tsv" > "$RUN_DIR/repair_status_counts.tsv"

{
    head -1 "$REPAIR_ALL"
    awk -F '\t' '
        NR == FNR {
            if (NR > 1) row[$2 "\t" $3]=$0
            next
        }
        /\.skipped$/ {
            name=$0
            sub(/^.*\//, "", name)
            sub(/\.skipped$/, "", name)
            split(name, parts, "_")
            date=parts[length(parts)]
            radar=name
            sub("_" date "$", "", radar)
            key=radar "\t" date
            if (key in row) print row[key]
        }
    ' "$REPAIR_ALL" <(find "$CANARY_STATUS" "$FULL_STATUS" -maxdepth 1 -type f -name '*.skipped' 2>/dev/null | sort)
} > "$RUN_DIR/raw_missing.tsv"

POST_MANIFEST=${RUN_DIR}/post_repair_audit_manifest.txt
awk -F '\t' 'NR>1 && $1 != "" {print $1}' "$REPAIR_ALL" | sort -u > "$POST_MANIFEST"
POST_AUDIT=${RUN_DIR}/post_repair_audit.tsv
log "running post repair audit"
"$ENV/bin/python" "$SCRIPT_DIR/audit_aggregate_file_health.py" \
    --manifest "$POST_MANIFEST" \
    --output "$POST_AUDIT" 2>&1 | tee -a "$LOG"

awk -F '\t' 'NR == 1 || (NR > 1 && $7 != "ok")' "$POST_AUDIT" > "$RUN_DIR/remaining_failures.tsv"
awk -F '\t' 'NR > 1 {c[$7]++} END {for (k in c) print k "\t" c[k]}' "$POST_AUDIT" | sort > "$RUN_DIR/post_repair_status_counts.tsv"
log "post repair status counts:"
cat "$RUN_DIR/post_repair_status_counts.tsv" | tee -a "$LOG"
log "done"
