#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/gws/ssde/j25a/ncas_radar}
AUDIT=${AUDIT:-$BASE/vol2/avocet/direct_repair_logs/aggregate_audit_20260625T043826Z/aggregate_audit_merged.tsv}
OUT_ROOT=${OUT_ROOT:-$BASE/vol2/avocet/direct_repair_logs}
STAMP=${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
OUT_DIR=${OUT_DIR:-$OUT_ROOT/hdf5_compression_benchmark_$STAMP}
SAMPLE_MODE=${SAMPLE_MODE:-small}
PROFILES=${PROFILES:-gzip1,gzip4,gzip6}
MIN_FREE_GB=${MIN_FREE_GB:-200}

mkdir -p "$OUT_DIR"/{samples,repacked,logs}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT_DIR/benchmark.log"
}

free_gb() {
  df -BG "$BASE" | awk 'NR==2 {gsub(/G/, "", $4); print $4}'
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: missing required tool $1" >&2
    exit 2
  }
}

require_tool h5repack
require_tool h5ls
require_tool h5dump
require_tool python3

log "Starting HDF5 compression benchmark"
log "AUDIT=$AUDIT"
log "OUT_DIR=$OUT_DIR"
log "SAMPLE_MODE=$SAMPLE_MODE"
log "PROFILES=$PROFILES"
df -h "$BASE" > "$OUT_DIR/df_start.txt" 2>&1 || true

python3 - "$AUDIT" "$OUT_DIR/sample_manifest.tsv" "$SAMPLE_MODE" <<'PY'
import csv
import sys
from collections import defaultdict
from pathlib import Path

audit = Path(sys.argv[1])
out = Path(sys.argv[2])
mode = sys.argv[3]

if mode == "small":
    bins = [
        ("0.15-0.3GB", 150_000_000, 300_000_000),
        ("0.3-0.6GB", 300_000_000, 600_000_000),
        ("0.6-0.9GB", 600_000_000, 900_000_000),
        ("1-2GB", 1_000_000_000, 2_000_000_000),
        ("2-5GB", 2_000_000_000, 5_000_000_000),
    ]
else:
    bins = [
        ("0.5-1GB", 500_000_000, 1_000_000_000),
        ("1-2GB", 1_000_000_000, 2_000_000_000),
        ("2-5GB", 2_000_000_000, 5_000_000_000),
        ("5-10GB", 5_000_000_000, 10_000_000_000),
        ("10-20GB", 10_000_000_000, 20_000_000_000),
    ]

