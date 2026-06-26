#!/bin/bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
cd "$SCRIPT_DIR"

RUN_DIR=${1:?Usage: monitor_canary_then_launch_full.sh <full_rewrite_run_dir>}
RUN_STAMP=$(basename "$RUN_DIR")
BASE=${BASE:-/gws/ssde/j25a/ncas_radar}
ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
OUT_BASE_OVERRIDE=${OUT_BASE_OVERRIDE:-$BASE/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site}
SCRATCH_BASE_OVERRIDE=${SCRATCH_BASE_OVERRIDE:-$BASE/vol2/avocet/tmp_raw_radar_repair}
MAX_ACTIVE=${MAX_ACTIVE:-500}
MIN_FREE_GB=${MIN_FREE_GB:-600}
SLEEP_SECONDS=${SLEEP_SECONDS:-120}
SLURM_TIME_LIMIT_OVERRIDE=${SLURM_TIME_LIMIT_OVERRIDE:-24:00:00}
SLURM_PARTITION_OVERRIDE=${SLURM_PARTITION_OVERRIDE:-standard}
SLURM_QOS_OVERRIDE=${SLURM_QOS_OVERRIDE:-standard}
SLURM_EXCLUDE_OVERRIDE=${SLURM_EXCLUDE_OVERRIDE:-}
H5_VERIFY=${H5_VERIFY:-1}
H5_COMPRESS=${H5_COMPRESS:-1}
H5_GZIP_LEVEL=${H5_GZIP_LEVEL:-4}
RAW_PRECHECK=${RAW_PRECHECK:-1}

CANARY=$RUN_DIR/canary_candidates.tsv
FULL=$RUN_DIR/full_rewrite_candidates.tsv
CANARY_STATUS=$RUN_DIR/forced_repair_status_${RUN_STAMP}_canary
FULL_STATUS=$RUN_DIR/forced_repair_status_${RUN_STAMP}_full
LOG=$RUN_DIR/canary_monitor_then_full.log
CANARY_PATHS=$RUN_DIR/canary_done_paths.txt
CANARY_AUDIT=$RUN_DIR/canary_post_rewrite_audit.tsv
COMPRESSION_CHECKS=$RUN_DIR/canary_compression_checks.tsv
FULL_MARKER=$RUN_DIR/full_submission_started.marker
ABORT_MARKER=$RUN_DIR/full_submission_blocked.marker
FULL_LOG=$RUN_DIR/nimrod_forced_repair_candidates_${RUN_STAMP}_full.log

H5LS_BIN=$(command -v h5ls 2>/dev/null || true)
PYTHON_BIN=${ENV%/}/bin/python

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG"
}

status_count() {
    local state=$1
    find "$CANARY_STATUS" -maxdepth 1 -type f -name "*.${state}" 2>/dev/null | wc -l
}

status_counts() {
    find "$CANARY_STATUS" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null |
        sed -n 's/.*\.//p' |
        sort |
        uniq -c |
        awk '{print $2 "=" $1}' |
        tr '\n' ' '
}

active_canary_jobs() {
    squeue -u "$USER" -h -o '%j' | awk '$1 ~ /^[0-9]{2}_[0-9]{8}$/ {n++} END{print n+0}'
}

fail_blocked() {
    log "BLOCKED: $*"
    {
        printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'reason=%s\n' "$*"
    } > "$ABORT_MARKER"
    exit 1
}

require_file() {
    if [ ! -f "$1" ]; then
        fail_blocked "missing required file: $1"
    fi
}

require_tool() {
    if [ -z "$2" ] || [ ! -x "$2" ]; then
        fail_blocked "missing required tool: $1"
    fi
}

manifest_count() {
    awk 'NR > 1 {n++} END {print n+0}' "$1"
}

