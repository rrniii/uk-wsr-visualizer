#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

CANDIDATES=${1:?Usage: submit_repair_candidates_fast.sh <candidate-tsv>}
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
LOG=${LOG:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_repair_candidates_fast_$(date -u +%Y%m%dT%H%M%SZ).log}
OUT_BASE_OVERRIDE=${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE_OVERRIDE=${SCRATCH_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/tmp_raw_radar_repair}
SLURM_TIME_LIMIT_OVERRIDE=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
SLURM_PARTITION_OVERRIDE=${SLURM_PARTITION_OVERRIDE:-standard}
SLURM_QOS_OVERRIDE=${SLURM_QOS_OVERRIDE:-standard}
SLURM_EXCLUDE_OVERRIDE=${SLURM_EXCLUDE_OVERRIDE:-}
RESUME_LOGS=${RESUME_LOGS:-$LOG}

CONVERT_SCRIPT="${SCRIPT_DIR}/convert_and_aggregate.sh"
RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')

if [ ! -f "$CANDIDATES" ]; then
    echo "ERROR: candidate file not found: $CANDIDATES" >&2
    exit 1
fi
if [ ! -x "$CONVERT_SCRIPT" ]; then
    echo "ERROR: missing executable converter wrapper: $CONVERT_SCRIPT" >&2
    exit 1
fi

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
{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting fast repair submissions"
    echo "candidate_file=$CANDIDATES"
    echo "env=$ENV"
    echo "max_active=$MAX_ACTIVE"
    echo "out_base=$OUT_BASE_OVERRIDE"
    echo "scratch_base=$SCRATCH_BASE_OVERRIDE"
    echo "slurm_time_limit=$SLURM_TIME_LIMIT_OVERRIDE"
    echo "slurm_partition=$SLURM_PARTITION_OVERRIDE"
    echo "slurm_qos=$SLURM_QOS_OVERRIDE"
    echo "slurm_exclude=$SLURM_EXCLUDE_OVERRIDE"
    echo "resume_logs=$RESUME_LOGS"
} | tee -a "$LOG"

tasks=$(mktemp)
submitted=$(mktemp)
cleanup() {
    rm -f "$tasks" "$submitted"
}
trap cleanup EXIT

awk -F '\t' 'NR > 1 && $2 != "" && $3 ~ /^[0-9]{8}$/ {print $2 "\t" $3}' "$CANDIDATES" | sort -u > "$tasks"

for resume_log in $RESUME_LOGS; do
    if [ -f "$resume_log" ]; then
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
        ' "$resume_log"
    fi
done | sort -u > "$submitted"

task_count=$(wc -l < "$tasks")
submitted_count=$(wc -l < "$submitted")
echo "task_count=$task_count" | tee -a "$LOG"
echo "already_submitted_repairs=$submitted_count" | tee -a "$LOG"

awk -F '\t' '
    NR == FNR {
        submitted[$1 "\t" $2] = 1
        next
    }
    {
        key = $1 "\t" $2
        if (!(key in submitted)) {
            print $1 "\t" $2
        }
    }
' "$submitted" "$tasks" |
while IFS=$'\t' read -r radar date; do
    while [ "$(active_jobs)" -ge "$MAX_ACTIVE" ]; do
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting: active_jobs=$(active_jobs)" | tee -a "$LOG"
        sleep "$SLEEP_SECONDS"
    done

    if ! rnum=$(radar_num "$radar"); then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] skipping unknown radar=$radar date=$date" | tee -a "$LOG"
        continue
    fi

    y=${date:0:4}
    m=${date:4:2}
    d=${date:6:2}
    agg_dir="${OUT_BASE_OVERRIDE%/}/${radar}/${y}"
    agg_file="${agg_dir}/${date}_polar_pl_radar${rnum}_aggregate.h5"
    tmp_folder="${SCRATCH_BASE_OVERRIDE%/}/${radar}/${date}/extracted"
    slurm_outs="${SCRATCH_BASE_OVERRIDE%/}/${radar}/${date}/slurm_outs"
    exclude_arg=""
    if [ -n "$SLURM_EXCLUDE_OVERRIDE" ]; then
        exclude_arg="--exclude=${SLURM_EXCLUDE_OVERRIDE}"
    fi

    mkdir -p "$agg_dir" "$tmp_folder" "$slurm_outs"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submitting repair radar=$radar date=$date" | tee -a "$LOG"
    job_str=$(
        sbatch \
            --account=ncas_radar \
            --partition="$SLURM_PARTITION_OVERRIDE" \
            --qos="$SLURM_QOS_OVERRIDE" \
            --time="$SLURM_TIME_LIMIT_OVERRIDE" \
            $exclude_arg \
            -o "${slurm_outs}/convert.out" \
            -e "${slurm_outs}/convert.err" \
            --job-name="${rnum}_${date}" \
            --wrap="${CONVERT_SCRIPT} -r ${radar} -y ${y} -m ${m} -d ${d} -t ${tmp_folder} -o ${agg_file} -c ${ENV}"
    )
    job_id=${job_str//[![:digit:]]}
    echo "kicked off slurm job $job_id for $radar $y/$m/$d" | tee -a "$LOG"
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] fast repair submissions complete" | tee -a "$LOG"
