# UK WSR Visualizer Deployment

> This page covers the web app deployment. It is not the Avocet data-production runbook.
> Aggregate/pvol creation, checking, and upload are maintained on JASMIN at `/home/users/rrniii/bin/avocet_pipeline`, outside this app repository.

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
/opt/uk-wsr-visualizer/
  repo/
  venv/
  data/
    catalog.json
    previews/
    tiles/
    exports/
    sessions/
/etc/systemd/system/uk-wsr-visualizer-api.service
/etc/systemd/system/uk-wsr-visualizer-catalog.timer
/etc/systemd/system/uk-wsr-visualizer-preview.timer
```

Repository-owned deployment assets live under `deploy/`:

- `deploy/env/uk-wsr-visualizer.env.example`
- `deploy/systemd/uk-wsr-visualizer-api.service`
- `deploy/systemd/uk-wsr-visualizer-catalog-refresh.service`
- `deploy/systemd/uk-wsr-visualizer-preview-build.service`
- `deploy/systemd/uk-wsr-visualizer-object-store-publish.service`
- `deploy/systemd/uk-wsr-visualizer-freshness-check.service`
- `deploy/nginx/uk-wsr-visualizer.conf`
- `deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh`

## Install

```bash
ssh ncas-rsg-cloud-workstation-ssh
cd /opt/uk-wsr-visualizer/repo
python3 -m venv /opt/uk-wsr-visualizer/venv
. /opt/uk-wsr-visualizer/venv/bin/activate
pip install -e ".[export]"
```

Use the repository
[`deploy/README.md`](https://github.com/rrniii/uk-wsr-visualizer/blob/master/deploy/README.md)
for the repeatable install sequence, including the `ukwsr` service user,
`/etc/uk-wsr-visualizer/uk-wsr-visualizer.env`, Nginx, and systemd timers.

## Build Catalog

```bash
UK_WSR_VISUALIZER_DATA_DIR=/opt/uk-wsr-visualizer/data \
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output /opt/uk-wsr-visualizer/data/catalog.json \
  --object-store-base https://TENANCY-o.s3-ext.jc.rl.ac.uk
```

## Run API

```bash
UK_WSR_VISUALIZER_DATA_DIR=/opt/uk-wsr-visualizer/data \
UK_WSR_VISUALIZER_CATALOG=/opt/uk-wsr-visualizer/data/catalog.json \
uk-wsr-visualizer api --host 127.0.0.1 --port 8000
```

Put Nginx in front of the API and proxy `/` and `/api/` to `127.0.0.1:8000`.

## Object Store

The object-store mirror should use keys matching the application helpers:

```text
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
uk-radar/index.html
uk-radar/dataset.json
uk-radar/catalog/stac/catalog.json
uk-radar/catalog/stac/uk-wsr-aggregate-h5/collection.json
uk-radar/catalog/stac/uk-wsr-aggregate-h5/{item_id}.json
uk-radar/previews/radar={radar}/date={YYYYMMDD}/...
uk-radar/tiles/radar={radar}/date={YYYYMMDD}/...
uk-radar/checksums/sha256/{YYYY}/{radar}.json
uk-radar/validation/...
uk-radar/exports/job={job_id}/...
```

Configure anonymous read only after UK radar redistribution terms are confirmed. For browser access, configure CORS with `GET` and `HEAD`.

The publication workflow is now:

```bash
uk-wsr-visualizer object-store plan
uk-wsr-visualizer object-store sync
uk-wsr-visualizer object-store verify
uk-wsr-visualizer object-store publish
uk-wsr-visualizer object-store reconcile
uk-wsr-visualizer freshness check
```

All object-store operations are dry-run by default. The systemd publisher uses `--execute`, so only enable `uk-wsr-visualizer-object-store-publish.timer` after the JASMIN tenancy, buckets, credentials, CORS, public redistribution permission, and release validation checks are confirmed.

The Chenies 2018 public object-store release is live as run `chenies-2018-full-20260624T021843Z`:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/status.json
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/manifests/latest.json
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

The latest public manifest has 757 verified objects and CORS has been smoke-tested from origin `http://130.246.214.121`.

## Minimal systemd Service

```ini
[Unit]
Description=UK WSR Visualizer API
After=network.target

[Service]
User=ukwsr
WorkingDirectory=/opt/uk-wsr-visualizer/repo
Environment=UK_WSR_VISUALIZER_DATA_DIR=/opt/uk-wsr-visualizer/data
Environment=UK_WSR_VISUALIZER_CATALOG=/opt/uk-wsr-visualizer/data/catalog.json
ExecStart=/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer api --host 127.0.0.1 --port 8000
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
curl 'http://127.0.0.1:8000/api/freshness?require_object_store=true'
curl http://127.0.0.1:8000/api/public/dataset
curl http://127.0.0.1:8000/public
```

Run host preflight before release-candidate publication:

```bash
uk-wsr-visualizer deployment preflight \
  --catalog /opt/uk-wsr-visualizer/data/catalog.json \
  --object-store-config /etc/uk-wsr-visualizer/object_store.toml \
  --object-store-manifest /opt/uk-wsr-visualizer/data/object-store/latest-manifest.json \
  --validation-dir /opt/uk-wsr-visualizer/data/validation \
  --base-url http://127.0.0.1:8000 \
  --require-object-store
```

Then open the public Nginx URL and verify catalog search, preview loading, tile-pyramid generation, four-panel view, contours, animation stepping, metadata export, export download links, KMZ export, session save/load, project file download/import, object URL display, and native HDF5 export.

Run the repository smoke test on the host:

```bash
bash deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh http://127.0.0.1:8000
bash deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh http://130.246.214.121
bash deploy/bin/uk-wsr-visualizer-remote-release-smoke.sh ncas-rsg-cloud-workstation-ssh http://127.0.0.1:8000
```
