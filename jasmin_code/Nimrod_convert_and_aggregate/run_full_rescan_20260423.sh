#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
OUT=${OUT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH=${SCRATCH:-/work/scratch-pw5/rrniii/ukmo-nimrod/tmp_raw_radar}
START=${START:-20130101}
END=${END:-$(date +"%Y%m%d")}
LOG=${LOG:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_catchup_${START}_to_${END}.log}

mkdir -p "$(dirname "$LOG")"

export H5_VERIFY="${H5_VERIFY:-1}"
export SLURM_TIME_LIMIT_OVERRIDE="${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}"
export OUT_BASE_OVERRIDE="$OUT"
export SCRATCH_BASE_OVERRIDE="$SCRATCH"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting full Nimrod rescan"
echo "env=$ENV"
echo "out=$OUT"
echo "scratch=$SCRATCH"
echo "date_range=${START}..${END}"
echo "h5_verify=$H5_VERIFY"
echo "slurm_time_limit=$SLURM_TIME_LIMIT_OVERRIDE"
echo "log=$LOG"
echo

(
  set -o pipefail
  ./convert_all_files.sh all "$ENV" "$START" "$END" |& tee -a "$LOG"
) &
rescan_pid=$!

echo "rescan_pid=$rescan_pid"
echo

while kill -0 "$rescan_pid" 2>/dev/null; do
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
  if command -v squeue >/dev/null 2>&1; then
    squeue -u "$USER" -h -o '%j %T' | awk '
      $1 ~ /^[0-9]{2}_[0-9]{8}(_r12h)?$/ {
        total++
        states[$2]++
      }
      END {
        print "slurm_total", total + 0
        for (state in states) {
          print state, states[state]
        }
      }
    '
  fi
  if [ -f "$LOG" ]; then
    echo "--- log tail ---"
    tail -n 20 "$LOG"
  fi
  echo
  sleep 300
done

wait "$rescan_pid"
status=$?

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] rescan finished with status=$status"
exit "$status"
