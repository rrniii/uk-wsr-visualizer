#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_REPO_ROOT="$APP_ROOT/Resources/repo"
REPO_ROOT="${UK_WSR_VISUALIZER_REPO_ROOT:-$DEFAULT_REPO_ROOT}"
APP_SUPPORT="$HOME/Library/Application Support/UK WSR Visualizer"
DATA_DIR="$APP_SUPPORT/data"
VENV_DIR="$APP_SUPPORT/venv"
LOG_FILE="$APP_SUPPORT/uk-wsr-visualizer.log"
PORT="${UK_WSR_VISUALIZER_MAC_PORT:-8765}"
BASE_URL="http://127.0.0.1:$PORT"
CACHE_TTL_SECONDS="${UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS:-0}"
CACHE_MAX_BYTES="${UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES:-26843545600}"
REMOTE_BASE="${UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE:-https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public}"
REMOTE_CATALOG="${UK_WSR_VISUALIZER_REMOTE_CATALOG_URL:-$REMOTE_BASE/ukmo-nimrod/catalog/pvol/catalog.json}"
PRE_DUAL_REMOTE_CATALOG="${UK_WSR_VISUALIZER_PRE_DUAL_POL_REMOTE_CATALOG_URL:-$REMOTE_BASE/ukmo-nimrod-pre-dual-pol/catalog/pvol/catalog.json}"

mkdir -p "$APP_SUPPORT" "$DATA_DIR"

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"
}

python_is_supported() {
  "$1" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

resolve_python() {
  if [ -n "${UK_WSR_VISUALIZER_PYTHON:-}" ] && python_is_supported "$UK_WSR_VISUALIZER_PYTHON"; then
    printf '%s\n' "$UK_WSR_VISUALIZER_PYTHON"
    return 0
  fi
  local candidates=(
    "$HOME/.local/bin/python"
    "$HOME/.local/bin/python3"
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.11"
    "/usr/local/bin/python3"
  )
  local found
  for found in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$found" >/dev/null 2>&1; then
      candidates+=("$(command -v "$found")")
    fi
  done
  local candidate
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ] && python_is_supported "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -d "$REPO_ROOT/src/uk_wsr_visualizer" ]; then
  log "bundled repo missing at $REPO_ROOT"
  log "set UK_WSR_VISUALIZER_REPO_ROOT when running from Xcode Debug, or build with macos/build-xcode-macos.sh"
  exit 70
fi

ensure_venv() {
  local python_bin="$1"
  if [ -x "$VENV_DIR/bin/python" ] && ! python_is_supported "$VENV_DIR/bin/python"; then
    log "existing venv Python is older than 3.11; recreating venv at $VENV_DIR"
    rm -rf "$VENV_DIR"
  fi
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "creating venv at $VENV_DIR using $python_bin"
    "$python_bin" -m venv "$VENV_DIR"
  fi
  if ! "$VENV_DIR/bin/python" -c 'import fastapi, uvicorn, h5py, numpy, PIL, imageio, imageio_ffmpeg' >/dev/null 2>&1; then
    log "runtime dependency import failed; recreating venv at $VENV_DIR"
    rm -rf "$VENV_DIR"
    "$python_bin" -m venv "$VENV_DIR"
    log "installing runtime dependencies into venv"
    "$VENV_DIR/bin/python" -m pip install --no-cache-dir --upgrade pip >> "$LOG_FILE" 2>&1
    "$VENV_DIR/bin/python" -m pip install --no-cache-dir fastapi 'uvicorn[standard]' h5py numpy pillow imageio imageio-ffmpeg rasterio >> "$LOG_FILE" 2>&1
  fi
}

server_ready() {
  /usr/bin/curl -fsS "$BASE_URL/api/ready" >/dev/null 2>&1
}

stop_saved_server() {
  local pid
  pid="$(cat "$APP_SUPPORT/server.pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    log "stopping existing server pid $pid"
    kill "$pid" >/dev/null 2>&1 || true
    for _attempt in {1..20}; do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        return
      fi
      sleep 0.25
    done
  fi
}

PYTHON_BIN="$(resolve_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  log "Python 3.11 or newer is required but was not found"
  log "Install Python 3.11+ or set UK_WSR_VISUALIZER_PYTHON to a supported interpreter"
  exit 78
fi
log "using Python runtime $PYTHON_BIN"

ensure_venv "$PYTHON_BIN"

if server_ready; then
  log "server already running at $BASE_URL; restarting saved app server"
  stop_saved_server
  if server_ready; then
    log "existing server at $BASE_URL is not owned by this launcher; leaving it alone"
    while server_ready; do
      sleep 1
    done
    exit 0
  fi
fi

log "starting server at $BASE_URL with dual-pol catalog $REMOTE_CATALOG and pre-dual catalog $PRE_DUAL_REMOTE_CATALOG"
env \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$REPO_ROOT/src" \
  UK_WSR_VISUALIZER_DATA_DIR="$DATA_DIR" \
  UK_WSR_VISUALIZER_CATALOG="$DATA_DIR/catalog.json" \
  UK_WSR_VISUALIZER_REMOTE_CATALOG_URL="$REMOTE_CATALOG" \
  UK_WSR_VISUALIZER_PRE_DUAL_POL_REMOTE_CATALOG_URL="$PRE_DUAL_REMOTE_CATALOG" \
  UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE="$REMOTE_BASE" \
  UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS="$CACHE_TTL_SECONDS" \
  UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES="$CACHE_MAX_BYTES" \
  "$VENV_DIR/bin/python" -m uk_wsr_visualizer.cli api --host 127.0.0.1 --port "$PORT" \
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
