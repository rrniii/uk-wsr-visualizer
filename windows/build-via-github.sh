#!/usr/bin/env bash
set -euo pipefail

WORKFLOW="windows-beta.yml"
ARTIFACT_NAME="UK WSR Visualizer Windows Beta"
OUTPUT_DIR="build/windows-beta-artifacts"
REF=""

usage() {
  cat <<'USAGE'
Build the Windows portable beta from macOS/Linux by dispatching GitHub Actions.

Usage:
  windows/build-via-github.sh [--ref BRANCH_OR_TAG] [--output DIR]

The Windows app is built on a GitHub-hosted Windows runner because PyInstaller
does not cross-compile Windows executables from macOS/Linux and the WebView2
shell is validated on Windows. The selected ref must already be pushed to
GitHub; uncommitted local changes are not included.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      REF="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT_DIR="${2:-}"
      shift 2
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

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI 'gh' is required. Install it and run 'gh auth login'." >&2
  exit 1
fi

if [[ -z "$REF" ]]; then
  REF="$(git branch --show-current)"
fi
if [[ -z "$REF" ]]; then
  echo "Could not infer a branch. Pass --ref BRANCH_OR_TAG." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run 'gh auth login'." >&2
  exit 1
fi

if [[ -n "$(git status --short)" ]]; then
  cat >&2 <<EOF
Warning: local working tree has uncommitted changes.
GitHub Actions will build only the pushed contents of ref '$REF'.
Commit and push first if this Windows beta should include local changes.
EOF
fi

TARGET_SHA="$(git rev-parse "$REF^{commit}")"
BEFORE_RUN_IDS="$(gh run list \
  --workflow "$WORKFLOW" \
  --branch "$REF" \
  --event workflow_dispatch \
  --json databaseId \
  --jq '.[].databaseId' \
  --limit 50 || true)"

echo "Dispatching $WORKFLOW for ref '$REF'..."
gh workflow run "$WORKFLOW" --ref "$REF"

echo "Waiting for the dispatched workflow run to appear..."
RUN_ID=""
for _attempt in {1..30}; do
  CANDIDATE_IDS="$(gh run list \
    --workflow "$WORKFLOW" \
    --branch "$REF" \
    --event workflow_dispatch \
    --json databaseId,headSha \
    --jq ".[] | select(.headSha == \"$TARGET_SHA\") | .databaseId" \
    --limit 20)"
  while IFS= read -r candidate_id; do
    if [[ -n "$candidate_id" ]] && ! grep -qx "$candidate_id" <<<"$BEFORE_RUN_IDS"; then
      RUN_ID="$candidate_id"
      break
    fi
  done <<<"$CANDIDATE_IDS"
  if [[ -n "$RUN_ID" ]]; then
    break
  fi
  sleep 2
done

if [[ -z "$RUN_ID" ]]; then
  echo "Could not find the dispatched workflow run for ref '$REF' at $TARGET_SHA." >&2
  exit 1
fi

echo "Watching workflow run $RUN_ID..."
gh run watch "$RUN_ID" --exit-status

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
echo "Downloading artifact '$ARTIFACT_NAME' to $OUTPUT_DIR..."
gh run download "$RUN_ID" --name "$ARTIFACT_NAME" --dir "$OUTPUT_DIR"

ZIP_PATH="$(find "$OUTPUT_DIR" -name 'UK WSR Visualizer Windows Beta.zip' -print -quit)"
if [[ -z "$ZIP_PATH" ]]; then
  echo "Artifact downloaded, but the expected Windows beta zip was not found in $OUTPUT_DIR." >&2
  exit 1
fi

echo "Windows beta zip is ready:"
echo "$ZIP_PATH"
