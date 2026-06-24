#!/usr/bin/env bash
set -euo pipefail

AWS_BIN=${AWS_BIN:-aws}
AWS_PROFILE_NAME=${AWS_PROFILE_NAME:-ncas-radar-o}
AWS_REGION=${AWS_REGION:-us-east-1}
ENDPOINT_URL=${ENDPOINT_URL:-http://ncas-radar-o.s3.jc.rl.ac.uk}
BUCKET=${BUCKET:-uk-wsr-visualizer-public}
SRC_ROOT=${SRC_ROOT:-/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site/chenies/2018/20180401}
CATALOG=${CATALOG:-/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/raw-volume-catalog/smoke/catalog-fast.json}

BASE_URI="s3://${BUCKET}/uk-radar/raw-volume/radar=chenies/year=2018/date=20180401"
CATALOG_URI="s3://${BUCKET}/uk-radar/catalog/inventory/raw-volume/chenies/2018/20180401/catalog.json"

export AWS_REQUEST_CHECKSUM_CALCULATION=when_required
export AWS_RESPONSE_CHECKSUM_VALIDATION=when_required

"${AWS_BIN}" --profile "${AWS_PROFILE_NAME}" --endpoint-url "${ENDPOINT_URL}" \
  --region "${AWS_REGION}" \
  s3 sync "${SRC_ROOT}/lp/" "${BASE_URI}/pulse=lp/" \
  --only-show-errors --size-only --acl public-read

"${AWS_BIN}" --profile "${AWS_PROFILE_NAME}" --endpoint-url "${ENDPOINT_URL}" \
  --region "${AWS_REGION}" \
  s3 sync "${SRC_ROOT}/sp/" "${BASE_URI}/pulse=sp/" \
  --only-show-errors --size-only --acl public-read

"${AWS_BIN}" --profile "${AWS_PROFILE_NAME}" --endpoint-url "${ENDPOINT_URL}" \
  --region "${AWS_REGION}" \
  s3 cp "${CATALOG}" "${CATALOG_URI}" \
  --only-show-errors --content-type application/json --acl public-read

"${AWS_BIN}" --profile "${AWS_PROFILE_NAME}" --endpoint-url "${ENDPOINT_URL}" \
  --region "${AWS_REGION}" \
  s3 ls "${BASE_URI}/" --recursive --summarize | tail -5

echo "catalog_url=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/${BUCKET}/uk-radar/catalog/inventory/raw-volume/chenies/2018/20180401/catalog.json"
