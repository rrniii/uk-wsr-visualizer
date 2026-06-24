#!/bin/bash
get_subdirs()( # sub-shell so don't need to cd back nor use local
    if cd $1; then

        # collect directories
        dirs=(*/)

        # strip trailing slashes and display
        echo "${dirs[@]%/}"
    fi
)
RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
                             
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')
#------------------------------------------------------------------------------------------------
# run as convert_all_files.sh <radar_name> [conda_env_location] <first_date> <end_date>
# dates are optional and in format YYYYMMDD
# if dates are not given the script will work out the last year that has been processed and check what has been done
# already from 1st Jan of that last year up to the current day
#------------------------------------------------------------------------------------------------
# Optional flag: --force (delete existing aggregates before conversion)
FORCE_OVERWRITE=0
if [[ "$1" == "--force" ]]; then
    FORCE_OVERWRITE=1
    shift
fi

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
if [ -z "$SCRIPT_DIR" ]; then
    echo "ERROR: failed to resolve script directory from $SCRIPT_PATH"
    exit 1
fi
CONVERT_SCRIPT="${SCRIPT_DIR}/convert_and_aggregate.sh"
if [ ! -x "$CONVERT_SCRIPT" ]; then
    echo "ERROR: convert_and_aggregate.sh not found or not executable at $CONVERT_SCRIPT"
    exit 1
fi
# find index of requested radar in $1
RADAR=$1
if [ -z "$RADAR" ] || [[ "${RADAR,,}" == "all" ]]
then
    echo "No radar specified; running all radars: ${RADARS[*]}"
    for r in "${RADARS[@]}"; do
        "$0" "$r" "${@:2}"
    done
    exit 0
fi
RADAR_NUM=-1
for i in "${!RADARS[@]}" # the ! makes it give indices starting at 0
do
    if [[ ${RADARS[i]} = $RADAR ]]
    then
        RADAR_NUM=${RADAR_NUMS[i]}
        break
    fi
done
if [ $RADAR_NUM -eq -1 ]
then
    echo 'no such radar' $RADAR
    exit 1
fi

echo $RADAR $RADAR_NUM

DEFAULT_CONDA_ENV=/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod
USER_CONDA_ENV=$2
USER_FIRST_DATE=$3
USER_END_DATE=$4

# Allow skipping the env argument if $2 looks like a YYYYMMDD date
if [[ -n "$USER_CONDA_ENV" && "$USER_CONDA_ENV" =~ ^[0-9]{8}$ ]]; then
    FIRST_DATE=$USER_CONDA_ENV
    CONDA_ENV=$DEFAULT_CONDA_ENV
    if [[ -n "$USER_FIRST_DATE" && "$USER_FIRST_DATE" =~ ^[0-9]{8}$ ]]; then
        END_DATE=$USER_FIRST_DATE
    fi
else
    CONDA_ENV=${USER_CONDA_ENV:-$DEFAULT_CONDA_ENV}
    if [[ -n "$USER_FIRST_DATE" && "$USER_FIRST_DATE" =~ ^[0-9]{8}$ ]]; then
        FIRST_DATE=$USER_FIRST_DATE
    fi
    if [[ -n "$USER_END_DATE" && "$USER_END_DATE" =~ ^[0-9]{8}$ ]]; then
        END_DATE=$USER_END_DATE
    fi
fi
if [ -z "$CONDA_ENV" ]; then
    echo 'no conda environment specified. Usage convert_all_files.sh <radar> [conda_env] [first_date] [end_date]'
    exit 1
fi
# allow user to pass full python path; normalize to env root
if [[ "$CONDA_ENV" =~ /bin/python$ ]]; then
    CONDA_ENV=${CONDA_ENV%/bin/python}
fi
PYTHON_BIN="${CONDA_ENV}/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "conda environment not found or missing python at ${PYTHON_BIN}"
    exit 1
fi

