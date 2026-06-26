#!/usr/bin/env bash
set -euo pipefail

TOOLKIT_DIR="${TOOLKIT_DIR:-$HOME/uk-wsr-visualizer}"
DATA_DIR="${DATA_DIR:-data/uk-wsr-visualizer}"
STATE_DIR="${STATE_DIR:-$DATA_DIR/object-store/backfill/all-available-both}"
PAIR_LIST="${PAIR_LIST:-$TOOLKIT_DIR/$STATE_DIR/available-radar-years.txt}"
RUNNER="${RUNNER:-deploy/bin/uk-wsr-visualizer-jasmin-backfill-both-parallel.sh}"

if [ -z "${SLURM_ARRAY_TASK_ID:-}" ]; then
  echo "SLURM_ARRAY_TASK_ID is not set" >&2
  exit 2
fi

cd "$TOOLKIT_DIR"

pair="$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$PAIR_LIST" 2>/dev/null || true)"
if [ -z "$pair" ]; then
  echo "No radar/year pair for SLURM_ARRAY_TASK_ID=${SLURM_ARRAY_TASK_ID}" >&2
  exit 2
fi

read -r radar year _extra <<EOF
$pair
EOF

if [ -z "${radar:-}" ] || [ -z "${year:-}" ]; then
  echo "Invalid pair line for task ${SLURM_ARRAY_TASK_ID}: ${pair}" >&2
  exit 2
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) LOTUS task ${SLURM_ARRAY_JOB_ID:-na}.${SLURM_ARRAY_TASK_ID} ${radar} ${year} on $(hostname -f 2>/dev/null || hostname)"

env \
  RUN_SINGLE_PAIR=1 \
  PAIR_RADAR="$radar" \
  PAIR_YEAR="$year" \
  CONCURRENCY=1 \
  PUBLISH_AFTER_PAIR="${PUBLISH_AFTER_PAIR:-0}" \
  RAW_VOLUME_AWS_DIRECTORY_COMMAND="${RAW_VOLUME_AWS_DIRECTORY_COMMAND:-sync}" \
  RAW_VOLUME_AWS_EXTRA_ARGS="${RAW_VOLUME_AWS_EXTRA_ARGS:---no-progress}" \
  RAW_VOLUME_SKIP_PUBLIC_HEAD="${RAW_VOLUME_SKIP_PUBLIC_HEAD:-1}" \
  AWS_MAX_ATTEMPTS="${AWS_MAX_ATTEMPTS:-10}" \
  bash "$RUNNER"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) LOTUS task complete ${radar} ${year}"
