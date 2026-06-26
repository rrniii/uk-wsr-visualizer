#!/usr/bin/env bash
set -euo pipefail

TOOLKIT_DIR="${TOOLKIT_DIR:-$HOME/uk-wsr-visualizer}"
DATA_DIR="${DATA_DIR:-data/uk-wsr-visualizer}"
STATE_DIR="${STATE_DIR:-$DATA_DIR/object-store/backfill/all-available-both}"
RUNNER="${RUNNER:-deploy/bin/uk-wsr-visualizer-jasmin-backfill-both-parallel.sh}"
ARRAY_TASK="${ARRAY_TASK:-deploy/bin/uk-wsr-visualizer-jasmin-backfill-lotus-array-task.sh}"

LOTUS_ARRAY_CONCURRENCY="${LOTUS_ARRAY_CONCURRENCY:-6}"
SLURM_ACCOUNT="${SLURM_ACCOUNT:-ncas_radar}"
SLURM_PARTITION="${SLURM_PARTITION:-standard}"
SLURM_QOS="${SLURM_QOS:-standard}"
SLURM_TIME="${SLURM_TIME:-24:00:00}"
SLURM_MEM="${SLURM_MEM:-4G}"
SLURM_CPUS_PER_TASK="${SLURM_CPUS_PER_TASK:-1}"

cd "$TOOLKIT_DIR"
mkdir -p "$STATE_DIR/slurm"

DISCOVER_ONLY=1 bash "$RUNNER"

PAIR_LIST="$TOOLKIT_DIR/$STATE_DIR/available-radar-years.txt"
pair_count="$(awk 'NF >= 2 {count++} END {print count + 0}' "$PAIR_LIST")"
if [ "$pair_count" -lt 1 ]; then
  echo "No radar/year pairs found in $PAIR_LIST" >&2
  exit 1
fi

sbatch_args=(
  --job-name=ukwsr-backfill
  --account="$SLURM_ACCOUNT"
  --partition="$SLURM_PARTITION"
  --time="$SLURM_TIME"
  --mem="$SLURM_MEM"
  --cpus-per-task="$SLURM_CPUS_PER_TASK"
  --array="1-${pair_count}%${LOTUS_ARRAY_CONCURRENCY}"
  --output="$TOOLKIT_DIR/$STATE_DIR/slurm/%A_%a.out"
  --error="$TOOLKIT_DIR/$STATE_DIR/slurm/%A_%a.err"
  --export=ALL,TOOLKIT_DIR="$TOOLKIT_DIR",DATA_DIR="$DATA_DIR",STATE_DIR="$STATE_DIR",PAIR_LIST="$PAIR_LIST",PUBLISH_AFTER_PAIR=0
)
if [ -n "$SLURM_QOS" ]; then
  sbatch_args+=(--qos="$SLURM_QOS")
fi

array_submit="$(sbatch "${sbatch_args[@]}" "$ARRAY_TASK")"
array_job_id="$(printf '%s\n' "$array_submit" | awk '{print $NF}')"
echo "$array_submit"

publish_log="$TOOLKIT_DIR/$STATE_DIR/slurm/%j.publish.out"
publish_err="$TOOLKIT_DIR/$STATE_DIR/slurm/%j.publish.err"
publish_cmd="cd '$TOOLKIT_DIR' && PUBLISH_ONLY=1 bash '$RUNNER'"

publish_args=(
  --job-name=ukwsr-publish
  --account="$SLURM_ACCOUNT"
  --partition="$SLURM_PARTITION"
  --time=01:00:00
  --mem=4G
  --dependency="afterany:${array_job_id}"
  --output="$publish_log"
  --error="$publish_err"
  --export=ALL,TOOLKIT_DIR="$TOOLKIT_DIR",DATA_DIR="$DATA_DIR",STATE_DIR="$STATE_DIR"
  --wrap="$publish_cmd"
)
if [ -n "$SLURM_QOS" ]; then
  publish_args+=(--qos="$SLURM_QOS")
fi

publish_submit="$(sbatch "${publish_args[@]}")"
publish_job_id="$(printf '%s\n' "$publish_submit" | awk '{print $NF}')"
echo "$publish_submit"

cat >"$STATE_DIR/lotus-submission.json" <<EOF
{
  "submitted_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pair_count": ${pair_count},
  "array_concurrency": ${LOTUS_ARRAY_CONCURRENCY},
  "array_job_id": "${array_job_id}",
  "publish_job_id": "${publish_job_id}",
  "pair_list": "${PAIR_LIST}",
  "state_dir": "${TOOLKIT_DIR}/${STATE_DIR}"
}
EOF

echo "Wrote $STATE_DIR/lotus-submission.json"
