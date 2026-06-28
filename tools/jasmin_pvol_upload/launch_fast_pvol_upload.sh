#!/usr/bin/env bash
set -euo pipefail

REPO=${REPO:-/home/users/rrniii/uk-wsr-visualizer}
PY=${PY:-/gws/smf/j04/ncas_radar/software/miniconda3_radar_group_20200519/envs/nimrod/bin/python}
AWS_BIN=${AWS_BIN:-/home/users/rrniii/bin/aws}
PVOL_BASE=${PVOL_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site}
RUN_BASE=${RUN_BASE:-/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/pvol-fast-upload}
WORKERS=${WORKERS:-64}
STAMP=${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
RUN_DIR=${RUN_DIR:-${RUN_BASE}/pvol_upload_${STAMP}}

mkdir -p "${RUN_DIR}/logs" "${RUN_DIR}/worker-status"
cd "${REPO}"

cat > "${RUN_DIR}/environment.txt" <<EOF
started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host=$(hostname)
repo=${REPO}
python=${PY}
aws_bin=${AWS_BIN}
pvol_base=${PVOL_BASE}
run_dir=${RUN_DIR}
workers=${WORKERS}
HDF5_USE_FILE_LOCKING=FALSE
RAW_VOLUME_SKIP_PUBLIC_HEAD=1
EOF
"${AWS_BIN}" --version >> "${RUN_DIR}/environment.txt" 2>&1 || true

"${PY}" - <<PY
from pathlib import Path
base = Path("${PVOL_BASE}")
run_dir = Path("${RUN_DIR}")
rows = []
for radar_dir in sorted(p for p in base.iterdir() if p.is_dir()):
    for year_dir in sorted(p for p in radar_dir.iterdir() if p.is_dir() and p.name.isdigit()):
        days = sorted(p for p in year_dir.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 8)
        if not days:
            continue
        rows.append((len(rows), radar_dir.name, year_dir.name, len(days)))
with (run_dir / "shards.tsv").open("w", encoding="utf-8") as out:
    out.write("shard_id\\tradar\\tyear\\tday_count\\n")
    for row in rows:
        out.write("%d\\t%s\\t%s\\t%d\\n" % row)
print(f"shards={len(rows)}")
PY

cp -p "${REPO}/tools/jasmin_pvol_upload/fast_pvol_upload_worker.py" "${RUN_DIR}/fast_pvol_upload_worker.py"

: > "${RUN_DIR}/pids.tsv"
for i in $(seq 0 $((WORKERS - 1))); do
  LOG="${RUN_DIR}/logs/worker_$(printf '%03d' "${i}").log"
  HDF5_USE_FILE_LOCKING=FALSE \
  RAW_VOLUME_SKIP_PUBLIC_HEAD=1 \
  AWS_MAX_ATTEMPTS=10 \
  AWS_RETRY_MODE=adaptive \
  nohup "${PY}" "${RUN_DIR}/fast_pvol_upload_worker.py" \
    --repo "${REPO}" \
    --python "${PY}" \
    --pvol-base "${PVOL_BASE}" \
    --run-dir "${RUN_DIR}" \
    --shards "${RUN_DIR}/shards.tsv" \
    --worker-index "${i}" \
    --worker-count "${WORKERS}" \
    --aws-bin "${AWS_BIN}" \
    > "${LOG}" 2>&1 < /dev/null &
  printf "%03d\t%s\t%s\n" "${i}" "$!" "${LOG}" >> "${RUN_DIR}/pids.tsv"
done

cat > "${RUN_DIR}/monitor.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "run_dir=${RUN_DIR}"
echo "alive_workers=$(awk '{print $2}' "${RUN_DIR}/pids.tsv" | xargs -r ps -o pid= -p | wc -l)"
echo "status_rows=$(find "${RUN_DIR}/worker-status" -name 'worker_*.tsv' -type f -exec tail -n +2 {} \; | wc -l)"
find "${RUN_DIR}/worker-status" -name 'worker_*.tsv' -type f -exec tail -n +2 {} \; |
  awk -F '\t' '{count[$10]++} END {for (k in count) print k,count[k]}'
echo "recent log lines:"
find "${RUN_DIR}/logs" -name 'worker_*.log' -type f -printf '%T@ %p\n' | sort -nr | head -5 | cut -d' ' -f2- |
  while read -r log; do echo "--- ${log}"; tail -5 "${log}"; done
EOF
chmod +x "${RUN_DIR}/monitor.sh"

cat > "${RUN_DIR}/wait_then_build_pvol_catalog.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="${RUN_DIR}"
REPO="${REPO}"
PY="${PY}"
export PYTHONPATH="${REPO}/src:/home/users/rrniii/uk-wsr-visualizer/.deps:\${PYTHONPATH:-}"
while true; do
  alive=\$(awk '{print \$2}' "\${RUN_DIR}/pids.tsv" | xargs -r ps -o pid= -p | wc -l)
  echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ) alive_upload_workers=\${alive}" | tee -a "\${RUN_DIR}/catalog_wait.log"
  [ "\${alive}" -eq 0 ] && break
  sleep 300
done
"${PY}" "${REPO}/tools/build_pvol_catalog_mirror.py" \\
  --run-dir "\${RUN_DIR}/pvol_catalog" \\
  --stage-root "\${RUN_DIR}/pvol_catalog_mirror" \\
  --upload \\
  > "\${RUN_DIR}/pvol_catalog_upload.log" 2>&1
ln -sfn "\${RUN_DIR}" "${RUN_BASE}/latest"
EOF
chmod +x "${RUN_DIR}/wait_then_build_pvol_catalog.sh"

nohup "${RUN_DIR}/wait_then_build_pvol_catalog.sh" > "${RUN_DIR}/catalog_wait_nohup.log" 2>&1 < /dev/null &
echo "$!" > "${RUN_DIR}/catalog_wait.pid"

printf 'run_dir=%s\nworkers=%s\npids=%s\nmonitor=%s\ncatalog_wait_pid=%s\n' \
  "${RUN_DIR}" "${WORKERS}" "${RUN_DIR}/pids.tsv" "${RUN_DIR}/monitor.sh" "$(cat "${RUN_DIR}/catalog_wait.pid")"
