#!/bin/bash

set -euo pipefail

CANDIDATES=${1:?Usage: run_hdf5_surgical_prune.sh <validation-candidates.tsv>}

ENV=${ENV:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod}
RUN_DIR=${RUN_DIR:-$(dirname "$CANDIDATES")}
RUN_STAMP=${RUN_STAMP:-hdf5_surgical_prune_$(date -u +%Y%m%dT%H%M%SZ)}
STATUS_DIR=${STATUS_DIR:-${RUN_DIR}/hdf5_surgical_prune_status_${RUN_STAMP}}
DONE_REPAIR_STATUS_DIR=${DONE_REPAIR_STATUS_DIR:-${RUN_DIR}/forced_repair_status_forced_after_lotus_retry2_20260623T1853Z}
MANIFEST=${MANIFEST:-${RUN_DIR}/hdf5_surgical_prune_manifest_${RUN_STAMP}.tsv}
ACTIVE_KEYS=${ACTIVE_KEYS:-${RUN_DIR}/hdf5_surgical_prune_active_keys_${RUN_STAMP}.tsv}
LOG=${LOG:-${RUN_DIR}/hdf5_surgical_prune_${RUN_STAMP}.log}
H5LS_BIN=${H5LS_BIN:-$(command -v h5ls 2>/dev/null || true)}

RADARS=('castor-bay' 'chenies' 'clee-hill' 'cobbacombe' 'crug-y-gorrllwyn' 'deanhill' 'druima-starraig' 'dudwick' 'hameldon-hill' 'high-moorsley' 'holehead' 'ingham' 'jersey' 'munduff-hill' 'predannack' 'thurnham' 'wardon-hill')
RADAR_NUMS=('07' '05' '03' '16' '10' '21' '15' '14' '04' '23' '18' '09' '12' '19' '08' '20' '11')

radar_for_num() {
    local rnum=$1
    local i
    for i in "${!RADAR_NUMS[@]}"; do
        if [ "${RADAR_NUMS[$i]}" = "$rnum" ]; then
            printf '%s\n' "${RADARS[$i]}"
            return 0
        fi
    done
    return 1
}

if [ ! -f "$CANDIDATES" ]; then
    echo "ERROR: candidate file not found: $CANDIDATES" >&2
    exit 1
fi
if [ ! -x "${ENV%/}/bin/python" ]; then
    echo "ERROR: missing python in env: ${ENV%/}/bin/python" >&2
    exit 1
fi
if [ -z "$H5LS_BIN" ]; then
    echo "ERROR: h5ls not found" >&2
    exit 1
fi

mkdir -p "$RUN_DIR" "$STATUS_DIR"

