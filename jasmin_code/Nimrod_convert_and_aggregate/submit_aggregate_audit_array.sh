#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
BASE=${BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
LOG_ROOT=${LOG_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/direct_repair_logs}
RUN_STAMP=${RUN_STAMP:-aggregate_audit_$(date -u +%Y%m%dT%H%M%SZ)}
RUN_DIR=${RUN_DIR:-$LOG_ROOT/$RUN_STAMP}
CHUNK_SIZE=${CHUNK_SIZE:-500}
ARRAY_CONCURRENCY=${ARRAY_CONCURRENCY:-500}
SLURM_TIME=${SLURM_TIME:-04:00:00}
SLURM_PARTITION=${SLURM_PARTITION:-standard}
SLURM_QOS=${SLURM_QOS:-standard}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
READ_PROBE=${READ_PROBE:-}
DEEP_QUANTITIES=${DEEP_QUANTITIES:-}

if ! [[ "$CHUNK_SIZE" =~ ^[0-9]+$ ]] || [ "$CHUNK_SIZE" -lt 1 ]; then
    echo "ERROR: CHUNK_SIZE must be a positive integer" >&2
    exit 1
fi
if ! [[ "$ARRAY_CONCURRENCY" =~ ^[0-9]+$ ]] || [ "$ARRAY_CONCURRENCY" -lt 1 ]; then
    echo "ERROR: ARRAY_CONCURRENCY must be a positive integer" >&2
    exit 1
fi
if [ "$ARRAY_CONCURRENCY" -gt 500 ]; then
    ARRAY_CONCURRENCY=500
fi

mkdir -p "$RUN_DIR/chunks" "$RUN_DIR/results" "$RUN_DIR/slurm"
MANIFEST="$RUN_DIR/aggregate_files.txt"
SUMMARY="$RUN_DIR/submit_summary.txt"

find "$BASE" -type f -name "*_aggregate.h5" | sort > "$MANIFEST"
split -d -a 5 -l "$CHUNK_SIZE" "$MANIFEST" "$RUN_DIR/chunks/chunk_"
for f in "$RUN_DIR"/chunks/chunk_*; do
    mv "$f" "$f.txt"
done
TASK_COUNT=$(find "$RUN_DIR/chunks" -maxdepth 1 -type f -name "chunk_*.txt" | wc -l)
FILE_COUNT=$(wc -l < "$MANIFEST")

{
    echo "run_stamp=$RUN_STAMP"
    echo "run_dir=$RUN_DIR"
    echo "base=$BASE"
    echo "manifest=$MANIFEST"
    echo "file_count=$FILE_COUNT"
    echo "chunk_size=$CHUNK_SIZE"
    echo "task_count=$TASK_COUNT"
    echo "array_concurrency=$ARRAY_CONCURRENCY"
    echo "slurm_time=$SLURM_TIME"
    echo "env=$ENV"
    echo "read_probe=$READ_PROBE"
    echo "deep_quantities=$DEEP_QUANTITIES"
} | tee "$SUMMARY"

if [ "$TASK_COUNT" -eq 0 ]; then
    echo "No aggregate files found" >&2
    exit 2
fi

LAST_TASK=$((TASK_COUNT - 1))
SBATCH_OUT=$(
    sbatch \
        --account=ncas_radar \
        --partition="$SLURM_PARTITION" \
        --qos="$SLURM_QOS" \
        --time="$SLURM_TIME" \
        --array="0-${LAST_TASK}%${ARRAY_CONCURRENCY}" \
        --job-name=agg_audit \
        -o "$RUN_DIR/slurm/%A_%a.out" \
        -e "$RUN_DIR/slurm/%A_%a.err" \
        --export="ALL,RUN_DIR=${RUN_DIR},ENV=${ENV},READ_PROBE=${READ_PROBE},DEEP_QUANTITIES=${DEEP_QUANTITIES},NIMROD_CODE_DIR=${SCRIPT_DIR}" \
        "$SCRIPT_DIR/run_aggregate_audit_chunk.sh"
)
JOB_ID=${SBATCH_OUT//[!0-9]/}
echo "job_id=$JOB_ID" | tee -a "$SUMMARY"
echo "submitted=$SBATCH_OUT" | tee -a "$SUMMARY"
echo "RUN_DIR=$RUN_DIR"
