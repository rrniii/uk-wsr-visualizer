#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

CANDIDATES=${1:?Usage: submit_repair_candidates.sh <candidate-tsv>}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
MAX_ACTIVE=${MAX_ACTIVE:-4000}
if ! [[ "$MAX_ACTIVE" =~ ^[0-9]+$ ]] || [ "$MAX_ACTIVE" -lt 1 ]; then
    echo "ERROR: MAX_ACTIVE must be a positive integer" >&2
    exit 1
fi
if [ "$MAX_ACTIVE" -gt 4000 ]; then
    MAX_ACTIVE=4000
fi
SLEEP_SECONDS=${SLEEP_SECONDS:-60}
LOG=${LOG:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_repair_candidates_$(date -u +%Y%m%dT%H%M%SZ).log}
OUT_BASE_OVERRIDE=${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE_OVERRIDE=${SCRATCH_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/tmp_raw_radar_repair}
SLURM_TIME_LIMIT_OVERRIDE=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
SLURM_EXCLUDE_OVERRIDE=${SLURM_EXCLUDE_OVERRIDE:-}
H5_VERIFY=${H5_VERIFY:-1}
RESUME_SKIP_SUBMITTED=${RESUME_SKIP_SUBMITTED:-1}

export OUT_BASE_OVERRIDE SCRATCH_BASE_OVERRIDE SLURM_TIME_LIMIT_OVERRIDE SLURM_EXCLUDE_OVERRIDE H5_VERIFY

if [ ! -f "$CANDIDATES" ]; then
    echo "ERROR: candidate file not found: $CANDIDATES"
    exit 1
fi

active_jobs() {
    squeue -u "$USER" -h -o '%j' | awk '
        $1 ~ /^[0-9]{2}_[0-9]{8}$/ {
            total++
        }
        END {
            print total + 0
        }
    '
}

mkdir -p "$(dirname "$LOG")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting repair submissions" | tee -a "$LOG"
echo "candidate_file=$CANDIDATES" | tee -a "$LOG"
echo "env=$ENV" | tee -a "$LOG"
echo "max_active=$MAX_ACTIVE" | tee -a "$LOG"
echo "out_base=$OUT_BASE_OVERRIDE" | tee -a "$LOG"
echo "scratch_base=$SCRATCH_BASE_OVERRIDE" | tee -a "$LOG"
echo "slurm_time_limit=$SLURM_TIME_LIMIT_OVERRIDE" | tee -a "$LOG"
echo "slurm_exclude=$SLURM_EXCLUDE_OVERRIDE" | tee -a "$LOG"
echo "h5_verify=$H5_VERIFY" | tee -a "$LOG"
echo "resume_skip_submitted=$RESUME_SKIP_SUBMITTED" | tee -a "$LOG"

submitted_dates=""
if [ "$RESUME_SKIP_SUBMITTED" -eq 1 ] && [ -f "$LOG" ]; then
    submitted_dates=$(mktemp)
    awk '
        /kicked off slurm job/ {
            for (i = 1; i <= NF; i++) {
                if ($i == "for") {
                    split($(i + 2), date_parts, "/")
                    printf "%s\t%04d%02d%02d\n", $(i + 1), date_parts[1], date_parts[2], date_parts[3]
                    break
                }
            }
        }
    ' "$LOG" | sort -u > "$submitted_dates"
    echo "already_submitted_repairs=$(wc -l < "$submitted_dates")" | tee -a "$LOG"
fi

if [ -n "$submitted_dates" ]; then
    awk -F '\t' '
        NR == FNR {
            submitted[$1 "\t" $2] = 1
            next
        }
        FNR > 1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {
            key = $2 "\t" $3
            if (!(key in submitted)) {
                print key
            }
        }
    ' "$submitted_dates" "$CANDIDATES"
else
    awk -F '\t' 'NR > 1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {print $2 "\t" $3}' "$CANDIDATES"
fi \
    | sort -u \
    | while IFS=$'\t' read -r radar date; do
        while [ "$(active_jobs)" -ge "$MAX_ACTIVE" ]; do
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting: active_jobs=$(active_jobs)" | tee -a "$LOG"
            sleep "$SLEEP_SECONDS"
        done

        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submitting repair radar=$radar date=$date" | tee -a "$LOG"
        ./convert_all_files.sh --force "$radar" "$ENV" "$date" "$date" 2>&1 | tee -a "$LOG"
    done

if [ -n "$submitted_dates" ]; then
    rm -f "$submitted_dates"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] repair submissions complete" | tee -a "$LOG"
