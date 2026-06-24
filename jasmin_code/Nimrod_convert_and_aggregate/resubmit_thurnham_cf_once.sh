#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR=${LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet}
RUN_STAMP=${RUN_STAMP:-thurnham_cf_resubmit_$(date -u +%Y%m%dT%H%M%SZ)}
TSV="${LOG_DIR}/${RUN_STAMP}.tsv"
LOG="${LOG_DIR}/${RUN_STAMP}.log"
NOHUP_LOG="${LOG_DIR}/${RUN_STAMP}.nohup"

{
    printf 'path\tradar\tdate\n'
    squeue -u "$USER" -h -t CF -o '%i %j' \
        | awk '$2 ~ /^20_[0-9]{8}$/ {print "resubmit\tthurnham\t" substr($2, 4)}'
} > "$TSV"

mapfile -t JOB_IDS < <(
    squeue -u "$USER" -h -t CF -o '%i %j' \
        | awk '$2 ~ /^20_[0-9]{8}$/ {print $1}'
)

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stuck_thurnham_jobs=${#JOB_IDS[@]}"
echo "tsv=$TSV"
echo "log=$LOG"

if [ "${#JOB_IDS[@]}" -eq 0 ]; then
    echo "No stuck thurnham CONFIGURING jobs found."
    exit 0
fi

printf '%s\n' "${JOB_IDS[@]}" | xargs -r scancel
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cancelled stuck jobs"

setsid -f env \
    LOG="$LOG" \
    MAX_ACTIVE=4000 \
    RESUME_SKIP_SUBMITTED=0 \
    SLURM_EXCLUDE_OVERRIDE=host1070 \
    ./submit_repair_candidates.sh "$TSV" > "$NOHUP_LOG" 2>&1 < /dev/null

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] launched resubmission excluding host1070"
echo "nohup_log=$NOHUP_LOG"
