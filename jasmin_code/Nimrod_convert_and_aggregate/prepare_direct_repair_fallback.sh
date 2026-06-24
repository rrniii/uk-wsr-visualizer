#!/bin/bash

set -euo pipefail

RUN_STAMP=${RUN_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
LIST=${LIST:-/gws/ssde/j25a/ncas_radar/vol2/avocet/direct_repair_pending_thurnham_${RUN_STAMP}.tsv}
LATEST=${LATEST:-/gws/ssde/j25a/ncas_radar/vol2/avocet/direct_repair_pending_thurnham_latest.tsv}

printf 'job_id\tradar\tdate\n' > "$LIST"
squeue -u "$USER" -h -o '%i %j' |
    awk '$2 ~ /^20_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]$/ {printf "%s\tthurnham\t%s\n", $1, substr($2,4)}' |
    sort -k3,3 >> "$LIST"

ln -sfn "$LIST" "$LATEST"

tasks=$(awk 'NR > 1 {count++} END {print count + 0}' "$LIST")
echo "direct_list=$LIST"
echo "direct_latest=$LATEST"
echo "direct_tasks=$tasks"

if [ "$tasks" -gt 0 ]; then
    ids=$(awk 'NR > 1 {print $1}' "$LIST" | tr '\n' ' ')
    scontrol hold $ids
    echo "held_jobs=$tasks"
else
    echo "held_jobs=0"
fi

pids=$(pgrep -u "$USER" -f '^/bin/bash ./run_validate_and_vol2birdinput_after_aggregates.sh$' || true)
if [ -n "$pids" ]; then
    kill $pids
    echo "stopped_monitor_pids=$pids"
else
    echo "stopped_monitor_pids=none"
fi

sleep 2
echo "queue_after_hold"
squeue -u "$USER" -h -o '%i %T %R %j' |
    awk '$4 ~ /^20_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]$/ {c[$2 "|" $3]++} END {for (k in c) print c[k], k}' |
    sort -nr
