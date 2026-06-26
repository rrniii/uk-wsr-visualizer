#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

CANDIDATES=${1:?Usage: submit_repair_candidates_force.sh <candidate-tsv>}
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
RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
LOG=${LOG:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_forced_repair_candidates_${RUN_STAMP}.log}
OUT_BASE_OVERRIDE=${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE_OVERRIDE=${SCRATCH_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/tmp_raw_radar_repair}
STATUS_DIR=${STATUS_DIR:-$(dirname "$LOG")/forced_repair_status_${RUN_STAMP}}
SLURM_TIME_LIMIT_OVERRIDE=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
SLURM_PARTITION_OVERRIDE=${SLURM_PARTITION_OVERRIDE:-standard}
SLURM_QOS_OVERRIDE=${SLURM_QOS_OVERRIDE:-standard}
SLURM_EXCLUDE_OVERRIDE=${SLURM_EXCLUDE_OVERRIDE:-}
SLURM_MEM_OVERRIDE=${SLURM_MEM_OVERRIDE:-16G}
H5_VERIFY=${H5_VERIFY:-1}
H5_COMPRESS=${H5_COMPRESS:-1}
H5_GZIP_LEVEL=${H5_GZIP_LEVEL:-4}
MIN_FREE_GB=${MIN_FREE_GB:-500}
RAW_PRECHECK=${RAW_PRECHECK:-1}
RESUME_LOGS=${RESUME_LOGS:-$LOG}

ONE_SCRIPT="${SCRIPT_DIR}/run_slurm_forced_repair_one.sh"
INDIR_BY_YEAR=/badc/ukmo-nimrod/data/single-site/storage_by_year
INDIR_FLAT=/badc/ukmo-nimrod/data/single-site
RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')

if [ ! -f "$CANDIDATES" ]; then
    echo "ERROR: candidate file not found: $CANDIDATES" >&2
    exit 1
fi
if [ ! -x "$ONE_SCRIPT" ]; then
    echo "ERROR: missing executable forced repair script: $ONE_SCRIPT" >&2
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

free_gb() {
    df -BG /gws/ssde/j25a/ncas_radar | awk 'NR == 2 {gsub(/G/, "", $4); print $4 + 0}'
}

pulse_raw_exists() {
    local radar=$1
    local date=$2
    local y=${date:0:4}
    local sp_by="${INDIR_BY_YEAR}/${y}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-sp.dat.gz.tar"
    local lp_by="${INDIR_BY_YEAR}/${y}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-lp.dat.gz.tar"
    local sp_flat="${INDIR_FLAT}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-sp.dat.gz.tar"
    local lp_flat="${INDIR_FLAT}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-lp.dat.gz.tar"

    if [ -f "$sp_by" ] || [ -f "$lp_by" ]; then
        return 0
    fi
    if [ -f "$sp_flat" ] || [ -f "$lp_flat" ]; then
        return 0
    fi
    return 1
}

write_precheck_status() {
    local radar=$1
    local date=$2
    local state=$3
    local message=$4
    local file="${STATUS_DIR}/${radar}_${date}.${state}"
    mkdir -p "$STATUS_DIR"
    {
        printf 'state=%s\n' "$state"
        printf 'radar=%s\n' "$radar"
        printf 'date=%s\n' "$date"
        printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'message=%s\n' "$message"
    } > "$file"
}

mkdir -p "$(dirname "$LOG")" "$STATUS_DIR"
{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting forced repair submissions"
    echo "candidate_file=$CANDIDATES"
    echo "env=$ENV"
    echo "max_active=$MAX_ACTIVE"
    echo "out_base=$OUT_BASE_OVERRIDE"
    echo "scratch_base=$SCRATCH_BASE_OVERRIDE"
    echo "status_dir=$STATUS_DIR"
    echo "run_stamp=$RUN_STAMP"
    echo "slurm_time_limit=$SLURM_TIME_LIMIT_OVERRIDE"
    echo "slurm_partition=$SLURM_PARTITION_OVERRIDE"
    echo "slurm_qos=$SLURM_QOS_OVERRIDE"
    echo "slurm_exclude=$SLURM_EXCLUDE_OVERRIDE"
    echo "slurm_mem=$SLURM_MEM_OVERRIDE"
    echo "h5_verify=$H5_VERIFY"
    echo "h5_compress=$H5_COMPRESS"
    echo "h5_gzip_level=$H5_GZIP_LEVEL"
    echo "min_free_gb=$MIN_FREE_GB"
    echo "raw_precheck=$RAW_PRECHECK"
    echo "resume_logs=$RESUME_LOGS"
} | tee -a "$LOG"

tasks=$(mktemp)
submitted=$(mktemp)
cleanup() {
    rm -f "$tasks" "$submitted"
}
trap cleanup EXIT

awk -F '\t' '
    NR == 1 && $0 ~ /date/ {
        next
    }
    {
        radar = ""
        date = ""
        if (NF >= 3 && $2 != "" && $3 ~ /^[0-9]{8}$/) {
            radar = $2
            date = $3
        } else if (NF >= 2 && $1 != "" && $2 ~ /^[0-9]{8}$/) {
            radar = $1
            date = $2
        } else if (NF >= 4 && $3 != "" && $4 ~ /^[0-9]{8}$/) {
            radar = $3
            date = $4
        }
        if (radar != "" && date != "") {
            print radar "\t" date
        }
    }
' "$CANDIDATES" | sort -u > "$tasks"

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

if [ "$submitted_count" -eq 0 ]; then
    cat "$tasks"
else
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
    ' "$submitted" "$tasks"
fi |
while IFS=$'\t' read -r radar date; do
    while [ "$(active_jobs)" -ge "$MAX_ACTIVE" ]; do
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting: active_jobs=$(active_jobs)" | tee -a "$LOG"
        sleep "$SLEEP_SECONDS"
    done
    while [ "$(free_gb)" -lt "$MIN_FREE_GB" ]; do
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting: free_gb=$(free_gb) min_free_gb=${MIN_FREE_GB}" | tee -a "$LOG"
        sleep "$SLEEP_SECONDS"
    done

    if ! rnum=$(radar_num "$radar"); then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] skipping unknown radar=$radar date=$date" | tee -a "$LOG"
        continue
    fi

    y=${date:0:4}
    m=${date:4:2}
    d=${date:6:2}
    if [ "$RAW_PRECHECK" -eq 1 ] && ! pulse_raw_exists "$radar" "$date"; then
        write_precheck_status "$radar" "$date" skipped "missing input data"
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] skipping missing input data radar=$radar date=$date" | tee -a "$LOG"
        continue
    fi

    slurm_outs="${SCRATCH_BASE_OVERRIDE%/}/${radar}/${date}/forced_slurm_outs_${RUN_STAMP}"
    exclude_arg=()
    if [ -n "$SLURM_EXCLUDE_OVERRIDE" ]; then
        exclude_arg=(--exclude="$SLURM_EXCLUDE_OVERRIDE")
    fi

    mkdir -p "$slurm_outs"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] submitting forced repair radar=$radar date=$date" | tee -a "$LOG"
    job_str=$(
        sbatch \
            --account=ncas_radar \
            --partition="$SLURM_PARTITION_OVERRIDE" \
            --qos="$SLURM_QOS_OVERRIDE" \
            --time="$SLURM_TIME_LIMIT_OVERRIDE" \
            --mem="$SLURM_MEM_OVERRIDE" \
            "${exclude_arg[@]}" \
            -o "${slurm_outs}/convert.out" \
            -e "${slurm_outs}/convert.err" \
            --job-name="${rnum}_${date}" \
            --export="ALL,NIMROD_CODE_DIR=${SCRIPT_DIR},NIMROD_ENV=${ENV},OUT_BASE_OVERRIDE=${OUT_BASE_OVERRIDE},SCRATCH_BASE_OVERRIDE=${SCRATCH_BASE_OVERRIDE},FORCED_REPAIR_RUN_STAMP=${RUN_STAMP},FORCED_REPAIR_STATUS_DIR=${STATUS_DIR},H5_VERIFY=${H5_VERIFY},H5_COMPRESS=${H5_COMPRESS},H5_GZIP_LEVEL=${H5_GZIP_LEVEL}" \
            "$ONE_SCRIPT" "$radar" "$date"
    )
    job_id=${job_str//[![:digit:]]}
    echo "kicked off slurm job $job_id for $radar $y/$m/$d" | tee -a "$LOG"
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] forced repair submissions complete" | tee -a "$LOG"
