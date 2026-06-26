#!/usr/bin/env bash
set -euo pipefail

BASE=${BASE:-/gws/ssde/j25a/ncas_radar}
OUT_ROOT=${OUT_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/direct_repair_logs}
STAMP=${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
OUT_DIR=${OUT_DIR:-"$OUT_ROOT/gws_cleanup_scan_$STAMP"}
MIN_FILE_SIZE=${MIN_FILE_SIZE:-+1G}

mkdir -p "$OUT_DIR"

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$OUT_DIR/scan.log"
}

write_header() {
  local path=$1
  shift
  printf '%s\n' "$*" > "$path"
}

log "Starting cleanup candidate scan"
log "BASE=$BASE"
log "OUT_DIR=$OUT_DIR"
log "MIN_FILE_SIZE=$MIN_FILE_SIZE"

df -h "$BASE" > "$OUT_DIR/df_start.txt" 2>&1 || true

log "Collecting top-level directory sizes"
{
  printf 'size\tpath\n'
  find "$BASE" -mindepth 1 -maxdepth 2 -type d -print0 2>/dev/null \
    | xargs -0 -r du -sh 2>/dev/null \
    | sort -hr
} > "$OUT_DIR/top_level_du.tsv" || true

log "Scanning project scratch/log directories"
write_header "$OUT_DIR/scratch_log_dirs.tsv" \
  "size_bytes	owner	group	mode	mtime_utc	path	classification"
find "$BASE" -type d \( \
    -name 'tmp*' -o \
    -name '*scratch*' -o \
    -name '*repair*logs*' -o \
    -name 'direct_repair_logs' -o \
    -name 'aggregate_audit_*' -o \
    -name 'fast_repair_*' -o \
    -name 'tmp_raw_radar*' \
  \) -print0 2>/dev/null \
  | while IFS= read -r -d '' path; do
      size=$(du -sb "$path" 2>/dev/null | awk '{print $1}' || printf 'NA')
      stat -c "%U	%G	%a	%y" "$path" 2>/dev/null \
        | awk -v p="$path" -v s="$size" '
            BEGIN { cls="review_scratch_or_logs" }
            {
              mtime=$4 "T" $5 "Z"
              print s "\t" $1 "\t" $2 "\t" $3 "\t" mtime "\t" p "\t" cls
            }'
    done \
  | sort -nr > "$OUT_DIR/scratch_log_dirs.tsv.tmp" || true
{
  head -1 "$OUT_DIR/scratch_log_dirs.tsv"
  cat "$OUT_DIR/scratch_log_dirs.tsv.tmp" 2>/dev/null || true
} > "$OUT_DIR/scratch_log_dirs.tsv.final"
mv "$OUT_DIR/scratch_log_dirs.tsv.final" "$OUT_DIR/scratch_log_dirs.tsv"
rm -f "$OUT_DIR/scratch_log_dirs.tsv.tmp"

log "Scanning hidden/temp HDF5-style files"
write_header "$OUT_DIR/temp_hdf5_candidates.tsv" \
  "size_bytes	owner	group	mode	mtime_utc	path	classification"
find "$BASE" -type f \( \
    -name '*.tmp' -o \
    -name '*.tmp.*' -o \
    -name '.*.tmp' -o \
    -name '*.h5.force_*' -o \
    -name '.*.h5.force_*' -o \
    -name '.*.h5.*.tmp' -o \
    -name '.nfs*' \
  \) -printf '%s\t%u\t%g\t%m\t%TY-%Tm-%TdT%TH:%TM:%TSZ\t%p\ttemp_or_interrupted_write\n' 2>/dev/null \
  | sort -nr > "$OUT_DIR/temp_hdf5_candidates.tsv.body" || true
{
  head -1 "$OUT_DIR/temp_hdf5_candidates.tsv"
  cat "$OUT_DIR/temp_hdf5_candidates.tsv.body" 2>/dev/null || true
} > "$OUT_DIR/temp_hdf5_candidates.tsv.final"
mv "$OUT_DIR/temp_hdf5_candidates.tsv.final" "$OUT_DIR/temp_hdf5_candidates.tsv"
rm -f "$OUT_DIR/temp_hdf5_candidates.tsv.body"

