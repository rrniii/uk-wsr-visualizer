#!/usr/bin/env bash
set -euo pipefail

REPO=${REPO:-/home/users/rrniii/uk-wsr-visualizer}
NIMROD_DIR=${NIMROD_DIR:-/home/users/rrniii/bin/Nimrod_convert_and_aggregate}
PY=${PY:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod/bin/python}
RUN_BASE=${RUN_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/integrity-checks}
RUN_STAMP=${RUN_STAMP:-integrity_$(date -u +%Y%m%dT%H%M%SZ)}
RUN_DIR=${RUN_DIR:-${RUN_BASE}/${RUN_STAMP}}
RAW_BY_YEAR=${RAW_BY_YEAR:-/badc/ukmo-nimrod/data/single-site/storage_by_year}
RAW_FLAT=${RAW_FLAT:-/badc/ukmo-nimrod/data/single-site}
AGGREGATE_ROOT=${AGGREGATE_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
PVOL_ROOT=${PVOL_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site}
CRON_LOG_DIR=${CRON_LOG_DIR:-/gws/ssde/j25a/ncas_radar/vol2/avocet/daily_update_logs}
BLOCK_FILE=${BLOCK_FILE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/nimrod_daily_update.block}
AGG_WORKERS=${AGG_WORKERS:-6}
PVOL_WORKERS=${PVOL_WORKERS:-8}
AGG_COMPRESSION_SAMPLE=${AGG_COMPRESSION_SAMPLE:-8}
PVOL_COMPRESSION_SAMPLE=${PVOL_COMPRESSION_SAMPLE:-4}
AGG_READ_PROBE=${AGG_READ_PROBE:-0}
AGG_DEEP_QUANTITIES=${AGG_DEEP_QUANTITIES:-0}
WAIT_FOR_AGGREGATE_IDLE=${WAIT_FOR_AGGREGATE_IDLE:-1}
WAIT_FOR_BIORAD_IDLE=${WAIT_FOR_BIORAD_IDLE:-1}
WAIT_FOR_PVOL_UPLOAD=${WAIT_FOR_PVOL_UPLOAD:-1}
POLL_SECONDS=${POLL_SECONDS:-300}
SKIP_AGGREGATE=${SKIP_AGGREGATE:-0}
SKIP_PVOL=${SKIP_PVOL:-0}
FORCE=${FORCE:-0}

mkdir -p "$RUN_DIR"/logs "$RUN_DIR"/aggregate "$RUN_DIR"/pvol
cd "$REPO"

export PYTHONPATH="${REPO}/src:${PYTHONPATH:-}"
export HDF5_USE_FILE_LOCKING=FALSE

active_checker_processes() {
    pgrep -u "$USER" -af 'tools/jasmin_integrity_audit/(aggregate_integrity_audit.py|pvol_integrity_audit.py)|run_aggregate_checker_after_idle.sh|run_pvol_checker_after_idle.sh' 2>/dev/null |
        grep -v "$$" |
        grep -v 'launch_integrity_checkers.sh' || true
}

if [ "$FORCE" != "1" ] && [ -n "$(active_checker_processes)" ]; then
    echo "active integrity checker already running; use FORCE=1 only if you intentionally want overlap"
    active_checker_processes
    exit 0
fi

cat > "$RUN_DIR/environment.txt" <<EOF
started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host=$(hostname -f 2>/dev/null || hostname)
repo=$REPO
nimrod_dir=$NIMROD_DIR
python=$PY
run_dir=$RUN_DIR
raw_by_year=$RAW_BY_YEAR
raw_flat=$RAW_FLAT
aggregate_root=$AGGREGATE_ROOT
pvol_root=$PVOL_ROOT
agg_workers=$AGG_WORKERS
pvol_workers=$PVOL_WORKERS
wait_for_aggregate_idle=$WAIT_FOR_AGGREGATE_IDLE
wait_for_biorad_idle=$WAIT_FOR_BIORAD_IDLE
wait_for_pvol_upload=$WAIT_FOR_PVOL_UPLOAD
EOF

EXPECTED="$RUN_DIR/expected_raw_available_manifest.tsv"
"$PY" tools/jasmin_integrity_audit/build_expected_raw_manifest.py \
    --raw-by-year "$RAW_BY_YEAR" \
    --raw-flat "$RAW_FLAT" \
    --aggregate-root "$AGGREGATE_ROOT" \
    --output "$EXPECTED" \
    --summary "$RUN_DIR/expected_raw_available_summary.json" \
    > "$RUN_DIR/logs/build_expected_raw_manifest.log" 2>&1

export REPO NIMROD_DIR PY RUN_BASE RUN_STAMP RUN_DIR RAW_BY_YEAR RAW_FLAT
export AGGREGATE_ROOT PVOL_ROOT CRON_LOG_DIR BLOCK_FILE EXPECTED
export AGG_WORKERS PVOL_WORKERS AGG_COMPRESSION_SAMPLE PVOL_COMPRESSION_SAMPLE
export AGG_READ_PROBE AGG_DEEP_QUANTITIES WAIT_FOR_AGGREGATE_IDLE WAIT_FOR_BIORAD_IDLE WAIT_FOR_PVOL_UPLOAD
export POLL_SECONDS

cat > "$RUN_DIR/run_aggregate_checker_after_idle.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
active_aggregate_jobs() {
  command -v squeue >/dev/null 2>&1 || { echo 0; return; }
  squeue -u "$USER" -h -o '%j' | awk '$1 ~ /^[0-9]{2}_[0-9]{8}(_r12h)?$/ {n++} END{print n+0}'
}
active_aggregate_processes() {
  (pgrep -u "$USER" -af 'run_full_compressed_rewrite.sh|submit_repair_candidates(_force)?\.sh|convert_all_files.sh|run_slurm_forced_repair_one.sh' 2>/dev/null || true) |
    grep -v "$$" | wc -l
}
if [ "${WAIT_FOR_AGGREGATE_IDLE}" = "1" ]; then
  while true; do
    jobs=$(active_aggregate_jobs)
    procs=$(active_aggregate_processes)
    log "waiting_for_aggregate_idle jobs=${jobs} processes=${procs}"
    [ "$jobs" -eq 0 ] && [ "$procs" -eq 0 ] && break
    sleep "$POLL_SECONDS"
  done
fi
args=(
  tools/jasmin_integrity_audit/aggregate_integrity_audit.py
  --aggregate-root "$AGGREGATE_ROOT"
  --expected-manifest "$EXPECTED"
  --nimrod-code-dir "$NIMROD_DIR"
  --cron-log-dir "$CRON_LOG_DIR"
  --block-file "$BLOCK_FILE"
  --run-dir "$RUN_DIR/aggregate"
  --workers "$AGG_WORKERS"
  --compression-sample "$AGG_COMPRESSION_SAMPLE"
  --progress-every 250
)
[ "$AGG_READ_PROBE" = "1" ] && args+=(--read-probe)
[ "$AGG_DEEP_QUANTITIES" = "1" ] && args+=(--deep-quantities)
log "starting aggregate integrity audit"
exec "$PY" "${args[@]}"
EOF
chmod +x "$RUN_DIR/run_aggregate_checker_after_idle.sh"

cat > "$RUN_DIR/run_pvol_checker_after_idle.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
active_biorad_jobs() {
  command -v squeue >/dev/null 2>&1 || { echo 0; return; }
  squeue -u "$USER" -h -o '%j' | awk 'tolower($0) ~ /biorad|vol2bird|vol2birdinput|pvol/ {n++} END{print n+0}'
}
active_pvol_upload_processes() {
  (pgrep -u "$USER" -af 'fast_pvol_upload_worker.py|aws .*s3 sync.*ukmo-nimrod/pvol' 2>/dev/null || true) |
    grep -v "$$" | wc -l
}
if [ "${WAIT_FOR_BIORAD_IDLE}" = "1" ]; then
  while true; do
    jobs=$(active_biorad_jobs)
    log "waiting_for_biorad_idle jobs=${jobs}"
    [ "$jobs" -eq 0 ] && break
    sleep "$POLL_SECONDS"
  done
fi
if [ "${WAIT_FOR_PVOL_UPLOAD}" = "1" ]; then
  while true; do
    procs=$(active_pvol_upload_processes)
    log "waiting_for_pvol_upload_idle processes=${procs}"
    [ "$procs" -eq 0 ] && break
    sleep "$POLL_SECONDS"
  done
fi
log "starting pvol integrity audit"
exec "$PY" tools/jasmin_integrity_audit/pvol_integrity_audit.py \
  --pvol-root "$PVOL_ROOT" \
  --expected-manifest "$EXPECTED" \
  --cron-log-dir "$CRON_LOG_DIR" \
  --block-file "$BLOCK_FILE" \
  --run-dir "$RUN_DIR/pvol" \
  --workers "$PVOL_WORKERS" \
  --compression-sample "$PVOL_COMPRESSION_SAMPLE" \
  --progress-every 10000
EOF
chmod +x "$RUN_DIR/run_pvol_checker_after_idle.sh"

cat > "$RUN_DIR/monitor.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "run_dir=$RUN_DIR"
echo "now=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -f "$RUN_DIR/pids.tsv" ]; then
  awk -F '\t' 'NR>1{print $1, $2, $3}' "$RUN_DIR/pids.tsv" |
    while read -r name pid log; do
      alive=$( (ps -p "$pid" -o pid= 2>/dev/null || true) | wc -l )
      echo "${name}_pid=${pid} alive=${alive} log=${log}"
    done
fi
for part in aggregate pvol; do
  echo "--- ${part}"
  if [ -f "$RUN_DIR/${part}/progress.json" ]; then
    python3 - "$RUN_DIR/${part}/progress.json" <<'PY'
import json, sys
data=json.load(open(sys.argv[1]))
for key in ("started_at","updated_at","finished_at","expected_done_days","actual_aggregate_files","pvol_files_scanned","pvol_days","scanned","bad","bad_or_compression_issue","missing_from_done_status","missing_days_from_done_status","extra_not_in_done_status","extra_days_not_in_done_status"):
    if key in data:
        print(f"{key}={data[key]}")
if "status_counts" in data:
    print("status_counts="+json.dumps(data["status_counts"], sort_keys=True))
if "top_issue_counts" in data:
    print("top_issue_counts="+json.dumps(data["top_issue_counts"], sort_keys=True))
PY
  else
    echo "progress=not_started"
  fi
  [ -f "$RUN_DIR/logs/${part}.log" ] && tail -5 "$RUN_DIR/logs/${part}.log" || true
done
EOF
chmod +x "$RUN_DIR/monitor.sh"

: > "$RUN_DIR/pids.tsv"
printf "name\tpid\tlog\n" > "$RUN_DIR/pids.tsv"

if [ "$SKIP_AGGREGATE" != "1" ]; then
    nohup "$RUN_DIR/run_aggregate_checker_after_idle.sh" > "$RUN_DIR/logs/aggregate.log" 2>&1 < /dev/null &
    printf "aggregate\t%s\t%s\n" "$!" "$RUN_DIR/logs/aggregate.log" >> "$RUN_DIR/pids.tsv"
fi

if [ "$SKIP_PVOL" != "1" ]; then
    nohup "$RUN_DIR/run_pvol_checker_after_idle.sh" > "$RUN_DIR/logs/pvol.log" 2>&1 < /dev/null &
    printf "pvol\t%s\t%s\n" "$!" "$RUN_DIR/logs/pvol.log" >> "$RUN_DIR/pids.tsv"
fi

ln -sfn "$RUN_DIR" "$RUN_BASE/latest"
printf 'run_dir=%s\nexpected_manifest=%s\nmonitor=%s\npids=%s\n' \
    "$RUN_DIR" "$EXPECTED" "$RUN_DIR/monitor.sh" "$RUN_DIR/pids.tsv"
