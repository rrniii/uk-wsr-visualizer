#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Run the desktop beta release smoke checks.

Usage:
  scripts/desktop_beta_smoke.sh [--allow-non-master]

The desktop Mac/Windows beta must normally be released from a clean master
checkout. The script runs syntax checks, Python tests, docs build, and citation
metadata checks before the Windows GitHub Actions build is dispatched.

Set PYTHON=/path/to/python or NODE=/path/to/node to override the commands used
by the smoke checks.
USAGE
}

ALLOW_NON_MASTER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-non-master)
      ALLOW_NON_MASTER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "master" && "$ALLOW_NON_MASTER" != "1" ]]; then
  echo "Desktop beta releases must be cut from master; current branch is '$BRANCH'." >&2
  exit 1
fi

if [[ -n "$(git status --short)" ]]; then
  echo "Working tree is not clean. Commit, stash, or remove changes before release smoke checks." >&2
  git status --short >&2
  exit 1
fi

PYTHON_BIN="${PYTHON:-python}"
NODE_BIN="${NODE:-node}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v "$NODE_BIN" >/dev/null 2>&1; then
  echo "Node.js is required for viewer JavaScript syntax checks. Set NODE=/path/to/node if it is not on PATH." >&2
  exit 1
fi

echo "Checking viewer JavaScript syntax..."
"$NODE_BIN" --check src/uk_wsr_visualizer/static/app.js
"$NODE_BIN" --check "macos/UK WSR Visualizer.app/Contents/Resources/repo/src/uk_wsr_visualizer/static/app.js"

echo "Running Python test suite..."
"$PYTHON_BIN" -m pytest

echo "Building documentation..."
if command -v sphinx-build >/dev/null 2>&1; then
  sphinx-build -b html docs docs/_build/html
else
  "$PYTHON_BIN" -m sphinx -b html docs docs/_build/html
fi

echo "Checking citation metadata..."
"$PYTHON_BIN" -m uk_wsr_visualizer.citations --json >/tmp/uk-wsr-visualizer-citation.json
grep -q '"software"' /tmp/uk-wsr-visualizer-citation.json
grep -q '"source_data"' /tmp/uk-wsr-visualizer-citation.json

cat <<'DONE'
Desktop beta smoke checks passed.

Next release steps:
  1. Push master.
  2. Run: windows/build-via-github.sh --ref master
  3. Replace the shared Google Drive Windows beta zip for Chris and Tommy.
DONE
