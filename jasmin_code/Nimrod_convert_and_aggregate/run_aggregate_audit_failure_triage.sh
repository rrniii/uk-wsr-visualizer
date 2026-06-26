#!/bin/bash
set -euo pipefail

SCRIPT_DIR=${NIMROD_CODE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
AUDIT=${AUDIT:?AUDIT is required}
OUT_DIR=${OUT_DIR:?OUT_DIR is required}

mkdir -p "$OUT_DIR"
"$ENV/bin/python" "$SCRIPT_DIR/triage_aggregate_audit_failures.py" \
    --audit "$AUDIT" \
    --out-dir "$OUT_DIR"
