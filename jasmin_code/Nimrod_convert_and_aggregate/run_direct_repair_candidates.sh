#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

CANDIDATES=${1:?Usage: run_direct_repair_candidates.sh <candidate-tsv-or-job-list>}

ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
CONCURRENCY=${CONCURRENCY:-2}
OUT_BASE=${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE=${SCRATCH_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/tmp_raw_radar_direct_repair}
LOG_ROOT=${LOG_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/direct_repair_logs}
RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
H5_VERIFY=${H5_VERIFY:-1}
NICE_LEVEL=${NICE_LEVEL:-10}
IONICE_CLASS=${IONICE_CLASS:-2}
IONICE_LEVEL=${IONICE_LEVEL:-7}

CONVERT_SCRIPT="${SCRIPT_DIR}/convert_and_aggregate.sh"
PYTHON_BIN="${ENV%/}/bin/python"
INDIR_BY_YEAR=/badc/ukmo-nimrod/data/single-site/storage_by_year
INDIR_FLAT=/badc/ukmo-nimrod/data/single-site
H5LS_BIN=$(command -v h5ls 2>/dev/null || true)

RUN_DIR="${LOG_ROOT}/direct_repair_${RUN_STAMP}"
TASKS_BASENAME=${TASKS_BASENAME:-tasks.tsv}
MAIN_LOG_BASENAME=${MAIN_LOG_BASENAME:-direct_repair_${RUN_STAMP}.log}
DATE_LOG_PREFIX=${DATE_LOG_PREFIX:-}
LOCK_CONFLICT_ACTION=${LOCK_CONFLICT_ACTION:-fail}
TASKS="${RUN_DIR}/${TASKS_BASENAME}"
STATUS_DIR="${RUN_DIR}/status"
DATE_LOG_DIR="${RUN_DIR}/date_logs"
MAIN_LOG="${RUN_DIR}/${MAIN_LOG_BASENAME}"

RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')

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

run_low_priority() {
    if command -v ionice >/dev/null 2>&1; then
        ionice -c "$IONICE_CLASS" -n "$IONICE_LEVEL" nice -n "$NICE_LEVEL" "$@"
    else
        nice -n "$NICE_LEVEL" "$@"
    fi
}

write_status() {
    local state=$1
    local radar=$2
    local date=$3
    local msg=${4:-}
    local file="${STATUS_DIR}/${radar}_${date}.${state}"
    {
        printf 'state=%s\n' "$state"
        printf 'radar=%s\n' "$radar"
        printf 'date=%s\n' "$date"
        printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        if [ -n "$msg" ]; then
            printf 'message=%s\n' "$msg"
        fi
    } > "$file"
}

run_one() {
    local radar=$1
    local date=$2
    local rnum y m d target_dir target tmp_out tmp_folder lock_dir log_file
    local input_sp_by input_lp_by input_sp_flat input_lp_flat input_sp input_lp

    log_file="${DATE_LOG_DIR}/${DATE_LOG_PREFIX}${radar}_${date}.log"
    {
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting direct repair radar=${radar} date=${date}"

        if ! rnum=$(radar_num "$radar"); then
            echo "ERROR: unknown radar: ${radar}"
            write_status failed "$radar" "$date" "unknown radar"
            return 1
        fi

        y=${date:0:4}
        m=${date:4:2}
        d=${date:6:2}
        target_dir="${OUT_BASE%/}/${radar}/${y}"
        target="${target_dir}/${date}_polar_pl_radar${rnum}_aggregate.h5"
        tmp_out="${target_dir}/.${date}_polar_pl_radar${rnum}_aggregate.h5.direct_${RUN_STAMP}_${BASHPID}.tmp"
        tmp_folder="${SCRATCH_BASE%/}/${radar}/${date}/${BASHPID}/extracted"
        lock_dir="${target}.direct.lock"

        mkdir -p "$target_dir" "$(dirname "$tmp_folder")"

        if [ -f "${STATUS_DIR}/${radar}_${date}.done" ] && [ -f "$target" ]; then
            if [ "$H5_VERIFY" -eq 0 ] || [ -z "$H5LS_BIN" ] || "$H5LS_BIN" "$target" >/dev/null 2>&1; then
                echo "done marker and valid target already exist; skipping"
                return 0
            fi
        fi

        if ! mkdir "$lock_dir" 2>/dev/null; then
            echo "ERROR: lock exists: ${lock_dir}"
            if [ "$LOCK_CONFLICT_ACTION" = "skip-no-status" ]; then
                echo "lock conflict; leaving status unchanged"
                return 0
            fi
            write_status failed "$radar" "$date" "lock exists"
            return 1
        fi
        trap 'rm -rf "$lock_dir"' RETURN

        input_sp_by="${INDIR_BY_YEAR}/${y}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-sp.dat.gz.tar"
        input_lp_by="${INDIR_BY_YEAR}/${y}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-lp.dat.gz.tar"
        input_sp_flat="${INDIR_FLAT}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-sp.dat.gz.tar"
        input_lp_flat="${INDIR_FLAT}/${radar}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${radar}_${date}_raw-dual-polar-augzdr-lp.dat.gz.tar"

        input_sp=""
        input_lp=""
        if [ -f "$input_sp_by" ] || [ -f "$input_lp_by" ]; then
            input_sp="$input_sp_by"
            input_lp="$input_lp_by"
        elif [ -f "$input_sp_flat" ] || [ -f "$input_lp_flat" ]; then
            input_sp="$input_sp_flat"
            input_lp="$input_lp_flat"
        fi

        if [ ! -f "$input_sp" ] || [ ! -f "$input_lp" ]; then
            echo "missing paired input data; sp=${input_sp:-unset} lp=${input_lp:-unset}"
            write_status skipped "$radar" "$date" "missing paired input data"
            return 0
        fi

        rm -f "$tmp_out"
        rm -rf "${tmp_folder:?}"
        mkdir -p "$tmp_folder"

        echo "target=${target}"
        echo "tmp_out=${tmp_out}"
        echo "tmp_folder=${tmp_folder}"

        if ! run_low_priority "$CONVERT_SCRIPT" -r "$radar" -y "$y" -m "$m" -d "$d" -t "$tmp_folder" -o "$tmp_out" -c "$ENV"; then
            rm -f "$tmp_out"
            write_status failed "$radar" "$date" "conversion failed"
            return 1
        fi

        if [ ! -f "$tmp_out" ]; then
            write_status failed "$radar" "$date" "temporary output was not created"
            return 1
        fi

        if [ "$H5_VERIFY" -eq 1 ] && [ -n "$H5LS_BIN" ]; then
            if ! "$H5LS_BIN" "$tmp_out" >/dev/null 2>&1; then
                rm -f "$tmp_out"
                write_status failed "$radar" "$date" "h5ls validation failed"
                return 1
            fi
        fi

        mv -f "$tmp_out" "$target"
        write_status done "$radar" "$date" "repaired aggregate written"
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] completed direct repair radar=${radar} date=${date}"
    } > "$log_file" 2>&1
}

