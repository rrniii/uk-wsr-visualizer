#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-ncas-rsg-cloud-workstation-ssh}"
BASE_URL="${2:-http://127.0.0.1:8000}"

ssh -o StrictHostKeyChecking=accept-new "${HOST}" "UK_WSR_VISUALIZER_SMOKE_BASE_URL='${BASE_URL}' bash -s" <<'REMOTE'
set -euo pipefail

if [[ -f /etc/uk-wsr-visualizer/uk-wsr-visualizer.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/uk-wsr-visualizer/uk-wsr-visualizer.env
  set +a
fi

UK_WSR_VISUALIZER_DATA_DIR="${UK_WSR_VISUALIZER_DATA_DIR:-/opt/uk-wsr-visualizer/data}"
UK_WSR_VISUALIZER_CATALOG="${UK_WSR_VISUALIZER_CATALOG:-${UK_WSR_VISUALIZER_DATA_DIR}/catalog.json}"
UK_WSR_VISUALIZER_PREVIEW_DIR="${UK_WSR_VISUALIZER_PREVIEW_DIR:-${UK_WSR_VISUALIZER_DATA_DIR}/previews}"
UK_WSR_VISUALIZER_TILE_DIR="${UK_WSR_VISUALIZER_TILE_DIR:-${UK_WSR_VISUALIZER_DATA_DIR}/tiles}"
UK_WSR_VISUALIZER_EXPORT_DIR="${UK_WSR_VISUALIZER_EXPORT_DIR:-${UK_WSR_VISUALIZER_DATA_DIR}/exports}"
UK_WSR_VISUALIZER_VALIDATION_DIR="${UK_WSR_VISUALIZER_VALIDATION_DIR:-${UK_WSR_VISUALIZER_DATA_DIR}/validation/wct}"
UK_WSR_VISUALIZER_OBJECT_STORE_CONFIG="${UK_WSR_VISUALIZER_OBJECT_STORE_CONFIG:-/etc/uk-wsr-visualizer/object_store.toml}"
UK_WSR_VISUALIZER_OBJECT_STORE_MANIFEST="${UK_WSR_VISUALIZER_OBJECT_STORE_MANIFEST:-${UK_WSR_VISUALIZER_DATA_DIR}/object-store/latest-manifest.json}"
UK_WSR_VISUALIZER_BIN="${UK_WSR_VISUALIZER_BIN:-/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer}"
BASE_URL="${UK_WSR_VISUALIZER_SMOKE_BASE_URL:-http://127.0.0.1:8000}"
SMOKE_DIR="${UK_WSR_VISUALIZER_DATA_DIR}/object-store/remote-smoke"

mkdir -p "${SMOKE_DIR}"

curl --fail --silent --show-error "${BASE_URL}/api/status" >"${SMOKE_DIR}/api-status.json"
curl --fail --silent --show-error "${BASE_URL}/api/catalog/summary" >"${SMOKE_DIR}/catalog-summary.json"
curl --fail --silent --show-error "${BASE_URL}/api/object-store/status" >"${SMOKE_DIR}/object-store-status.json"
curl --fail --silent --show-error "${BASE_URL}/api/freshness?require_object_store=true&require_wct_validation=true" >"${SMOKE_DIR}/freshness-strict.json"

"${UK_WSR_VISUALIZER_BIN}" object-store release-candidate \
  --config "${UK_WSR_VISUALIZER_OBJECT_STORE_CONFIG}" \
  --catalog "${UK_WSR_VISUALIZER_CATALOG}" \
  --manifest "${UK_WSR_VISUALIZER_OBJECT_STORE_MANIFEST}" \
  --staging-dir "${SMOKE_DIR}/staging" \
  --preview-dir "${UK_WSR_VISUALIZER_PREVIEW_DIR}" \
  --tile-dir "${UK_WSR_VISUALIZER_TILE_DIR}" \
  --export-dir "${UK_WSR_VISUALIZER_EXPORT_DIR}" \
  --validation-dir "${UK_WSR_VISUALIZER_VALIDATION_DIR}" \
  --plan-output "${SMOKE_DIR}/release-candidate-plan.json" \
  --output "${SMOKE_DIR}/release-candidate-summary.json"

python3 - <<PY
import json
from pathlib import Path

root = Path("${SMOKE_DIR}")
status = json.loads((root / "api-status.json").read_text())
summary = json.loads((root / "catalog-summary.json").read_text())
object_store = json.loads((root / "object-store-status.json").read_text())
freshness = json.loads((root / "freshness-strict.json").read_text())
release = json.loads((root / "release-candidate-summary.json").read_text())

assert status.get("ok") is True, status
assert "item_count" in summary, summary
assert object_store.get("ok") is True, object_store
assert freshness.get("ok") is True, freshness
assert release.get("ok") is True, release

print(
    json.dumps(
        {
            "api_ok": status["ok"],
            "catalog_item_count": summary["item_count"],
            "object_store_ok": object_store["ok"],
            "freshness_ok": freshness["ok"],
            "release_candidate_ok": release["ok"],
            "release_summary": str(root / "release-candidate-summary.json"),
        },
        indent=2,
        sort_keys=True,
    )
)
PY
REMOTE
