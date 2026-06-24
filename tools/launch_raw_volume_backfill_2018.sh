#!/usr/bin/env bash
set -euo pipefail

REPO=${REPO:-/home/users/rrniii/avocet-radar-toolkit}
PY=${PY:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod/bin/python}
RUN_ROOT=${RUN_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/raw-volume-backfill}
LOG_DIR="${RUN_ROOT}/logs"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG="${LOG_DIR}/raw-volume-backfill-2018-${STAMP}.log"
PIDFILE="${RUN_ROOT}/raw-volume-backfill-2018.pid"

mkdir -p "${LOG_DIR}"
cd "${REPO}"

nohup env PYTHONPATH="${REPO}/src" "${PY}" "${REPO}/tools/raw_volume_object_store_backfill.py" \
  --radar chenies \
  --radar castor-bay \
  --radar clee-hill \
  --year 2018 \
  --run-root "${RUN_ROOT}" \
  --keep-going \
  > "${LOG}" 2>&1 < /dev/null &

printf '%s\n' "$!" > "${PIDFILE}"
printf 'pid=%s\nlog=%s\npidfile=%s\n' "$!" "${LOG}" "${PIDFILE}"
