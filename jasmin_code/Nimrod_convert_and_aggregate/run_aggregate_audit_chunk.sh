#!/bin/bash
set -euo pipefail

if [ -n "${NIMROD_CODE_DIR:-}" ]; then
    SCRIPT_DIR="$NIMROD_CODE_DIR"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
fi
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
RUN_DIR=${RUN_DIR:?RUN_DIR is required}
TASK_ID=${SLURM_ARRAY_TASK_ID:-${1:-0}}
CHUNK=$(printf "%s/chunks/chunk_%05d.txt" "$RUN_DIR" "$TASK_ID")
OUT=$(printf "%s/results/chunk_%05d.tsv" "$RUN_DIR" "$TASK_ID")

if [ ! -s "$CHUNK" ]; then
    echo "missing chunk: $CHUNK" >&2
    exit 2
fi

mkdir -p "$RUN_DIR/results"
if [ -s "$OUT" ] && tail -n +2 "$OUT" | grep -q .; then
    echo "already complete: $OUT"
    exit 0
fi

"$ENV/bin/python" "$SCRIPT_DIR/audit_aggregate_file_health.py" \
    --manifest "$CHUNK" \
    --output "$OUT" \
    ${READ_PROBE:+--read-probe} \
    ${DEEP_QUANTITIES:+--deep-quantities}