write_canary_done_paths() {
    awk -F '\t' -v status_dir="$CANARY_STATUS" '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                col[$i] = i
            }
            next
        }
        {
            radar = $col["radar"]
            date = $col["date"]
            path = $col["path"]
            if (radar != "" && date != "" && path != "") {
                done_file = status_dir "/" radar "_" date ".done"
                if ((getline line < done_file) >= 0) {
                    print path
                }
                close(done_file)
            }
        }
    ' "$CANARY" > "$CANARY_PATHS"
}

check_compression() {
    "$PYTHON_BIN" - "$CANARY_PATHS" "$COMPRESSION_CHECKS" "$H5_GZIP_LEVEL" <<'PY'
import csv
import sys
from pathlib import Path

import h5py

paths_file = Path(sys.argv[1])
out_file = Path(sys.argv[2])
expected_level = int(sys.argv[3])


def representative_data_arrays(h5):
    for pulse in ("lp", "sp"):
        if pulse not in h5:
            continue
        pulse_group = h5[pulse]
        time_keys = sorted(
            key
            for key, value in pulse_group.items()
            if key.isdigit() and isinstance(value, h5py.Group)
        )
        for time_key in time_keys[:2]:
            time_group = pulse_group[time_key]
            dataset_keys = sorted(
                key
                for key, value in time_group.items()
                if key.startswith("dataset") and isinstance(value, h5py.Group)
            )
            for dataset_key in dataset_keys[:2]:
                dataset_group = time_group[dataset_key]
                data_keys = sorted(
                    key
                    for key, value in dataset_group.items()
                    if (key.startswith("data") or key.startswith("quality")) and isinstance(value, h5py.Group)
                )
                for data_key in data_keys:
                    data_path = f"{pulse}/{time_key}/{dataset_key}/{data_key}/data"
                    if data_path in h5 and isinstance(h5[data_path], h5py.Dataset):
                        yield data_path, h5[data_path]


bad = 0
with paths_file.open() as src, out_file.open("w", newline="") as dst:
    writer = csv.writer(dst, delimiter="\t", lineterminator="\n")
    writer.writerow(
        [
            "path",
            "h5_open_ok",
            "checked_datasets",
            "gzip_ok",
            "shuffle_ok",
            "level_ok",
            "details",
        ]
    )
    for raw in src:
        path = raw.strip()
        if not path:
            continue
        h5_open_ok = 0
        checked = 0
        gzip_ok = 1
        shuffle_ok = 1
        level_ok = 1
        details = []
        try:
            with h5py.File(path, "r") as h5:
                h5_open_ok = 1
                for data_path, data in representative_data_arrays(h5):
                    checked += 1
                    if data.compression != "gzip":
                        gzip_ok = 0
                        details.append(f"{data_path}:compression={data.compression}")
                    if not data.shuffle:
                        shuffle_ok = 0
                        details.append(f"{data_path}:shuffle={data.shuffle}")
                    if data.compression_opts != expected_level:
                        level_ok = 0
                        details.append(f"{data_path}:level={data.compression_opts}")
                    if checked >= 24:
                        break
        except Exception as exc:
            details.append(f"open_error:{type(exc).__name__}:{exc}")
        if not h5_open_ok or checked == 0 or not gzip_ok or not shuffle_ok or not level_ok:
            bad += 1
        writer.writerow(
            [
                path,
                h5_open_ok,
                checked,
                gzip_ok,
                shuffle_ok,
                level_ok,
                ";".join(details),
            ]
        )
raise SystemExit(1 if bad else 0)
PY
}

run_canary_audit() {
    "$PYTHON_BIN" "$SCRIPT_DIR/audit_aggregate_file_health.py" \
        --manifest "$CANARY_PATHS" \
        --output "$CANARY_AUDIT" \
        --deep-quantities \
        --progress-every 0
}

check_canary_audit() {
    awk -F '\t' '
        NR == 1 {
            for (i = 1; i <= NF; i++) {
                col[$i] = i
            }
            next
        }
        {
            if (
                $(col["status"]) != "ok" ||
                $(col["corrupt_gap_boundaries"]) != "" ||
                $(col["has_sqi"]) != "1" ||
                $(col["has_normalised_coherent_power"]) != "1"
            ) {
                bad++
            }
        }
        END {exit bad ? 1 : 0}
    ' "$CANARY_AUDIT"
}

