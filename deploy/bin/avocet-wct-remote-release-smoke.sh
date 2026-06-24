#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-ncas-rsg-cloud-workstation-ssh}"
BASE_URL="${2:-http://127.0.0.1:8000}"

ssh -o StrictHostKeyChecking=accept-new "${HOST}" "AVOCET_WCT_SMOKE_BASE_URL='${BASE_URL}' bash -s" <<'REMOTE'
set -euo pipefail

if [[ -f /etc/avocet-wct/avocet-wct.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/avocet-wct/avocet-wct.env
  set +a
fi

AVOCET_WCT_DATA_DIR="${AVOCET_WCT_DATA_DIR:-/opt/avocet-radar-toolkit/data}"
AVOCET_WCT_CATALOG="${AVOCET_WCT_CATALOG:-${AVOCET_WCT_DATA_DIR}/catalog.json}"
AVOCET_WCT_PREVIEW_DIR="${AVOCET_WCT_PREVIEW_DIR:-${AVOCET_WCT_DATA_DIR}/previews}"
AVOCET_WCT_TILE_DIR="${AVOCET_WCT_TILE_DIR:-${AVOCET_WCT_DATA_DIR}/tiles}"
AVOCET_WCT_EXPORT_DIR="${AVOCET_WCT_EXPORT_DIR:-${AVOCET_WCT_DATA_DIR}/exports}"
AVOCET_WCT_VALIDATION_DIR="${AVOCET_WCT_VALIDATION_DIR:-${AVOCET_WCT_DATA_DIR}/validation/wct}"
AVOCET_WCT_OBJECT_STORE_CONFIG="${AVOCET_WCT_OBJECT_STORE_CONFIG:-/etc/avocet-wct/object_store.toml}"
AVOCET_WCT_OBJECT_STORE_MANIFEST="${AVOCET_WCT_OBJECT_STORE_MANIFEST:-${AVOCET_WCT_DATA_DIR}/object-store/latest-manifest.json}"
AVOCET_WCT_BIN="${AVOCET_WCT_BIN:-/opt/avocet-radar-toolkit/venv/bin/avocet-wct}"
BASE_URL="${AVOCET_WCT_SMOKE_BASE_URL:-http://127.0.0.1:8000}"
SMOKE_DIR="${AVOCET_WCT_DATA_DIR}/object-store/remote-smoke"

mkdir -p "${SMOKE_DIR}"

curl --fail --silent --show-error "${BASE_URL}/api/status" >"${SMOKE_DIR}/api-status.json"
curl --fail --silent --show-error "${BASE_URL}/api/catalog/summary" >"${SMOKE_DIR}/catalog-summary.json"
curl --fail --silent --show-error "${BASE_URL}/api/object-store/status" >"${SMOKE_DIR}/object-store-status.json"
curl --fail --silent --show-error "${BASE_URL}/api/freshness?require_object_store=true&require_wct_validation=true" >"${SMOKE_DIR}/freshness-strict.json"

"${AVOCET_WCT_BIN}" object-store release-candidate \
  --config "${AVOCET_WCT_OBJECT_STORE_CONFIG}" \
  --catalog "${AVOCET_WCT_CATALOG}" \
  --manifest "${AVOCET_WCT_OBJECT_STORE_MANIFEST}" \
  --staging-dir "${SMOKE_DIR}/staging" \
  --preview-dir "${AVOCET_WCT_PREVIEW_DIR}" \
  --tile-dir "${AVOCET_WCT_TILE_DIR}" \
  --export-dir "${AVOCET_WCT_EXPORT_DIR}" \
  --validation-dir "${AVOCET_WCT_VALIDATION_DIR}" \
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