INDIR_BY_YEAR=/badc/ukmo-nimrod/data/single-site/storage_by_year
INDIR_FLAT=/badc/ukmo-nimrod/data/single-site
BASE_DIR=${BASE_DIR_OVERRIDE:-/work/scratch-pw5/rrniii/ukmo-nimrod}
OUT_BASE=${OUT_BASE_OVERRIDE:-${BASE_DIR}/raw_h5_data_final/single-site}
SCRATCH_BASE=${SCRATCH_BASE_OVERRIDE:-${BASE_DIR}/tmp_raw_radar}
OUTDIR=${OUT_BASE%/}/
SCRATCH=${SCRATCH_BASE%/}
RADAR_OUTDIR=${OUTDIR}${RADAR}
echo 'radar outdir' $RADAR_OUTDIR

# Allow overriding SLURM destination without editing the script
PARTITION=${SLURM_PARTITION_OVERRIDE:-standard}
QOS=${SLURM_QOS_OVERRIDE:-standard}
EXCLUDE=${SLURM_EXCLUDE_OVERRIDE:-}
# Allow longer SLURM time limits without editing the script.
TIME_LIMIT=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
EXCLUDE_ARG=""
if [ -n "$EXCLUDE" ]; then
    EXCLUDE_ARG="--exclude=${EXCLUDE}"
fi

# Enable HDF5 integrity checks for existing aggregates (1=on, 0=off).
H5_VERIFY=${H5_VERIFY:-1}
H5LS_BIN=$(command -v h5ls 2>/dev/null || true)

# Force re-creation of existing aggregate files (1=on, 0=off).
FORCE_OVERWRITE=${FORCE_OVERWRITE:-0}

if [ -n "$FIRST_DATE" ]
then
    echo 'using first date' $FIRST_DATE