> "$ACTIVE_KEYS"
while read -r job; do
    [ -n "$job" ] || continue
    rnum=${job%%_*}
    date=${job#*_}
    if radar=$(radar_for_num "$rnum"); then
        printf '%s\t%s\n' "$radar" "$date"
    fi
done < <(squeue -u "$USER" -h -o '%j' | awk '/^[0-9][0-9]_[0-9]{8}$/ {print $1}') >> "$ACTIVE_KEYS"
sort -u -o "$ACTIVE_KEYS" "$ACTIVE_KEYS"

{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting HDF5 surgical prune"
    echo "candidate_file=$CANDIDATES"
    echo "env=$ENV"
    echo "run_stamp=$RUN_STAMP"
    echo "status_dir=$STATUS_DIR"
    echo "done_repair_status_dir=$DONE_REPAIR_STATUS_DIR"
    echo "manifest=$MANIFEST"
    echo "active_keys=$ACTIVE_KEYS"
    echo "active_key_count=$(wc -l < "$ACTIVE_KEYS")"
    echo "h5ls=$H5LS_BIN"
} | tee -a "$LOG"

"${ENV%/}/bin/python" - "$CANDIDATES" "$MANIFEST" "$ACTIVE_KEYS" "$DONE_REPAIR_STATUS_DIR" <<'PY'
import csv
import os
import sys
from collections import defaultdict

candidates, manifest, active_keys_file, done_status_dir = sys.argv[1:5]
whole_file_issues = {"hdf5_open_error", "missing_lp_sp"}
surgical_issues = {"partial_volume", "non_contiguous_datasets", "missing_datasets"}

active = set()
with open(active_keys_file, newline="") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2:
            active.add((parts[0], parts[1]))

issues_by_path = defaultdict(set)
groups_by_path = defaultdict(set)
meta_by_path = {}

with open(candidates, newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        path = row["path"]
        radar = row["radar"]
        date = row["date"]
        issue = row["issue"]
        pulse = row.get("pulse", "")
        time = row.get("time", "")
        issues_by_path[path].add(issue)
        meta_by_path[path] = (radar, date)
        if issue in surgical_issues and pulse and time:
            groups_by_path[path].add((pulse, time))

counts = defaultdict(int)
with open(manifest, "w", newline="") as f:
    writer = csv.writer(f, delimiter="\t")
    writer.writerow(["path", "radar", "date", "group_count", "groups"])
    for path in sorted(issues_by_path):
        radar, date = meta_by_path[path]
        key = (radar, date)
        if issues_by_path[path] & whole_file_issues:
            counts["skip_whole_file_issue"] += 1
            continue
        if path not in groups_by_path:
            counts["skip_no_surgical_groups"] += 1
            continue
        if key in active:
            counts["skip_active_slurm"] += 1
            continue
        done_file = os.path.join(done_status_dir, f"{radar}_{date}.done")
        if os.path.exists(done_file):
            counts["skip_already_raw_repaired"] += 1
            continue
        groups = sorted(groups_by_path[path])
        writer.writerow([path, radar, date, len(groups), ",".join(f"{p}/{t}" for p, t in groups)])
        counts["manifest_files"] += 1
        counts["manifest_groups"] += len(groups)

for key in sorted(counts):
    print(f"{key}={counts[key]}")
PY

{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] manifest ready"
    echo "manifest_file_count=$(( $(wc -l < "$MANIFEST") - 1 ))"
} | tee -a "$LOG"

"${ENV%/}/bin/python" - "$MANIFEST" "$STATUS_DIR" "$H5LS_BIN" "$LOG" <<'PY'
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import time

import h5py

manifest, status_dir, h5ls_bin, log = sys.argv[1:5]

def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def append_log(message):
    with open(log, "a") as f:
        f.write(f"[{utc()}] {message}\n")
        f.flush()

def status_path(path, suffix):
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()
    return os.path.join(status_dir, f"{digest}.{suffix}")

def write_status(path, suffix, lines):
    with open(status_path(path, suffix), "w") as f:
        f.write(f"path={path}\n")
        f.write(f"timestamp_utc={utc()}\n")
        for line in lines:
            f.write(f"{line}\n")

processed = changed = failed = skipped = 0

with open(manifest, newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        path = row["path"]
        radar = row["radar"]
        date = row["date"]
        groups = [tuple(item.split("/", 1)) for item in row["groups"].split(",") if item]
        processed += 1

        if os.path.exists(status_path(path, "done")) or os.path.exists(status_path(path, "skipped")):
            skipped += 1
            continue

        lock_dir = f"{path}.force.lock"
        if os.path.exists(lock_dir):
            write_status(path, "skipped", [f"reason=active_lock", f"radar={radar}", f"date={date}"])
            skipped += 1
            append_log(f"SKIP lock path={path}")
            continue

        if not os.path.exists(path):
            write_status(path, "skipped", [f"reason=missing_file", f"radar={radar}", f"date={date}"])
            skipped += 1
            append_log(f"SKIP missing path={path}")
            continue

        tmp = f"{path}.surgical_prune_{os.getpid()}.tmp"
        deleted = 0
        missing = 0
        try:
            present_groups = []
            with h5py.File(path, "r") as h5:
                for pulse, t in groups:
                    group_path = f"{pulse}/{t}"
                    if group_path in h5:
                        present_groups.append((pulse, t))
                    else:
                        missing += 1
            if not present_groups:
                write_status(path, "skipped", [
                    "reason=no_listed_groups_present",
                    f"radar={radar}",
                    f"date={date}",
                    f"missing_groups={missing}",
                ])
                skipped += 1
                append_log(f"SKIP no_groups path={path} missing={missing}")
                continue

            if os.path.exists(tmp):
                os.unlink(tmp)
            shutil.copy2(path, tmp)
            with h5py.File(tmp, "r+") as h5:
                for pulse, t in present_groups:
                    group_path = f"{pulse}/{t}"
                    if group_path in h5:
                        del h5[group_path]
                        deleted += 1
                    else:
                        missing += 1
                h5.flush()
            if deleted == 0:
                os.unlink(tmp)
                write_status(path, "skipped", [
                    "reason=no_listed_groups_present",
                    f"radar={radar}",
                    f"date={date}",
                    f"missing_groups={missing}",
                ])
                skipped += 1
                append_log(f"SKIP no_groups path={path} missing={missing}")
                continue
            subprocess.run([h5ls_bin, tmp], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.replace(tmp, path)
            subprocess.run([h5ls_bin, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            write_status(path, "done", [
                f"radar={radar}",
                f"date={date}",
                f"deleted_groups={deleted}",
                f"missing_groups={missing}",
            ])
            changed += 1
            append_log(f"DONE path={path} deleted_groups={deleted} missing_groups={missing}")
        except Exception as exc:
            failed += 1
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass
            write_status(path, "failed", [
                f"radar={radar}",
                f"date={date}",
                f"error={type(exc).__name__}: {exc}",
            ])
            append_log(f"FAILED path={path} error={type(exc).__name__}: {exc}")

        if processed % 100 == 0:
            append_log(f"PROGRESS processed={processed} changed={changed} skipped={skipped} failed={failed}")

append_log(f"COMPLETE processed={processed} changed={changed} skipped={skipped} failed={failed}")
PY

{
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] HDF5 surgical prune complete"
    echo "status_counts"
    find "$STATUS_DIR" -type f | sed 's/.*\.//' | sort | uniq -c || true
    echo "df_after"
    df -h "$RUN_DIR"
} | tee -a "$LOG"
