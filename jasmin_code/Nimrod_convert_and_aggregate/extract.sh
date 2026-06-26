#!/bin/bash

#
# This script acts as a wrapper for Nimrod HDF5 conversion, untarring data of requested pulse mode and zdr mode from
# one day
#


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
  echo "    -d    Date, DD. Required"
  echo "    -t    Folder for temporary storage of extracted raw data. Required"
  echo "    -p    Pulse mode - l, s or b (both). Optional, default l"
  echo "    -z    ZDR or LDR - z, l or b (both). Optional, default z"
  echo "    -h    Prints this help message and exits"
  echo
  exit 1
}

######################
# Read in CL options #
######################

while getopts "r:y:m:d:t:p:z:h" opt
do
  case $opt in
    r) radar_name=$OPTARG ;;
    y) year=$OPTARG ;;
    m) month=$OPTARG ;;
    d) date=$OPTARG ;;
    t) tmp_folder=$OPTARG ;;
    p) pulse_mode=$OPTARG ;;
    z) zdr_mode=$OPTARG ;;
    h) display_help
       exit 0 ;;
    [?]) display_help
         exit 0 ;;
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
  exit 0
fi

if [ -z "$year" ]
then
  echo 
  echo "ERROR: Year not specified!"
  display_help
  exit 0
fi

if [ -z "$month" ]
then
  echo
  echo "ERROR: Month not specified!"
  display_help
  exit 0
fi

if [ -z "$date" ]
then
  echo
  echo "ERROR: Date not specified!"
  display_help
  exit 0
fi

if [ -z "$tmp_folder" ]
then
  echo
  echo "ERROR: tmp_folder not specified!"
  display_help
  exit 0
fi

if [ -z "$pulse_mode" ]
then
  pulse_mode=l
fi

if [ -z "$zdr_mode" ]
then
  zdr_mode=z
fi

##################################
# Extract raw data to tmp_folder #
##################################

echo "Untarring" /badc/ukmo-nimrod/data/single-site/${radar_name}/raw-dual-polar/${year}/metoffice-c-band-rain-radar_${radar_name}_${year}${month}${date}

INDIR_BY_YEAR=/badc/ukmo-nimrod/data/single-site/storage_by_year
INDIR_FLAT=/badc/ukmo-nimrod/data/single-site
full_date=${year}${month}${date}
extracted_count=0

find_input_file() {
  local mode=$1
  local candidate_by_year="${INDIR_BY_YEAR}/${year}/${radar_name}/raw-dual-polar/${year}/metoffice-c-band-rain-radar_${radar_name}_${full_date}_raw-dual-polar-${mode}.dat.gz.tar"
  local candidate_flat="${INDIR_FLAT}/${radar_name}/raw-dual-polar/${year}/metoffice-c-band-rain-radar_${radar_name}_${full_date}_raw-dual-polar-${mode}.dat.gz.tar"

  if [ -f "$candidate_by_year" ]; then
    printf '%s\n' "$candidate_by_year"
  elif [ -f "$candidate_flat" ]; then
    printf '%s\n' "$candidate_flat"
  fi
}

extract_if_available() {
  local mode=$1
  local input_file
  input_file=$(find_input_file "$mode")
  if [ -z "$input_file" ]; then
    echo "No input tar for ${mode}"
    return 0
  fi
  echo "Extracting ${input_file}"
  if tar -xf "$input_file" -C "$tmp_folder"; then
    extracted_count=$((extracted_count + 1))
    return 0
  fi
  echo "ERROR! Failed to extract ${input_file}"
  return 1
}

if [ ${zdr_mode} == b ]
then
  if [ ${pulse_mode} == b ] || [ ${pulse_mode} == l ] 
  then
      extract_if_available augzdr-lp || exit 1
      extract_if_available augldr-lp || exit 1
  fi
  if [ ${pulse_mode} == b ] || [ ${pulse_mode} == s ] 
  then
      extract_if_available augzdr-sp || exit 1
  fi
elif [ ${zdr_mode} == z ]
then
  if [ ${pulse_mode} == b ] || [ ${pulse_mode} == l ] 
  then
      extract_if_available augzdr-lp || exit 1
  fi
  if [ ${pulse_mode} == b ] || [ ${pulse_mode} == s ] 
  then
      extract_if_available augzdr-sp || exit 1
  fi
elif [ ${zdr_mode} == l ]
then
  if [ ${pulse_mode} == b ] || [ ${pulse_mode} == l ] 
  then
      extract_if_available augldr-lp || exit 1
  fi
  if [ ${pulse_mode} == s ] 
  then
      echo "ERROR! No short pulse with LDR!"
      echo "Exiting..."
      exit 0
  fi
else
  echo "ERROR! Incorrect zdr mode - ${zdr_mode}"
  echo "Exiting..."
  exit 0
fi

if [ "$extracted_count" -eq 0 ]; then
  echo "ERROR! No input tars extracted"
  exit 1
fi