elif [ $# -gt 2 ]
then
    FIRST_DATE=$3
    echo 'using first date' $FIRST_DATE
else
    echo 'finding years done'
    # assign subdirs which are years into array
    YEARS_DONE=($(get_subdirs $RADAR_OUTDIR))
    NYEARS_DONE=${#YEARS_DONE[@]}
    if [ $NYEARS_DONE -gt 0 ]
    then
       LAST_YEAR_DONE=${YEARS_DONE[$(( NYEARS_DONE-1))]}
       echo 'nyears done' $NYEARS_DONE
       echo 'last year done is' $LAST_YEAR_DONE
       FIRST_DATE=$(date -d $(date -d "${LAST_YEAR_DONE}0101" +"%Y%m%d") +"%Y%m%d") # first date to check
    else
       echo 'no years done please specify first date'
       exit 1
    fi
fi

END_DATE=${END_DATE:-$(date +"%Y%m%d")} # cap processing (inclusive); defaults to today
if ! [[ "$END_DATE" =~ ^[0-9]{8}$ ]]; then
    echo 'end date must be YYYYMMDD'
    exit 1
fi
if [ "$END_DATE" -lt "$FIRST_DATE" ]; then
    echo "end date $END_DATE is before first date $FIRST_DATE"
    exit 1
fi

this_date=$FIRST_DATE
CURRENT_DATE=$END_DATE
echo 'using end date' $CURRENT_DATE
echo 'starting with' $this_date
NDAYS=$(( 1 + ($(date -d $CURRENT_DATE +%s) - $(date -d $FIRST_DATE +%s)) / (24*3600) ))
echo $NDAYS days
for ((i=1; i<=NDAYS; i++))
do
    y=$(date -d $this_date "+%Y")
    m=$(date -d $this_date "+%m")
    d=$(date -d $this_date "+%d")
    AGG_FOLDER=${RADAR_OUTDIR}/${y}
    if [ ! -d "$AGG_FOLDER" ]
    then
        mkdir -p "$AGG_FOLDER"
        echo 'mkdir' "$AGG_FOLDER"
    fi
    AGG_FILE=$AGG_FOLDER/${y}${m}${d}_polar_pl_radar${RADAR_NUM}_aggregate.h5
    if [ -f "$AGG_FILE" ] && [ "$FORCE_OVERWRITE" -eq 1 ]; then
        echo "FORCE overwrite requested for existing file: $AGG_FILE"
    fi
    if [ -f "$AGG_FILE" ] && [ "$FORCE_OVERWRITE" -eq 0 ] && [ "$H5_VERIFY" -eq 1 ] && [ -n "$H5LS_BIN" ]; then
        if ! "$H5LS_BIN" "$AGG_FILE" >/dev/null 2>&1; then
            echo "HDF5 check failed, removing corrupt file: $AGG_FILE"
            rm -f "$AGG_FILE"
        fi
    fi
    if [ ! -f "$AGG_FILE" ] || [ "$FORCE_OVERWRITE" -eq 1 ]; then
        echo "h5 file for $RADAR $this_date does not exist. Trying conversion..."
        INPUT_SP_BY="${INDIR_BY_YEAR}/${y}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${y}${m}${d}_raw-dual-polar-augzdr-sp.dat.gz.tar"
        INPUT_LP_BY="${INDIR_BY_YEAR}/${y}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${y}${m}${d}_raw-dual-polar-augzdr-lp.dat.gz.tar"
        INPUT_SP_FLAT="${INDIR_FLAT}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${y}${m}${d}_raw-dual-polar-augzdr-sp.dat.gz.tar"
        INPUT_LP_FLAT="${INDIR_FLAT}/${RADAR}/raw-dual-polar/${y}/metoffice-c-band-rain-radar_${RADAR}_${y}${m}${d}_raw-dual-polar-augzdr-lp.dat.gz.tar"

        INPUT_SP=""
        INPUT_LP=""
        if [ -f "$INPUT_SP_BY" ] || [ -f "$INPUT_LP_BY" ]; then
            INPUT_SP="$INPUT_SP_BY"
            INPUT_LP="$INPUT_LP_BY"
        elif [ -f "$INPUT_SP_FLAT" ] || [ -f "$INPUT_LP_FLAT" ]; then
            INPUT_SP="$INPUT_SP_FLAT"
            INPUT_LP="$INPUT_LP_FLAT"
        fi
        if [ ! -f "$INPUT_SP" ] && [ ! -f "$INPUT_LP" ]; then
            echo "No Input Data"
        else
            echo "Input Data Exists."
            if [ ! -f "$INPUT_SP" ]; then echo "No SP Input Data"; fi;
            if [ ! -f "$INPUT_LP" ]; then echo "No LP Input Data"; fi;
            if  [ -f "$INPUT_SP" ] && [ -f "$INPUT_LP" ]; then
                if [ -f "$AGG_FILE" ] && [ "$FORCE_OVERWRITE" -eq 1 ]; then
                    echo "FORCE overwrite enabled and input exists; removing existing file: $AGG_FILE"
                    rm -f "$AGG_FILE"
                fi
                # create tmp folders
                TMP_FOLDER=${SCRATCH}/${RADAR}/${y}${m}${d}/extracted
                echo 'tmp folder' $TMP_FOLDER
                if [ ! -d "$TMP_FOLDER" ]
                then
                    mkdir -p "$TMP_FOLDER"
                    echo 'mkdir' "$TMP_FOLDER"
                fi
                SLURM_OUTS=${SCRATCH}/${RADAR}/${y}${m}${d}/slurm_outs
                echo 'slurm out folder' $SLURM_OUTS
                if [ ! -d "$SLURM_OUTS" ]
                then
                    mkdir -p "$SLURM_OUTS"
                    echo 'mkdir' "$SLURM_OUTS"
                fi
                # kick off job to convert each file to ODIM and aggregate into 1 file
                JOB_STR=`sbatch --account=ncas_radar --partition=${PARTITION} --qos=${QOS} --time=${TIME_LIMIT} ${EXCLUDE_ARG} -o ${SLURM_OUTS}/convert.out -e ${SLURM_OUTS}/convert.err --job-name=${RADAR_NUM}_${y}${m}${d} --wrap="${CONVERT_SCRIPT} -r ${RADAR} -y ${y} -m ${m} -d ${d} -t ${TMP_FOLDER} -o ${AGG_FILE} -c ${CONDA_ENV}"`
                JOB1=${JOB_STR//[![:digit:]]}               
                echo 'kicked off slurm job' $JOB1 'for' $RADAR $y/$m/$d

            fi
        fi
    else
        echo $AGG_FILE 'already exists'
    fi

    # go to next date
    this_date=$(date +"%Y%m%d" -d "$this_date + 1 day")
done
