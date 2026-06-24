#!/bin/bash

set -euo pipefail

BASE=${BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet}
TMP=${TMP:-${BASE}/tmp_raw_radar_repair}
RUN_DIR=${RUN_DIR:-${BASE}/direct_repair_logs/direct_repair_20260622T1115_postscan_sci03}
STATUS_DIR=${STATUS_DIR:-${RUN_DIR}/forced_repair_status_forced_after_lotus_retry2_20260623T1853Z}
STAMP=${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
MANIFEST=${MANIFEST:-${RUN_DIR}/cleanup_manifest_${STAMP}.txt}
RUNNING_KEYS=${RUNNING_KEYS:-${RUN_DIR}/cleanup_running_keys_${STAMP}.txt}
DELETE_BATCH_SIZE=${DELETE_BATCH_SIZE:-250}
DELETE=${DELETE:-0}
CLEAN_OLD_EXTRACTED=${CLEAN_OLD_EXTRACTED:-0}

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

mkdir -p "$RUN_DIR"

{
    squeue -u "$USER" -h -o '%j' \
        | awk '/^[0-9][0-9]_[0-9]{8}$/ {print substr($1, 1, 2) "\t" substr($1, 4)}' \
        | sort -u
} > "${RUNNING_KEYS}.raw"

> "$RUNNING_KEYS"
while IFS=$'\t' read -r rnum date; do
    [ -n "${rnum:-}" ] || continue
    if radar=$(radar_for_num "$rnum"); then
        printf '%s\t%s\n' "$radar" "$date"
    fi
done < "${RUNNING_KEYS}.raw" | sort -u > "$RUNNING_KEYS"
rm -f "${RUNNING_KEYS}.raw"

is_running_key() {
    local radar=$1
    local date=$2
    grep -qxF "${radar}	${date}" "$RUNNING_KEYS"
}

tmp_manifest=$(mktemp)
trap 'rm -f "$tmp_manifest"' EXIT
> "$tmp_manifest"
shopt -s nullglob

# Completed or failed forced-repair extraction directories. Logs are not included.
if [ -d "$STATUS_DIR" ]; then
    find "$STATUS_DIR" -type f \( -name '*.done' -o -name '*.failed' \) -print | while read -r status_file; do
        base=$(basename "$status_file")
        state=${base##*.}
        key=${base%.*}
        radar=${key%_*}
        date=${key##*_}
        if [ -z "$radar" ] || [ -z "$date" ] || is_running_key "$radar" "$date"; then
            continue
        fi
        date_dir="${TMP%/}/${radar}/${date}"
        [ -d "$date_dir" ] || continue
        for path in "$date_dir"/force_forced_after_lotus*/extracted; do
            [ -d "$path" ] || continue
            printf '%s\t%s\n' "$state" "$path"
        done
    done >> "$tmp_manifest"
fi

# Old direct/serial extraction directories that are not part of current running jobs.
if [ "$CLEAN_OLD_EXTRACTED" -eq 1 ]; then
    find "$TMP" -mindepth 3 -maxdepth 3 -type d -name extracted ! -path '*/force_forced_after_lotus*' -print 2>/dev/null \
        | while read -r path; do
            date_dir=$(dirname "$path")
            date=$(basename "$date_dir")
            radar=$(basename "$(dirname "$date_dir")")
            if [ -z "$radar" ] || [ -z "$date" ] || is_running_key "$radar" "$date"; then
                continue
            fi
            printf 'old_extracted\t%s\n' "$path"
        done >> "$tmp_manifest"
fi

sort -u "$tmp_manifest" > "$MANIFEST"

path_count=$(wc -l < "$MANIFEST")
running_count=$(wc -l < "$RUNNING_KEYS")
echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "tmp=$TMP"
echo "status_dir=$STATUS_DIR"
echo "manifest=$MANIFEST"
echo "running_keys=$RUNNING_KEYS"
echo "running_key_count=$running_count"
echo "manifest_path_count=$path_count"
echo "clean_old_extracted=$CLEAN_OLD_EXTRACTED"

echo "manifest_by_reason"
awk -F '\t' '{count[$1]++} END {for (reason in count) print reason, count[reason]}' "$MANIFEST" | sort

echo "estimating_manifest_size"
awk -F '\t' '{print $2}' "$MANIFEST" | xargs -r du -sch 2>/dev/null | tail -1 || true

if [ "$DELETE" -ne 1 ]; then
    echo "delete=0; dry run only"
    exit 0
fi

echo "delete=1; deleting in batches of $DELETE_BATCH_SIZE"
batch_file=$(mktemp)
deleted=0
awk -F '\t' '{print $2}' "$MANIFEST" | while IFS= read -r path; do
    printf '%s\0' "$path" >> "$batch_file"
    deleted=$((deleted + 1))
    if [ "$((deleted % DELETE_BATCH_SIZE))" -eq 0 ]; then
        xargs -0 -r rm -rf < "$batch_file"
        : > "$batch_file"
        echo "deleted_paths=$deleted timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi
done
if [ -s "$batch_file" ]; then
    xargs -0 -r rm -rf < "$batch_file"
fi
rm -f "$batch_file"
echo "cleanup_complete timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