if [ ! -f "$CANDIDATES" ]; then
    echo "ERROR: candidate file not found: $CANDIDATES" >&2
    exit 1
fi
if [ ! -x "$CONVERT_SCRIPT" ]; then
    echo "ERROR: missing executable converter wrapper: $CONVERT_SCRIPT" >&2
    exit 1
fi
if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: missing python in env: $PYTHON_BIN" >&2
    exit 1
fi
if ! [[ "$CONCURRENCY" =~ ^[0-9]+$ ]] || [ "$CONCURRENCY" -lt 1 ]; then
    echo "ERROR: CONCURRENCY must be a positive integer" >&2
    exit 1
fi

mkdir -p "$RUN_DIR" "$STATUS_DIR" "$DATE_LOG_DIR"

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
' "$CANDIDATES" | sort -u > "$TASKS"

task_count=$(wc -l < "$TASKS")
{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting direct aggregate repair"
    echo "candidate_file=$CANDIDATES"
    echo "tasks=$TASKS"
    echo "task_count=$task_count"
    echo "concurrency=$CONCURRENCY"
    echo "tasks_basename=$TASKS_BASENAME"
    echo "main_log_basename=$MAIN_LOG_BASENAME"
    echo "date_log_prefix=$DATE_LOG_PREFIX"
    echo "lock_conflict_action=$LOCK_CONFLICT_ACTION"
    echo "env=$ENV"
    echo "out_base=$OUT_BASE"
    echo "scratch_base=$SCRATCH_BASE"
    echo "run_dir=$RUN_DIR"
    echo "h5_verify=$H5_VERIFY"
    echo
} | tee -a "$MAIN_LOG"

if [ "$task_count" -eq 0 ]; then
    echo "No direct repair tasks found." | tee -a "$MAIN_LOG"
    exit 0
fi

while IFS=$'\t' read -r radar date; do
    while [ "$(jobs -pr | wc -l)" -ge "$CONCURRENCY" ]; do
        sleep 10
    done
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] queued direct repair radar=${radar} date=${date}" | tee -a "$MAIN_LOG"
    run_one "$radar" "$date" &
done < "$TASKS"

wait || true

done_count=$(find "$STATUS_DIR" -type f -name '*.done' | wc -l)
failed_count=$(find "$STATUS_DIR" -type f -name '*.failed' | wc -l)
skipped_count=$(find "$STATUS_DIR" -type f -name '*.skipped' | wc -l)
{
    echo
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] direct aggregate repair finished"
    echo "done=$done_count"
    echo "failed=$failed_count"
    echo "skipped=$skipped_count"
} | tee -a "$MAIN_LOG"

if [ "$failed_count" -gt 0 ]; then
    exit 1
fi
