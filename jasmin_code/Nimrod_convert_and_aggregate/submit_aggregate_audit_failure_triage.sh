#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
AUDIT_RUN_DIR=${1:?Usage: submit_aggregate_audit_failure_triage.sh <audit-run-dir>}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
SLURM_TIME=${SLURM_TIME:-02:00:00}
SLURM_PARTITION=${SLURM_PARTITION:-standard}
SLURM_QOS=${SLURM_QOS:-standard}

AUDIT="$AUDIT_RUN_DIR/aggregate_audit_merged.tsv"
if [ ! -s "$AUDIT" ]; then
    echo "ERROR: missing merged audit file: $AUDIT" >&2
    exit 2
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="$AUDIT_RUN_DIR/failure_triage_$STAMP"
mkdir -p "$OUT_DIR/slurm"

SBATCH_OUT=$(
    sbatch \
        --account=ncas_radar \
        --partition="$SLURM_PARTITION" \
        --qos="$SLURM_QOS" \
        --time="$SLURM_TIME" \
        --job-name=agg_triage \
        -o "$OUT_DIR/slurm/%j.out" \
        -e "$OUT_DIR/slurm/%j.err" \
        --export="ALL,AUDIT=${AUDIT},OUT_DIR=${OUT_DIR},ENV=${ENV},NIMROD_CODE_DIR=${SCRIPT_DIR}" \
        "$SCRIPT_DIR/run_aggregate_audit_failure_triage.sh"
)
JOB_ID=${SBATCH_OUT//[!0-9]/}
{
    echo "audit_run_dir=$AUDIT_RUN_DIR"
    echo "audit=$AUDIT"
    echo "out_dir=$OUT_DIR"
    echo "job_id=$JOB_ID"
    echo "submitted=$SBATCH_OUT"
} | tee "$OUT_DIR/submit_summary.txt"
echo "OUT_DIR=$OUT_DIR"
