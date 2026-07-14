# UK WSR Visualizer Deployment Assets

These files target `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121`.

The workstation should serve the FastAPI app and static frontend. Catalog refresh, preview generation, object-store publication, and freshness checks are represented as systemd units so they can run predictably and be moved to JASMIN-side workers later.

## Paths

```text
/opt/uk-wsr-visualizer/
  repo/
  venv/
  data/
/etc/uk-wsr-visualizer/
  uk-wsr-visualizer.env
  object_store.toml
```

## Install Sequence

```bash
ssh ncas-rsg-cloud-workstation-ssh
sudo useradd --system --home /opt/uk-wsr-visualizer --shell /usr/sbin/nologin ukwsr
sudo mkdir -p /opt/uk-wsr-visualizer/{repo,venv,data} /etc/uk-wsr-visualizer
sudo chown -R ukwsr:ukwsr /opt/uk-wsr-visualizer
```

Copy or clone this repository into `/opt/uk-wsr-visualizer/repo`, then install:

```bash
sudo -u ukwsr python3 -m venv /opt/uk-wsr-visualizer/venv
sudo -u ukwsr /opt/uk-wsr-visualizer/venv/bin/pip install -e "/opt/uk-wsr-visualizer/repo[export,object-store]"
sudo install -m 0640 -o root -g ukwsr deploy/env/uk-wsr-visualizer.env.example /etc/uk-wsr-visualizer/uk-wsr-visualizer.env
sudo install -m 0640 -o root -g ukwsr configs/object_store.example.toml /etc/uk-wsr-visualizer/object_store.toml
```

Edit `/etc/uk-wsr-visualizer/uk-wsr-visualizer.env` and `/etc/uk-wsr-visualizer/object_store.toml` before enabling object-store publication.

## systemd

```bash
sudo install -m 0644 deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uk-wsr-visualizer-api.service
sudo systemctl enable --now uk-wsr-visualizer-catalog-refresh.timer
sudo systemctl enable --now uk-wsr-visualizer-preview-build.timer
sudo systemctl enable --now uk-wsr-visualizer-freshness-check.timer
```

Do not enable `uk-wsr-visualizer-object-store-publish.timer` until object-store credentials, CORS, and publication permission are confirmed:

```bash
sudo systemctl start uk-wsr-visualizer-object-store-publish.service
sudo systemctl enable --now uk-wsr-visualizer-object-store-publish.timer
```

## Nginx

```bash
sudo install -m 0644 deploy/nginx/uk-wsr-visualizer.conf /etc/nginx/sites-available/uk-wsr-visualizer.conf
sudo ln -sf /etc/nginx/sites-available/uk-wsr-visualizer.conf /etc/nginx/sites-enabled/uk-wsr-visualizer.conf
sudo nginx -t
sudo systemctl reload nginx
```

## Smoke Test

Deployment preflight on the host:

```bash
/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer deployment preflight \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --catalog /opt/uk-wsr-visualizer/data/catalog.json \
  --object-store-config /etc/uk-wsr-visualizer/object_store.toml \
  --object-store-manifest /opt/uk-wsr-visualizer/data/object-store/latest-manifest.json \
  --validation-dir /opt/uk-wsr-visualizer/data/validation \
  --base-url http://127.0.0.1:8000 \
  --require-object-store
```

Local API:

```bash
bash deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh http://127.0.0.1:8000
```

Through Nginx:

```bash
bash deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh http://130.246.214.121
```

Remote host release readiness:

```bash
bash deploy/bin/uk-wsr-visualizer-remote-release-smoke.sh ncas-rsg-cloud-workstation-ssh http://127.0.0.1:8000
```

This SSHes to the workstation, loads `/etc/uk-wsr-visualizer/uk-wsr-visualizer.env`, checks the local API, runs strict freshness checks, and runs `uk-wsr-visualizer object-store release-candidate` using the host's configured catalog, manifest, previews, tiles, exports, and validation report paths.

## Dry-Run Object Store

Before enabling live publish, run as `ukwsr`:

```bash
/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer object-store plan \
  --config /etc/uk-wsr-visualizer/object_store.toml \
  --catalog /opt/uk-wsr-visualizer/data/catalog.json \
  --staging-dir /opt/uk-wsr-visualizer/data/object-store/staging \
  --preview-dir /opt/uk-wsr-visualizer/data/previews \
  --tile-dir /opt/uk-wsr-visualizer/data/tiles \
  --export-dir /opt/uk-wsr-visualizer/data/exports \
  --validation-dir /opt/uk-wsr-visualizer/data/validation \
  --output /opt/uk-wsr-visualizer/data/object-store/plan.json

/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer object-store sync \
  --config /etc/uk-wsr-visualizer/object_store.toml \
  --plan /opt/uk-wsr-visualizer/data/object-store/plan.json \
  --manifest /opt/uk-wsr-visualizer/data/object-store/synced.json

/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer object-store verify \
  --config /etc/uk-wsr-visualizer/object_store.toml \
  --manifest /opt/uk-wsr-visualizer/data/object-store/synced.json \
  --output /opt/uk-wsr-visualizer/data/object-store/latest-manifest.json

/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer freshness check \
  --catalog /opt/uk-wsr-visualizer/data/catalog.json \
  --object-store-manifest /opt/uk-wsr-visualizer/data/object-store/latest-manifest.json \
  --require-object-store

/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer object-store release-candidate \
  --config /etc/uk-wsr-visualizer/object_store.toml \
  --catalog /opt/uk-wsr-visualizer/data/catalog.json \
  --manifest /opt/uk-wsr-visualizer/data/object-store/latest-manifest.json \
  --staging-dir /opt/uk-wsr-visualizer/data/object-store/release-candidate-staging \
  --preview-dir /opt/uk-wsr-visualizer/data/previews \
  --tile-dir /opt/uk-wsr-visualizer/data/tiles \
  --export-dir /opt/uk-wsr-visualizer/data/exports \
  --validation-dir /opt/uk-wsr-visualizer/data/validation \
  --plan-output /opt/uk-wsr-visualizer/data/object-store/release-candidate-plan.json \
  --output /opt/uk-wsr-visualizer/data/object-store/release-candidate-summary.json
```

Add `--execute` only after the plan has been inspected and the JASMIN Object Store credentials are installed.

## Avocet Data Production

Aggregate rebuilds, pvol generation, integrity checks, and pvol object-store
uploads are JASMIN-only operations. They are intentionally not shipped as app
deployment assets.

The operational pipeline lives on JASMIN at:

```text
/home/users/rrniii/bin/avocet_pipeline
```

The daily cron on `cron-01.jasmin.ac.uk` points to:

```text
/home/users/rrniii/bin/avocet_pipeline/tools/jasmin_pipeline/run_daily_avocet_pipeline.sh
```