log "Scanning large files for manual review"
write_header "$OUT_DIR/large_files.tsv" \
  "size_bytes	owner	group	mode	mtime_utc	path	classification"
find "$BASE" -type f -size "$MIN_FILE_SIZE" \
  -printf '%s\t%u\t%g\t%m\t%TY-%Tm-%TdT%TH:%TM:%TSZ\t%p\tlarge_file_review\n' 2>/dev/null \
  | sort -nr > "$OUT_DIR/large_files.tsv.body" || true
{
  head -1 "$OUT_DIR/large_files.tsv"
  cat "$OUT_DIR/large_files.tsv.body" 2>/dev/null || true
} > "$OUT_DIR/large_files.tsv.final"
mv "$OUT_DIR/large_files.tsv.final" "$OUT_DIR/large_files.tsv"
rm -f "$OUT_DIR/large_files.tsv.body"

log "Scanning ukmo-nimrod named paths"
write_header "$OUT_DIR/ukmo_nimrod_paths.tsv" \
  "size_bytes	owner	group	mode	mtime_utc	path	classification"
find "$BASE" -path '*ukmo-nimrod*' -type d -print0 2>/dev/null \
  | while IFS= read -r -d '' path; do
      size=$(du -sb "$path" 2>/dev/null | awk '{print $1}' || printf 'NA')
      stat -c "%U	%G	%a	%y" "$path" 2>/dev/null \
        | awk -v p="$path" -v s="$size" '
            {
              mtime=$4 "T" $5 "Z"
              print s "\t" $1 "\t" $2 "\t" $3 "\t" mtime "\t" p "\tukmo_nimrod_review"
            }'
    done \
  | sort -nr > "$OUT_DIR/ukmo_nimrod_paths.tsv.body" || true
{
  head -1 "$OUT_DIR/ukmo_nimrod_paths.tsv"
  cat "$OUT_DIR/ukmo_nimrod_paths.tsv.body" 2>/dev/null || true
} > "$OUT_DIR/ukmo_nimrod_paths.tsv.final"
mv "$OUT_DIR/ukmo_nimrod_paths.tsv.final" "$OUT_DIR/ukmo_nimrod_paths.tsv"
rm -f "$OUT_DIR/ukmo_nimrod_paths.tsv.body"

log "Building summary"
{
  printf 'metric\tvalue\n'
  printf 'out_dir\t%s\n' "$OUT_DIR"
  printf 'base\t%s\n' "$BASE"
  printf 'started_utc\t%s\n' "$STAMP"
  printf 'scratch_log_dir_count\t%s\n' "$(($(wc -l < "$OUT_DIR/scratch_log_dirs.tsv") - 1))"
  printf 'temp_hdf5_candidate_count\t%s\n' "$(($(wc -l < "$OUT_DIR/temp_hdf5_candidates.tsv") - 1))"
  printf 'large_file_count\t%s\n' "$(($(wc -l < "$OUT_DIR/large_files.tsv") - 1))"
  printf 'ukmo_nimrod_path_count\t%s\n' "$(($(wc -l < "$OUT_DIR/ukmo_nimrod_paths.tsv") - 1))"
  awk -F '\t' 'NR>1 && $1 ~ /^[0-9]+$/ {s+=$1} END {printf "temp_hdf5_candidate_bytes\t%.0f\n", s+0}' "$OUT_DIR/temp_hdf5_candidates.tsv"
  awk -F '\t' 'NR>1 && $1 ~ /^[0-9]+$/ {s+=$1} END {printf "scratch_log_dir_bytes\t%.0f\n", s+0}' "$OUT_DIR/scratch_log_dirs.tsv"
} > "$OUT_DIR/summary.tsv"

df -h "$BASE" > "$OUT_DIR/df_end.txt" 2>&1 || true
log "Finished cleanup candidate scan"
log "Summary: $OUT_DIR/summary.tsv"
