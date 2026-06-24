#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"

curl --fail --silent --show-error "${BASE_URL}/api/status" >/tmp/avocet-wct-status.json
curl --fail --silent --show-error "${BASE_URL}/api/radars" >/tmp/avocet-wct-radars.json
curl --fail --silent --show-error "${BASE_URL}/api/catalog/summary" >/tmp/avocet-wct-catalog-summary.json
curl --fail --silent --show-error "${BASE_URL}/api/object-store/status" >/tmp/avocet-wct-object-store-status.json
curl --fail --silent --show-error "${BASE_URL}/api/freshness" >/tmp/avocet-wct-freshness.json

python3 - <<'PY'
import json
from pathlib import Path

status = json.loads(Path("/tmp/avocet-wct-status.json").read_text())
radars = json.loads(Path("/tmp/avocet-wct-radars.json").read_text())
summary = json.loads(Path("/tmp/avocet-wct-catalog-summary.json").read_text())
object_store = json.loads(Path("/tmp/avocet-wct-object-store-status.json").read_text())
freshness = json.loads(Path("/tmp/avocet-wct-freshness.json").read_text())

assert status.get("ok") is True, status
assert len(radars.get("radars", [])) >= 10, radars
assert "item_count" in summary, summary
assert "ok" in object_store, object_store
assert "checks" in freshness, freshness

print(
    json.dumps(
        {
            "api_ok": status["ok"],
            "radar_count": len(radars["radars"]),
            "catalog_item_count": summary["item_count"],
            "object_store_ok": object_store["ok"],
            "freshness_ok": freshness["ok"],
        },
        indent=2,
        sort_keys=True,
    )
)
PY
