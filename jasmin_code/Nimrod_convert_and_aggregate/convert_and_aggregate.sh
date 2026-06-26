#!/bin/bash

#
# This script acts as a wrapper for Nimrod HDF5 conversion, converting and aggregating all .gz files in tmp_folder. 
# This should be run as a SLURM job. 
#

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
if [ -z "$SCRIPT_DIR" ]; then
  echo "ERROR: failed to resolve script directory from $SCRIPT_PATH"
  exit 2
fi
EXTRACT_SCRIPT="${SCRIPT_DIR}/extract.sh"
CONVERT_PY="${SCRIPT_DIR}/convert_and_aggregate.py"
CONV_PY_PATH="${SCRIPT_DIR}/Radar_ODIM_conv"
if [ ! -x "$EXTRACT_SCRIPT" ]; then
  echo "ERROR: extract.sh not found or not executable at $EXTRACT_SCRIPT"
  exit 2
fi
if [ ! -f "$CONVERT_PY" ]; then
  echo "ERROR: convert_and_aggregate.py not found at $CONVERT_PY"
  exit 2
fi
if [ ! -d "$CONV_PY_PATH" ]; then
  echo "ERROR: Radar_ODIM_conv not found at $CONV_PY_PATH"
  exit 2
fi

#####################
# Command line help #
#####################
display_help() {
  echo
  echo "Usage: "$(basename "${0}")" [options...]"
  echo
  echo "    -r    Radar name. Required"
  echo "    -y    Year, YYYY. Required"
  echo "    -m    Month, MM. Required"
  echo "    -d    Day, DD. Required"
  echo "    -t    Folder for temporary storage of extracted raw data. Required"
  echo "    -o    Output file. Required"
  echo "    -c    conda environment. Required"
  echo "    -h    Prints this help message and exits"
  echo
  exit 1
}
CURRENT_DATETIME=$(date +"%d/%m/%Y %H:%M") # get current date
echo $CURRENT_DATETIME ': starting conversion'

######################
# Read in CL options #
######################

while getopts "r:y:m:d:t:o:c:h" opt
do
  case $opt in
    r) radar_name=$OPTARG ;;
    y) year=$OPTARG ;;
    m) month=$OPTARG ;;
    d) day=$OPTARG ;;
    t) tmp_folder=$OPTARG ;;
    o) out_file=$OPTARG ;;
    c) conda_env=$OPTARG ;;
    h) display_help
       exit 1 ;;
    [?]) display_help
         exit 1 ;;
  esac
done

shift "$((OPTIND-1))"

#####################################
# Set defaults and check CL options #
#####################################

if [ -z "$radar_name" ]
then
  echo
  echo "ERROR: Radar name not specified!"
  display_help
  exit 1
fi

if [ -z "$year" ]
then
  echo 
  echo "ERROR: Year not specified!"
  display_help
  exit 1
fi

if [ -z "$month" ]
then
  echo
  echo "ERROR: Month not specified!"
  display_help
  exit 1
fi

if [ -z "$day" ]
then
  echo
  echo "ERROR: Day not specified!"
  display_help
  exit 1
fi

if [ -z "$tmp_folder" ]
then
  echo
  echo "ERROR: tmp_folder not specified!"
  display_help
  exit 1
fi

if [ -z "$out_file" ]
then
  echo
  echo "ERROR: out_file not specified!"
  display_help
  exit 1
fi

# Skip work if output already exists.
if [ -f "$out_file" ]; then
  echo "$CURRENT_DATETIME : output exists, skipping $out_file"
  exit 0
fi

if [ -z "$conda_env" ]
then
  echo
  echo "ERROR: conda_env not specified!"
  display_help
  exit 1
fi

##############################################################
# untar the required files
"${EXTRACT_SCRIPT}" -r ${radar_name} -y ${year} -m ${month} -d ${day} -t ${tmp_folder} -p b -z z 

##############################################################
# convert and aggregate each of the untarred files in out_file
##############################################################
export PYTHONPATH="${CONV_PY_PATH}"
# Suppress noisy divide-by-zero warnings from Radar_ODIM_conv (non-fatal).
export PYTHONWARNINGS="ignore:divide by zero encountered in log10:RuntimeWarning"
# Compress ODIM data arrays by default to reduce output size.
export H5_DATA_COMPRESSION="${H5_DATA_COMPRESSION:-gzip}"
export H5_DATA_COMPRESSION_LEVEL="${H5_DATA_COMPRESSION_LEVEL:-4}"
export H5_DATA_SHUFFLE="${H5_DATA_SHUFFLE:-1}"
${conda_env}/bin/python "${CONVERT_PY}" ${tmp_folder} ${out_file} ${radar_name}
exit_status=$?
CURRENT_DATETIME=$(date +"%d/%m/%Y %H:%M") # get current date
if [ "${exit_status}" -eq 0 ]
then
    echo $CURRENT_DATETIME ": converted and aggregated" $out_file
    # Clean extracted files to free scratch space.
    if [ -n "$tmp_folder" ] && [ -d "$tmp_folder" ]; then
        rm -rf "${tmp_folder:?}/"*
        rmdir "$tmp_folder" 2>/dev/null || true
    fi
    date_dir="$(dirname "$tmp_folder")"
    echo $CURRENT_DATETIME ": tmp_raw_radar cleaned for ${date_dir}"
else
    echo $CURRENT_DATETIME ":conversion failed" $out_file, "error" $exit_status
    exit $exit_status
fi
