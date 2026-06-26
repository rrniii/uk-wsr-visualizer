#!/bin/bash
set -euo pipefail

RUN_DIR=${1:?Usage: summarize_aggregate_audit.sh <run-dir>}
RESULTS="$RUN_DIR/results"
MERGED="$RUN_DIR/aggregate_audit_merged.tsv"
STATUS_COUNTS="$RUN_DIR/status_counts.tsv"
REBUILD="$RUN_DIR/needs_rebuild_manifest.tsv"
MISSING_VARIABLES="$RUN_DIR/missing_variables_manifest.tsv"
GAP_BOUNDARY="$RUN_DIR/corrupt_gap_boundary_manifest.tsv"

first=1
: > "$MERGED"
for f in "$RESULTS"/chunk_*.tsv; do
    [ -f "$f" ] || continue
    if [ "$first" -eq 1 ]; then
        cat "$f" >> "$MERGED"
        first=0
    else
        tail -n +2 "$f" >> "$MERGED"
    fi
done

awk -F '\t' 'NR > 1 {count[$7]++} END {for (k in count) print k "\t" count[k]}' "$MERGED" | sort > "$STATUS_COUNTS"
awk -F '\t' 'NR == 1 || (NR > 1 && $7 != "ok")' "$MERGED" > "$REBUILD"
awk -F '\t' 'NR == 1 || (NR > 1 && $7 == "missing_variable")' "$MERGED" > "$MISSING_VARIABLES"
awk -F '\t' 'NR == 1 || (NR > 1 && $7 == "corrupt_gap_boundary")' "$MERGED" > "$GAP_BOUNDARY"

echo "merged=$MERGED"
echo "status_counts=$STATUS_COUNTS"
cat "$STATUS_COUNTS"
echo "needs_rebuild=$REBUILD"
echo "missing_variables=$MISSING_VARIABLES"
echo "corrupt_gap_boundary=$GAP_BOUNDARY"
