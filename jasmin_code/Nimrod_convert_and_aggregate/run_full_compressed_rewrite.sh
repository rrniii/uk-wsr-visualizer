#!/bin/bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

BASE=${BASE:-/gws/ssde/j25a/ncas_radar}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
RUN_STAMP=${RUN_STAMP:-full_compressed_rewrite_$(date -u +%Y%m%dT%H%M%SZ)}
RUN_DIR=${RUN_DIR:-$BASE/vol2/avocet/direct_repair_logs/${RUN_STAMP}}
OUT_BASE_OVERRIDE=${OUT_BASE_OVERRIDE:-$BASE/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE_OVERRIDE=${SCRATCH_BASE_OVERRIDE:-$BASE/vol2/avocet/tmp_raw_radar_repair}
MAX_ACTIVE=${MAX_ACTIVE:-500}
MIN_FREE_GB=${MIN_FREE_GB:-500}
SLEEP_SECONDS=${SLEEP_SECONDS:-60}
SLURM_TIME_LIMIT_OVERRIDE=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
SLURM_PARTITION_OVERRIDE=${SLURM_PARTITION_OVERRIDE:-standard}
SLURM_QOS_OVERRIDE=${SLURM_QOS_OVERRIDE:-standard}
SLURM_EXCLUDE_OVERRIDE=${SLURM_EXCLUDE_OVERRIDE:-}
H5_VERIFY=${H5_VERIFY:-1}
H5_COMPRESS=${H5_COMPRESS:-1}
H5_GZIP_LEVEL=${H5_GZIP_LEVEL:-4}
RAW_PRECHECK=${RAW_PRECHECK:-1}
DISCOVERY_MODE=${DISCOVERY_MODE:-date_range}
REWRITE_START_DATE=${REWRITE_START_DATE:-20140101}
REWRITE_END_DATE=${REWRITE_END_DATE:-$(date -u +%Y%m%d)}
CANARY_PER_RADAR=${CANARY_PER_RADAR:-1}
CANARY_WAIT_SECONDS=${CANARY_WAIT_SECONDS:-7200}
CANARY_POLL_SECONDS=${CANARY_POLL_SECONDS:-120}

LOG=$RUN_DIR/full_compressed_rewrite_driver.log
MANIFEST=$RUN_DIR/raw_available_rewrite_candidates.tsv
CANARY=$RUN_DIR/canary_candidates.tsv
FULL=$RUN_DIR/full_rewrite_candidates.tsv
CANARY_STATUS=$RUN_DIR/forced_repair_status_${RUN_STAMP}_canary
FULL_STATUS=$RUN_DIR/forced_repair_status_${RUN_STAMP}_full

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

active_rewrite_jobs() {
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

log "starting full compressed rewrite"
log "run_dir=$RUN_DIR"
log "out_base=$OUT_BASE_OVERRIDE"
log "scratch_base=$SCRATCH_BASE_OVERRIDE"
log "max_active=$MAX_ACTIVE"
log "min_free_gb=$MIN_FREE_GB"
log "h5_compress=$H5_COMPRESS"
log "h5_gzip_level=$H5_GZIP_LEVEL"
log "raw_precheck=$RAW_PRECHECK"
log "discovery_mode=$DISCOVERY_MODE"
log "rewrite_start_date=$REWRITE_START_DATE"
log "rewrite_end_date=$REWRITE_END_DATE"
df -h "$BASE" > "$RUN_DIR/df_start.txt" 2>&1 || true

log "building rewrite manifest"
python3 - "$MANIFEST" "$DISCOVERY_MODE" "$REWRITE_START_DATE" "$REWRITE_END_DATE" <<'PY'
from datetime import datetime, timedelta
import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
mode = sys.argv[2]
start_date = sys.argv[3]
end_date = sys.argv[4]
radar_nums = {
    "castor-bay": "07",
    "chenies": "05",
    "clee-hill": "03",
    "cobbacombe": "16",
    "crug-y-gorrllwyn": "10",
    "deanhill": "21",
    "druima-starraig": "15",
    "dudwick": "14",
    "hameldon-hill": "04",
    "high-moorsley": "23",
    "holehead": "18",
    "ingham": "09",
    "jersey": "12",
    "munduff-hill": "19",
    "predannack": "08",
    "thurnham": "20",
    "wardon-hill": "11",
}

def target_path(radar, radar_num, date):
    return (
        f"/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/"
        f"single-site/{radar}/{date[:4]}/{date}_polar_pl_radar{radar_num}_aggregate.h5"
    )


def date_range(start, end):
    current = datetime.strptime(start, "%Y%m%d")
    final = datetime.strptime(end, "%Y%m%d")
    while current <= final:
        yield current.strftime("%Y%m%d")
        current += timedelta(days=1)


with out.open("w") as f:
    f.write("path\tradar\tdate\tradar_num\tstatuses\traw_status\traw_source\tsp_path\tlp_path\tissues\n")
    if mode != "date_range":
        raise SystemExit(f"unsupported DISCOVERY_MODE={mode!r}; use date_range")
    for radar, radar_num in radar_nums.items():
        for date in date_range(start_date, end_date):
            f.write(
                "\t".join(
                    [
                        target_path(radar, radar_num, date),
                        radar,
                        date,
                        radar_num,
                        "full_rewrite",
                        "raw_unchecked",
                        "date_range_raw_precheck",
                        "",
                        "",
                        "",
                    ]
                )
                + "\n"
            )
PY

task_count=$(awk 'NR>1{n++} END{print n+0}' "$MANIFEST")
log "raw_available_tasks=$task_count"
if [ "$task_count" -eq 0 ]; then
    log "ERROR no raw-available tasks found"
    exit 2
fi

python3 - "$MANIFEST" "$CANARY" "$FULL" "$CANARY_PER_RADAR" <<'PY'
import csv
import os
import sys

manifest, canary, full, per = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
with open(manifest, newline="") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))

