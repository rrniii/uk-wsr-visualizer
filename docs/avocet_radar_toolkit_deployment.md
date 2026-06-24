# Avocet Radar Toolkit Deployment

## Target

Use `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121` for the web implementation target.

The web host should run the API and static frontend. Heavy catalog scans, preview generation, object-store sync, and large exports should run on JASMIN/GWS-side workers or LOTUS where possible.

## Current Access Status

As of 2026-06-24, the deployment assets are ready but installation on the target host is blocked by SSH access:

- `ssh ncas-rsg-cloud-workstation-ssh` does not resolve from the local machine or from JASMIN `sci1`.
- `ssh 130.246.214.121` reaches the host but returns `Permission denied (publickey)` for user `rrniii`.

To proceed with the live web deployment, authorize the user's SSH public key for `rrniii@130.246.214.121` or provide the correct SSH alias, username, and key. After SSH works, run the install sequence below and then the remote smoke tests.

Current tested public key fingerprint for the local/JASMIN key is:

```text
SHA256:m7aZGxf4nSxTkmPyV1TIMsHTBDmUzwIqPWooKbS6EDY
```

## Recommended Layout

```text
/opt/avocet-radar-toolkit/
  repo/
  venv/
  data/
    catalog.json
    previews/
    tiles/
    exports/
    sessions/
/etc/systemd/system/avocet-wct-api.service
/etc/systemd/system/avocet-wct-catalog.timer
/etc/systemd/system/avocet-wct-preview.timer
```

Repository-owned deployment assets live under `deploy/`:

- `deploy/env/avocet-wct.env.example`
- `deploy/systemd/avocet-wct-api.service`
- `deploy/systemd/avocet-wct-catalog-refresh.service`
- `deploy/systemd/avocet-wct-preview-build.service`
- `deploy/systemd/avocet-wct-object-store-publish.service`
- `deploy/systemd/avocet-wct-freshness-check.service`
- `deploy/nginx/avocet-wct.conf`
- `deploy/bin/avocet-wct-remote-smoke-test.sh`

## Install

```bash
ssh ncas-rsg-cloud-workstation-ssh
cd /opt/avocet-radar-toolkit/repo
python3 -m venv /opt/avocet-radar-toolkit/venv
. /opt/avocet-radar-toolkit/venv/bin/activate
pip install -e ".[export]"
```

Use [deploy/README.md](../deploy/README.md) for the repeatable install sequence, including the `avocet` service user, `/etc/avocet-wct/avocet-wct.env`, Nginx, and systemd timers.

## Build Catalog

```bash
AVOCET_WCT_DATA_DIR=/opt/avocet-radar-toolkit/data \
avocet-wct catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output /opt/avocet-radar-toolkit/data/catalog.json \
  --object-store-base https://TENANCY-o.s3-ext.jc.rl.ac.uk
```

## Run API

```bash
AVOCET_WCT_DATA_DIR=/opt/avocet-radar-toolkit/data \
AVOCET_WCT_CATALOG=/opt/avocet-radar-toolkit/data/catalog.json \
avocet-wct api --host 127.0.0.1 --port 8000
```

Put Nginx in front of the API and proxy `/` and `/api/` to `127.0.0.1:8000`.

## Object Store

The object-store mirror should use keys matching the application helpers:

```text
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
uk-radar/index.html
uk-radar/dataset.json
uk-radar/catalog/stac/catalog.json
uk-radar/catalog/stac/avocet-uk-radar-aggregate-h5/collection.json
uk-radar/catalog/stac/avocet-uk-radar-aggregate-h5/{item_id}.json
uk-radar/previews/radar={radar}/date={YYYYMMDD}/...
uk-radar/tiles/radar={radar}/date={YYYYMMDD}/...
uk-radar/checksums/sha256/{YYYY}/{radar}.json
uk-radar/validation/wct/...
uk-radar/exports/job={job_id}/...
```

Configure anonymous read only after UK radar redistribution terms are confirmed. For browser access, configure CORS with `GET` and `HEAD`.

The publication workflow is now:

```bash
avocet-wct object-store plan
avocet-wct object-store sync
avocet-wct object-store verify
avocet-wct object-store publish
avocet-wct object-store reconcile
avocet-wct freshness check
```

All object-store operations are dry-run by default. The systemd publisher uses `--execute`, so only enable `avocet-wct-object-store-publish.timer` after the JASMIN tenancy, buckets, credentials, CORS, public redistribution permission, and required WCT validation reports are confirmed.

The Chenies 2018 public object-store release is live as run `chenies-2018-full-20260624T021843Z`:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public/uk-radar/status.json
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public/uk-radar/manifests/latest.json
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public/uk-radar/catalog/inventory/catalog.json
```

The latest public manifest has 757 verified objects and CORS has been smoke-tested from origin `http://130.246.214.121`.

## Minimal systemd Service

```ini
[Unit]
Description=Avocet Radar Toolkit API
After=network.target

[Service]
User=avocet
WorkingDirectory=/opt/avocet-radar-toolkit/repo
Environment=AVOCET_WCT_DATA_DIR=/opt/avocet-radar-toolkit/data
Environment=AVOCET_WCT_CATALOG=/opt/avocet-radar-toolkit/data/catalog.json
ExecStart=/opt/avocet-radar-toolkit/venv/bin/avocet-wct api --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Verification

```bash
curl http://127.0.0.1:8000/api/status
curl http://127.0.0.1:8000/api/radars
curl http://127.0.0.1:8000/api/catalog/summary
curl http://127.0.0.1:8000/api/freshness
curl 'http://127.0.0.1:8000/api/freshness?require_object_store=true&require_wct_validation=true'
curl http://127.0.0.1:8000/api/public/dataset
curl http://127.0.0.1:8000/public
```

Run host preflight before release-candidate publication:

```bash
avocet-wct deployment preflight \
  --catalog /opt/avocet-radar-toolkit/data/catalog.json \
  --object-store-config /etc/avocet-wct/object_store.toml \
  --object-store-manifest /opt/avocet-radar-toolkit/data/object-store/latest-manifest.json \
  --validation-dir /opt/avocet-radar-toolkit/data/validation/wct \
  --base-url http://127.0.0.1:8000 \
  --require-object-store \
  --require-wct-validation
```

Then open the public Nginx URL and verify catalog search, preview loading, tile-pyramid generation, four-panel view, contours, animation stepping, metadata export, export download links, KMZ export, session save/load, project file download/import, object URL display, and native HDF5 export.

Run the repository smoke test on the host:

```bash
bash deploy/bin/avocet-wct-remote-smoke-test.sh http://127.0.0.1:8000
bash deploy/bin/avocet-wct-remote-smoke-test.sh http://130.246.214.121
bash deploy/bin/avocet-wct-remote-release-smoke.sh ncas-rsg-cloud-workstation-ssh http://127.0.0.1:8000
```

For WCT-style export parity checks, verify `geotiff`, `cf_netcdf`, `geojson`, `shapefile`, and georeferenced `kmz` outputs against representative Avocet aggregate files and WCT 4.9.1 output.

Use [docs/wct_parity_validation.md](wct_parity_validation.md) for the WCT 4.9.1 batch validation workflow.
