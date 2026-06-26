#!/bin/bash

set -euo pipefail

RUN_DIR=${1:?Usage: cleanup_submitted_rewrite_targets.sh <full_rewrite_run_dir>}
RUN_STAMP=$(basename "$RUN_DIR")
OUT_BASE=${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
FULL_LOG=${FULL_LOG:-$RUN_DIR/nimrod_forced_repair_candidates_${RUN_STAMP}_full.log}
WORK_BASE=${WORK_BASE:-/tmp/avocet_cleanup_submitted_rewrite_targets_${RUN_STAMP}}
SLEEP_SECONDS=${SLEEP_SECONDS:-300}
ONCE=${ONCE:-0}

RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')

mkdir -p "$WORK_BASE"
LOG=$WORK_BASE/cleanup_submitted_rewrite_targets.log
STATE=$WORK_BASE/deleted_paths.txt
touch "$STATE"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"
}

radar_num() {
    local radar=$1
    local i
    for i in "${!RADARS[@]}"; do
        if [ "${RADARS[$i]}" = "$radar" ]; then
            printf '%s\n' "${RADAR_NUMS[$i]}"
            return 0
        fi
    done
    return 1
}

legacy_cutoff_epoch() {
    local marker=$RUN_DIR/full_submission_started.marker
    local raw_ts=""
    if [ -f "$marker" ]; then
        raw_ts=$(sed -n 's/^timestamp_utc=//p' "$marker" | tail -n 1)
    fi
    if [ -n "$raw_ts" ]; then
        date -d "$raw_ts" +%s 2>/dev/null && return 0
    fi
    date -u +%s
}

build_candidates() {
    awk '
        /kicked off slurm job/ {
            for (i = 1; i <= NF; i++) {
                if ($i == "for") {
                    split($(i + 2), d, "/")
                    printf "%s\t%04d%02d%02d\n", $(i + 1), d[1], d[2], d[3]
                    break
                }
            }
        }
    ' "$FULL_LOG" | sort -u
}

cleanup_once() {
    local cutoff=$1
    local manifest=$WORK_BASE/candidates.tsv
    local deleted=$WORK_BASE/deleted_$(date -u +%Y%m%dT%H%M%SZ).tsv
    local deleted_count=0
    local deleted_bytes=0

    if [ ! -f "$FULL_LOG" ]; then
        log "waiting for full log: $FULL_LOG"
        return 0
    fi

    build_candidates > "$manifest"
    {
        printf 'size_bytes\tpath\n'
        while IFS=$'\t' read -r radar date; do
            [ -n "$radar" ] || continue
            if ! rnum=$(radar_num "$radar"); then
                continue
            fi
            y=${date:0:4}
            path="${OUT_BASE%/}/${radar}/${y}/${date}_polar_pl_radar${rnum}_aggregate.h5"
            grep -qxF "$path" "$STATE" && continue
            [ -f "$path" ] || continue
            case "$(basename "$path")" in .*) continue ;; esac
            mtime=$(stat -c %Y "$path" 2>/dev/null || echo 0)
            if [ "$mtime" -ge "$cutoff" ]; then
                continue
            fi
            size=$(stat -c %s "$path" 2>/dev/null || echo 0)
            rm -f -- "$path"
            if [ ! -e "$path" ]; then
                printf '%s\t%s\n' "$size" "$path"
                printf '%s\n' "$path" >> "$STATE"
                deleted_count=$((deleted_count + 1))
                deleted_bytes=$((deleted_bytes + size))
            fi
        done < "$manifest"
    } > "$deleted"
    log "deleted_count=$deleted_count deleted_bytes=$deleted_bytes candidates=$(wc -l < "$manifest") free=$(df -h /gws/ssde/j25a/ncas_radar | awk 'NR==2{print $4}')"
}

cutoff=$(legacy_cutoff_epoch)
log "starting submitted-target cleanup run_dir=$RUN_DIR cutoff_epoch=$cutoff sleep_seconds=$SLEEP_SECONDS once=$ONCE"

while true; do
    cleanup_once "$cutoff"
    if [ "$ONCE" -eq 1 ]; then
        break
    fi
    sleep "$SLEEP_SECONDS"
done