selected = set()
by_radar = {}
for index, row in enumerate(rows):
    if os.path.exists(row["path"]):
        by_radar.setdefault(row["radar"], []).append((row["date"], index))

for radar, items in by_radar.items():
    for _, index in sorted(items, reverse=True)[:per]:
        selected.add(index)

fallback_count = {}
for index, row in enumerate(rows):
    if fallback_count.get(row["radar"], 0) >= per:
        continue
    if not any(rows[chosen]["radar"] == row["radar"] for chosen in selected):
        selected.add(index)
        fallback_count[row["radar"]] = fallback_count.get(row["radar"], 0) + 1

fieldnames = rows[0].keys() if rows else [
    "path", "radar", "date", "radar_num", "statuses", "raw_status",
    "raw_source", "sp_path", "lp_path", "issues",
]
with open(canary, "w", newline="") as out_canary, open(full, "w", newline="") as out_full:
    canary_writer = csv.DictWriter(out_canary, delimiter="\t", fieldnames=fieldnames, lineterminator="\n")
    full_writer = csv.DictWriter(out_full, delimiter="\t", fieldnames=fieldnames, lineterminator="\n")
    canary_writer.writeheader()
    full_writer.writeheader()
    for index, row in enumerate(rows):
        if index in selected:
            canary_writer.writerow(row)
        else:
            full_writer.writerow(row)
PY

canary_tasks=$(awk 'NR>1{n++} END{print n+0}' "$CANARY")
full_tasks=$(awk 'NR>1{n++} END{print n+0}' "$FULL")
log "canary_tasks=$canary_tasks full_tasks=$full_tasks"