rows = []
with audit.open(newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        if row.get("status") != "ok":
            continue
        try:
            size = int(row["size_bytes"])
        except Exception:
            continue
        path = Path(row["path"])
        if path.name.startswith(".") or path.name.endswith(".tmp"):
            continue
        rows.append((size, row["radar"], row["date"], row["radar_num"], str(path)))

used_radars = set()
chosen = []
for label, lo, hi in bins:
    candidates = [r for r in rows if lo <= r[0] < hi]
    candidates.sort(key=lambda r: (r[1] in used_radars, abs(r[0] - ((lo + hi) // 2))))
    if candidates:
        size, radar, date, radar_num, path = candidates[0]
        used_radars.add(radar)
        chosen.append((label, size, radar, date, radar_num, path))

with out.open("w", newline="") as f:
    writer = csv.writer(f, delimiter="\t", lineterminator="\n")
    writer.writerow(["sample_bin", "size_bytes", "radar", "date", "radar_num", "path"])
    writer.writerows(chosen)
PY

log "Sample manifest"
cat "$OUT_DIR/sample_manifest.tsv" | tee -a "$OUT_DIR/benchmark.log"

printf 'sample_bin\tprofile\tsource_size_bytes\tcompressed_size_bytes\tratio\tcopy_seconds\trepack_seconds\th5ls_ok\tfilter_ok\tsource_path\tcompressed_path\n' > "$OUT_DIR/compression_benchmark.tsv"
printf 'sample_bin\tprofile\tcommand\tstdout_stderr_log\n' > "$OUT_DIR/commands.tsv"

profile_level() {
  case "$1" in
    gzip1) echo 1 ;;
    gzip4) echo 4 ;;
    gzip6) echo 6 ;;
    *) echo "unknown profile $1" >&2; return 1 ;;
  esac
}

IFS=',' read -r -a profile_array <<< "$PROFILES"

tail -n +2 "$OUT_DIR/sample_manifest.tsv" | while IFS=$'\t' read -r sample_bin size_bytes radar date radar_num source_path; do
  [ -n "$source_path" ] || continue
  current_free=$(free_gb)
  if [ "$current_free" -lt "$MIN_FREE_GB" ]; then
    log "Stopping before sample $sample_bin: free_gb=$current_free below MIN_FREE_GB=$MIN_FREE_GB"
    break
  fi

  sample_name="${sample_bin}_${radar}_${date}_radar${radar_num}"
  sample_name=${sample_name//[^A-Za-z0-9_.-]/_}
  sample_copy="$OUT_DIR/samples/${sample_name}.h5"

  log "Copying sample $source_path"
  copy_log="$OUT_DIR/logs/${sample_name}_copy.log"
  copy_start=$(date +%s)
  cp -p "$source_path" "$sample_copy" >"$copy_log" 2>&1
  copy_end=$(date +%s)
  copy_seconds=$((copy_end - copy_start))
  source_size=$(stat -c %s "$sample_copy")

  for profile in "${profile_array[@]}"; do
    level=$(profile_level "$profile")
    out_file="$OUT_DIR/repacked/${sample_name}_${profile}.h5"
    repack_log="$OUT_DIR/logs/${sample_name}_${profile}_h5repack.log"
    log "Repacking sample=$sample_name profile=$profile"
    printf '%s\t%s\th5repack -f SHUF -f GZIP=%s\t%s\n' "$sample_bin" "$profile" "$level" "$repack_log" >> "$OUT_DIR/commands.tsv"
    repack_start=$(date +%s)
    if h5repack -f SHUF -f "GZIP=${level}" "$sample_copy" "$out_file" >"$repack_log" 2>&1; then
      repack_rc=0
    else
      repack_rc=$?
    fi
    repack_end=$(date +%s)
    repack_seconds=$((repack_end - repack_start))
    compressed_size=0
    h5ls_ok=0
    filter_ok=0
    ratio=0
    if [ "$repack_rc" -eq 0 ] && [ -s "$out_file" ]; then
      compressed_size=$(stat -c %s "$out_file")
      if h5ls "$out_file" >/dev/null 2>&1; then
        h5ls_ok=1
      fi
      filter_dump="$OUT_DIR/logs/${sample_name}_${profile}_h5dump_filters.txt"
      if h5dump -pH "$out_file" >"$filter_dump" 2>/dev/null; then
        if grep -q "PREPROCESSING SHUFFLE" "$filter_dump" && grep -q "COMPRESSION DEFLATE" "$filter_dump"; then
          filter_ok=1
        fi
      fi
      ratio=$(awk -v c="$compressed_size" -v s="$source_size" 'BEGIN {if (s > 0) printf "%.6f", c / s; else print "0"}')
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$sample_bin" "$profile" "$source_size" "$compressed_size" "$ratio" \
      "$copy_seconds" "$repack_seconds" "$h5ls_ok" "$filter_ok" "$source_path" "$out_file" \
      >> "$OUT_DIR/compression_benchmark.tsv"
  done
done

python3 - "$AUDIT" "$OUT_DIR/compression_benchmark.tsv" "$OUT_DIR/compression_projection_by_radar.tsv" "$OUT_DIR/recommended_profile.txt" <<'PY'
import csv
import sys
from collections import defaultdict
from pathlib import Path

audit = Path(sys.argv[1])
bench = Path(sys.argv[2])
projection = Path(sys.argv[3])
recommendation = Path(sys.argv[4])

db_bytes = 0
radar_bytes = defaultdict(int)
with audit.open(newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        try:
            size = int(row["size_bytes"])
        except Exception:
            continue
        db_bytes += size
        radar_bytes[row["radar"]] += size

ratios = defaultdict(list)
with bench.open(newline="") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        if row["h5ls_ok"] != "1" or row["filter_ok"] != "1":
            continue
        ratio = float(row["ratio"])
        if ratio > 0:
            ratios[row["profile"]].append(ratio)

profile_summary = {}
for profile, vals in ratios.items():
    if vals:
        profile_summary[profile] = sum(vals) / len(vals)

best_profile = None
if "gzip4" in profile_summary:
    best_profile = "gzip4"
elif profile_summary:
    best_profile = sorted(profile_summary, key=profile_summary.get)[0]

with projection.open("w", newline="") as f:
    writer = csv.writer(f, delimiter="\t", lineterminator="\n")
    writer.writerow(["radar", "current_bytes", "profile", "mean_ratio", "projected_bytes"])
    for radar, size in sorted(radar_bytes.items()):
        for profile, ratio in sorted(profile_summary.items()):
            writer.writerow([radar, size, profile, f"{ratio:.6f}", int(size * ratio)])

with recommendation.open("w") as f:
    f.write(f"current_database_bytes\t{db_bytes}\n")
    f.write(f"current_database_TiB\t{db_bytes/1024**4:.2f}\n")
    for profile, ratio in sorted(profile_summary.items()):
        projected = db_bytes * ratio
        f.write(f"profile\t{profile}\tmean_ratio\t{ratio:.6f}\tprojected_TiB\t{projected/1024**4:.2f}\tprojected_TB\t{projected/1000**4:.2f}\n")
    if best_profile:
        ratio = profile_summary[best_profile]
        f.write(f"recommended_profile\t{best_profile}\n")
        f.write(f"recommended_projected_TB\t{db_bytes * ratio / 1000**4:.2f}\n")
    else:
        f.write("recommended_profile\tNONE_VALID\n")
PY

df -h "$BASE" > "$OUT_DIR/df_end.txt" 2>&1 || true
log "Finished HDF5 compression benchmark"
log "Results: $OUT_DIR/compression_benchmark.tsv"
log "Recommendation: $OUT_DIR/recommended_profile.txt"