submit_full() {
    if [ -f "$FULL_MARKER" ]; then
        log "full submission marker already exists; not submitting again"
        return 0
    fi
    log "canary passed compression and audit gates; submitting full rewrite"
    {
        printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf 'run_stamp=%s\n' "${RUN_STAMP}_full"
        printf 'full_manifest=%s\n' "$FULL"
    } > "$FULL_MARKER"

    RUN_STAMP="${RUN_STAMP}_full" \
    LOG="$FULL_LOG" \
    STATUS_DIR="$FULL_STATUS" \
    MAX_ACTIVE="$MAX_ACTIVE" \
    MIN_FREE_GB="$MIN_FREE_GB" \
    SLEEP_SECONDS="$SLEEP_SECONDS" \
    SLURM_TIME_LIMIT_OVERRIDE="$SLURM_TIME_LIMIT_OVERRIDE" \
    SLURM_PARTITION_OVERRIDE="$SLURM_PARTITION_OVERRIDE" \
    SLURM_QOS_OVERRIDE="$SLURM_QOS_OVERRIDE" \
    SLURM_EXCLUDE_OVERRIDE="$SLURM_EXCLUDE_OVERRIDE" \
    OUT_BASE_OVERRIDE="$OUT_BASE_OVERRIDE" \
    SCRATCH_BASE_OVERRIDE="$SCRATCH_BASE_OVERRIDE" \
    H5_VERIFY="$H5_VERIFY" \
    H5_COMPRESS="$H5_COMPRESS" \
    H5_GZIP_LEVEL="$H5_GZIP_LEVEL" \
    RAW_PRECHECK="$RAW_PRECHECK" \
    "$SCRIPT_DIR/submit_repair_candidates_force.sh" "$FULL" 2>&1 | tee -a "$LOG"
}

mkdir -p "$RUN_DIR" "$CANARY_STATUS"
require_file "$CANARY"
require_file "$FULL"
require_file "$SCRIPT_DIR/audit_aggregate_file_health.py"
require_tool h5ls "$H5LS_BIN"
require_tool python "$PYTHON_BIN"

expected=$(manifest_count "$CANARY")
if [ "$expected" -eq 0 ]; then
    fail_blocked "canary manifest has no tasks"
fi

log "starting canary monitor for $RUN_DIR"
log "expected_canary_tasks=$expected max_active=$MAX_ACTIVE min_free_gb=$MIN_FREE_GB h5_gzip_level=$H5_GZIP_LEVEL"

while true; do
    done_count=$(status_count done)
    failed_count=$(status_count failed)
    skipped_count=$(status_count skipped)
    completed=$((done_count + failed_count + skipped_count))
    log "canary completed=$completed/$expected done=$done_count failed=$failed_count skipped=$skipped_count active_jobs=$(active_canary_jobs) status_counts=$(status_counts)"

    if [ "$failed_count" -gt 0 ]; then
        fail_blocked "canary has failed jobs"
    fi
    if [ "$skipped_count" -gt 0 ]; then
        fail_blocked "canary has skipped jobs; choose a canary date with raw input"
    fi
    if [ "$completed" -ge "$expected" ]; then
        break
    fi
    sleep "$SLEEP_SECONDS"
done

write_canary_done_paths
path_count=$(wc -l < "$CANARY_PATHS")
if [ "$path_count" -ne "$expected" ]; then
    fail_blocked "expected $expected done canary paths but found $path_count"
fi

log "checking canary HDF5 readability and deflate compression"
if ! check_compression; then
    fail_blocked "canary compression/readability check failed; see $COMPRESSION_CHECKS"
fi

log "running canary aggregate audit"
run_canary_audit | tee -a "$LOG"
if ! check_canary_audit; then
    fail_blocked "canary aggregate audit failed; see $CANARY_AUDIT"
fi

submit_full
log "monitor finished"