CANARY_RUN_STAMP=${RUN_STAMP}_canary
CANARY_LOG=$RUN_DIR/nimrod_forced_repair_candidates_${CANARY_RUN_STAMP}.log
log "submitting compressed canary"
RUN_STAMP="$CANARY_RUN_STAMP" \
LOG="$CANARY_LOG" \
STATUS_DIR="$CANARY_STATUS" \
MAX_ACTIVE="$MAX_ACTIVE" \
MIN_FREE_GB="$MIN_FREE_GB" \
SLEEP_SECONDS=10 \
SLURM_TIME_LIMIT_OVERRIDE="$SLURM_TIME_LIMIT_OVERRIDE" \
SLURM_PARTITION_OVERRIDE="$SLURM_PARTITION_OVERRIDE" \
SLURM_QOS_OVERRIDE="$SLURM_QOS_OVERRIDE" \
SLURM_EXCLUDE_OVERRIDE="$SLURM_EXCLUDE_OVERRIDE" \
OUT_BASE_OVERRIDE="$OUT_BASE_OVERRIDE" \
SCRATCH_BASE_OVERRIDE="$SCRATCH_BASE_OVERRIDE" \
H5_VERIFY="$H5_VERIFY" \
H5_COMPRESS="$H5_COMPRESS" \
H5_GZIP_LEVEL="$H5_GZIP_LEVEL" \
RAW_PRECHECK="$RAW_PRECHECK" \
"$SCRIPT_DIR/submit_repair_candidates_force.sh" "$CANARY" 2>&1 | tee -a "$LOG"

deadline=$(( $(date +%s) + CANARY_WAIT_SECONDS ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    counts=$(status_counts "$CANARY_STATUS")
    active=$(active_rewrite_jobs)
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
log "canary summary done=$canary_done failed=$canary_failed skipped=$canary_skipped active_jobs=$(active_rewrite_jobs)"

if [ "$canary_failed" -gt 0 ] || [ "$canary_done" -eq 0 ]; then
    log "stopping before full rewrite because canary was not clean"
    exit 3
fi

FULL_RUN_STAMP=${RUN_STAMP}_full
FULL_LOG=$RUN_DIR/nimrod_forced_repair_candidates_${FULL_RUN_STAMP}.log
log "submitting full compressed rewrite"
RUN_STAMP="$FULL_RUN_STAMP" \
LOG="$FULL_LOG" \
STATUS_DIR="$FULL_STATUS" \
MAX_ACTIVE="$MAX_ACTIVE" \
MIN_FREE_GB="$MIN_FREE_GB" \
SLEEP_SECONDS="$SLEEP_SECONDS" \
SLURM_TIME_LIMIT_OVERRIDE="$SLURM_TIME_LIMIT_OVERRIDE" \
SLURM_PARTITION_OVERRIDE="$SLURM_PARTITION_OVERRIDE" \
SLURM_QOS_OVERRIDE="$SLURM_QOS_OVERRIDE" \
SLURM_EXCLUDE_OVERRIDE="$SLURM_EXCLUDE_OVERRIDE" \
OUT_BASE_OVERRIDE="$OUT_BASE_OVERRIDE" \
SCRATCH_BASE_OVERRIDE="$SCRATCH_BASE_OVERRIDE" \
H5_VERIFY="$H5_VERIFY" \
H5_COMPRESS="$H5_COMPRESS" \
H5_GZIP_LEVEL="$H5_GZIP_LEVEL" \
RAW_PRECHECK="$RAW_PRECHECK" \
"$SCRIPT_DIR/submit_repair_candidates_force.sh" "$FULL" 2>&1 | tee -a "$LOG"

log "full rewrite submissions complete; monitoring active jobs"
while [ "$(active_rewrite_jobs)" -gt 0 ]; do
    log "full active_jobs=$(active_rewrite_jobs) status_counts=$(status_counts "$FULL_STATUS") disk=$(df -h "$BASE" | tail -1)"
    sleep 300
done

write_status_counts_tsv "$FULL_STATUS" "$RUN_DIR/full_status_counts.tsv"
cat "$RUN_DIR/canary_status_counts.tsv" "$RUN_DIR/full_status_counts.tsv" > "$RUN_DIR/rewrite_status_counts.tsv"
df -h "$BASE" > "$RUN_DIR/df_end.txt" 2>&1 || true
log "full compressed rewrite driver finished"
