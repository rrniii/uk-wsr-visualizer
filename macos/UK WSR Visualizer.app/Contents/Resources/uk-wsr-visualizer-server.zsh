#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$APP_ROOT/Resources/repo"
APP_SUPPORT="$HOME/Library/Application Support/UK WSR Visualizer"
DATA_DIR="$APP_SUPPORT/data"
VENV_DIR="$APP_SUPPORT/venv"
LOG_FILE="$APP_SUPPORT/uk-wsr-visualizer.log"
PORT="${UK_WSR_VISUALIZER_MAC_PORT:-8765}"
BASE_URL="http://127.0.0.1:$PORT"
CACHE_TTL_SECONDS="${UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS:-3600}"
CACHE_MAX_BYTES="${UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES:-26843545600}"
REMOTE_BASE="${UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE:-https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public}"
REMOTE_CATALOG="${UK_WSR_VISUALIZER_REMOTE_CATALOG_URL:-$REMOTE_BASE/ukmo-nimrod/catalog/pvol/catalog.json}"

mkdir -p "$APP_SUPPORT" "$DATA_DIR"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
}

ensure_venv() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "creating venv at $VENV_DIR"
    /usr/bin/arch -arm64 /usr/bin/python3 -m venv "$VENV_DIR"
  fi
  if ! /usr/bin/arch -arm64 "$VENV_DIR/bin/python" -c 'import fastapi, uvicorn, h5py, numpy, PIL, tomli, eval_type_backport' >/dev/null 2>&1; then
    log "runtime dependency import failed; recreating venv at $VENV_DIR"
    rm -rf "$VENV_DIR"
    /usr/bin/arch -arm64 /usr/bin/python3 -m venv "$VENV_DIR"
    log "installing runtime dependencies into venv"
    /usr/bin/arch -arm64 "$VENV_DIR/bin/python" -m pip install --no-cache-dir --upgrade pip >> "$LOG_FILE" 2>&1
    /usr/bin/arch -arm64 "$VENV_DIR/bin/python" -m pip install --no-cache-dir fastapi 'uvicorn[standard]' h5py numpy pillow tomli eval_type_backport >> "$LOG_FILE" 2>&1
  fi
}

server_ready() {
  /usr/bin/curl -fsS "$BASE_URL/api/ready" >/dev/null 2>&1
}

server_catalog_matches() {
  local status
  status="$(/usr/bin/curl -fsS "$BASE_URL/api/status" 2>/dev/null || true)"
  if [ -z "$status" ]; then
    return 1
  fi
  STATUS_JSON="$status" EXPECTED_CATALOG="$REMOTE_CATALOG" /usr/bin/python3 - <<'PY'
import json
import os
import sys

try:
    status = json.loads(os.environ["STATUS_JSON"])
except Exception:
    sys.exit(1)
sys.exit(0 if status.get("catalog_source") == os.environ["EXPECTED_CATALOG"] else 1)
PY
}

stop_saved_server() {
  local pid
  pid="$(cat "$APP_SUPPORT/server.pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    log "stopping existing server pid $pid to refresh catalog source"
    kill "$pid" >/dev/null 2>&1 || true
    for _attempt in {1..20}; do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        return
      fi
      sleep 0.25
    done
  fi
}

ensure_venv

if server_ready; then
  log "server already running at $BASE_URL; restarting saved app server so bundled UI changes are loaded"
  stop_saved_server
  if server_ready; then
    if server_catalog_matches; then
      log "using existing server at $BASE_URL"
      while server_ready; do
        sleep 1
      done
      exit 0
    fi
    log "existing server at $BASE_URL uses a different catalog; leaving it alone"
    while server_ready; do
      sleep 1
    done
    exit 0
  fi
fi

log "starting server at $BASE_URL with remote catalog $REMOTE_CATALOG"
env \
  PYTHONPATH="$REPO_ROOT/src" \
  UK_WSR_VISUALIZER_DATA_DIR="$DATA_DIR" \
  UK_WSR_VISUALIZER_CATALOG="$DATA_DIR/catalog.json" \
  UK_WSR_VISUALIZER_REMOTE_CATALOG_URL="$REMOTE_CATALOG" \
  UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE="$REMOTE_BASE" \
  UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS="$CACHE_TTL_SECONDS" \
  UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES="$CACHE_MAX_BYTES" \
  /usr/bin/arch -arm64 "$VENV_DIR/bin/python" -m uk_wsr_visualizer.cli api --host 127.0.0.1 --port "$PORT" \
  >> "$LOG_FILE" 2>&1 &
server_pid="$!"
printf '%s\n' "$server_pid" > "$APP_SUPPORT/server.pid"

cleanup() {
  if kill -0 "$server_pid" >/dev/null 2>&1; then
    log "stopping server pid $server_pid"
    kill "$server_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup INT TERM EXIT
wait "$server_pid"
