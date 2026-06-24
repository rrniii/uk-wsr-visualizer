#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR=${NIMROD_CODE_DIR:-$(cd "$(dirname "$SCRIPT_PATH")" && pwd)}
cd "$SCRIPT_DIR"

RADAR=${1:?Usage: run_slurm_forced_repair_one.sh <radar> <YYYYMMDD>}
DATE=${2:?Usage: run_slurm_forced_repair_one.sh <radar> <YYYYMMDD>}

ENV=${NIMROD_ENV:-${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}}
OUT_BASE=${OUT_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE=${SCRATCH_BASE_OVERRIDE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/tmp_raw_radar_repair}
RUN_STAMP=${FORCED_REPAIR_RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
STATUS_DIR=${FORCED_REPAIR_STATUS_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet/forced_repair_status_${RUN_STAMP}}
H5_VERIFY=${H5_VERIFY:-1}

CONVERT_SCRIPT="${SCRIPT_DIR}/convert_and_aggregate.sh"
INDIR_BY_YEAR=/badc/ukmo-nimrod/data/single-site/storage_by_year
INDIR_FLAT=/badc/ukmo-nimrod/data/single-site
H5LS_BIN=$(command -v h5ls 2>/dev/null || true)

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

write_status() {
    local state=$1
    local message=${2:-}
    local file="${STATUS_DIR}/${RADAR}_${DATE}.${state}"
    mkdir -p "$STATUS_DIR"
    {
        printf 'state=%s\n' "$state"
        printf 'radar=%s\n' "$RADAR"
        printf 'date=%s\n' "$DATE"
        printf 'job_id=%s\n' "${SLURM_JOB_ID:-}"
        printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        if [ -n "$message" ]; then
            printf 'message=%s\n' "$message"
        fi
    } > "$file"
}

lock_dir=""
tmp_out=""
cleanup() {
    if [ -n "$lock_dir" ]; then
        rmdir "$lock_dir" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting forced repair radar=${RADAR} date=${DATE}"

if ! [[ "$DATE" =~ ^[0-9]{8}$ ]]; then
    echo "ERROR: date must be YYYYMMDD: ${DATE}"
    write_status failed "bad date"
    exit 1
fi
if ! rnum=$(radar_num "$RADAR"); then
    echo "ERROR: unknown radar: ${RADAR}"
    write_status failed "unknown radar"
    exit 1
fi
if [ ! -x "$CONVERT_SCRIPT" ]; then
    echo "ERROR: missing executable converter wrapper: $CONVERT_SCRIPT"
    write_status failed "missing converter wrapper"
    exit 1
fi
if [ ! -x "${ENV%/}/bin/python" ]; then
    echo "ERROR: missing python in env: ${ENV%/}/bin/python"
    write_status failed "missing python env"
    exit 1
fi
if [ "$H5_VERIFY" -eq 1 ] && [ -z "$H5LS_BIN" ]; then
    echo "ERROR: h5ls is required when H5_VERIFY=1"
    write_status failed "missing h5ls"
    exit 1
fi

y=${DATE:0:4}
m=${DATE:4:2}
d=${DATE:6:2}
target_dir="${OUT_BASE%/}/${RADAR}/${y}"
target="${target_dir}/${DATE}_polar_pl_radar${rnum}_aggregate.h5"
tmp_out="${target_dir}/.${DATE}_polar_pl_radar${rnum}_aggregate.h5.force_${RUN_STAMP}_${SLURM_JOB_ID:-$$}.tmp"
tmp_folder="${SCRATCH_BASE%/}/${RADAR}/${DATE}/force_${RUN_STAMP}_${SLURM_JOB_ID:-$$}/extracted"
lock_dir="${target}.force.lock"

input_sp_by="${INDIR_BY_YEAR}/${y}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${DATE}_raw-dual-polar-augzdr-sp.dat.gz.tar"
input_lp_by="${INDIR_BY_YEAR}/${y}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${DATE}_raw-dual-polar-augzdr-lp.dat.gz.tar"
input_sp_flat="${INDIR_FLAT}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${DATE}_raw-dual-polar-augzdr-sp.dat.gz.tar"
input_lp_flat="${INDIR_FLAT}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${DATE}_raw-dual-polar-augzdr-lp.dat.gz.tar"

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
    write_status skipped "missing paired input data"
    exit 0
fi

mkdir -p "$target_dir" "$(dirname "$tmp_folder")" "$STATUS_DIR"
if ! mkdir "$lock_dir" 2>/dev/null; then
    echo "ERROR: lock exists: $lock_dir"
    write_status failed "lock exists"
    exit 1
fi

rm -f "$tmp_out"
rm -rf "${tmp_folder:?}"
mkdir -p "$tmp_folder"

echo "target=${target}"
echo "tmp_out=${tmp_out}"
echo "tmp_folder=${tmp_folder}"
echo "input_sp=${input_sp}"
echo "input_lp=${input_lp}"

if ! "$CONVERT_SCRIPT" -r "$RADAR" -y "$y" -m "$m" -d "$d" -t "$tmp_folder" -o "$tmp_out" -c "$ENV"; then
    rm -f "$tmp_out"
    write_status failed "conversion failed"
    exit 1
fi

if [ ! -f "$tmp_out" ]; then
    write_status failed "temporary output was not created"
    exit 1
fi

if [ "$H5_VERIFY" -eq 1 ]; then
    if ! "$H5LS_BIN" "$tmp_out" >/dev/null 2>&1; then
        rm -f "$tmp_out"
        write_status failed "h5ls validation failed"
        exit 1
    fi
fi

mv -f "$tmp_out" "$target"

if [ "$H5_VERIFY" -eq 1 ]; then
    if ! "$H5LS_BIN" "$target" >/dev/null 2>&1; then
        write_status failed "target h5ls validation failed after move"
        exit 1
    fi
fi

write_status done "repaired aggregate written"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] completed forced repair radar=${RADAR} date=${DATE}"
