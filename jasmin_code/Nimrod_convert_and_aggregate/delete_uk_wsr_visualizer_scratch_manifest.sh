#!/bin/bash

set -euo pipefail

MANIFEST=${1:?Usage: delete_avocet_scratch_manifest.sh <manifest>}
BASE=${BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet}
TMP=${TMP:-${BASE}/tmp_raw_radar_repair}
RUN_DIR=${RUN_DIR:-${BASE}/direct_repair_logs/direct_repair_20260622T1115_postscan_sci03}
STAMP=${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
VALIDATED=${VALIDATED:-${RUN_DIR}/cleanup_manifest_${STAMP}.validated_current.txt}
RUNNING=${RUNNING:-${RUN_DIR}/cleanup_running_keys_current_delete_${STAMP}.txt}
DELETE_BATCH_SIZE=${DELETE_BATCH_SIZE:-100}

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

if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: manifest not found: $MANIFEST" >&2
    exit 1
fi

mkdir -p "$RUN_DIR"

> "$RUNNING"
while read -r job; do
    [ -n "$job" ] || continue
    rnum=${job%%_*}
    date=${job#*_}
    if radar=$(radar_for_num "$rnum"); then
        printf '%s\t%s\n' "$radar" "$date"
    fi
done < <(squeue -u "$USER" -h -o '%j' | awk '/^[0-9][0-9]_[0-9]{8}$/ {print $1}') >> "$RUNNING"
sort -u -o "$RUNNING" "$RUNNING"

awk -F '\t' -v tmp="$TMP" -v running="$RUNNING" '
    BEGIN {
        while ((getline line < running) > 0) {
            run[line] = 1
        }
    }
    NF >= 2 {
        path = $2
        if (index(path, tmp "/") != 1) {
            bad_prefix++
            next
        }
        if (path !~ /\/extracted$/) {
            bad_suffix++
            next
        }
        rel = path
        sub(tmp "/", "", rel)
        split(rel, parts, "/")
        radar = parts[1]
        date = parts[2]
        key = radar "\t" date
        if (key in run) {
            running_skip++
            next
        }
        print path
    }
    END {
        printf "bad_prefix=%d\n", bad_prefix + 0 > "/dev/stderr"
        printf "bad_suffix=%d\n", bad_suffix + 0 > "/dev/stderr"
        printf "running_skip=%d\n", running_skip + 0 > "/dev/stderr"
    }
' "$MANIFEST" | sort -u > "$VALIDATED"

echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "manifest=$MANIFEST"
echo "validated=$VALIDATED"
echo "running_keys=$RUNNING"
echo "running_key_count=$(wc -l < "$RUNNING")"
echo "manifest_count=$(wc -l < "$MANIFEST")"
echo "validated_count=$(wc -l < "$VALIDATED")"
echo "df_before"
df -h "$BASE"

if [ ! -s "$VALIDATED" ]; then
    echo "No validated paths to delete."
    exit 0
fi

batch=$(mktemp)
trap 'rm -f "$batch"' EXIT
deleted=0
while IFS= read -r path; do
    printf '%s\0' "$path" >> "$batch"
    deleted=$((deleted + 1))
    if [ "$((deleted % DELETE_BATCH_SIZE))" -eq 0 ]; then
        xargs -0 -r rm -rf < "$batch"
        : > "$batch"
        echo "deleted_paths=$deleted timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi
done < "$VALIDATED"

if [ -s "$batch" ]; then
    xargs -0 -r rm -rf < "$batch"
fi

echo "deleted_paths=$deleted timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "df_after"
df -h "$BASE"
