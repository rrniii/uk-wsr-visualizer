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

## JASMIN Avocet Production Pipeline

The supported Avocet production workflow is documented in `docs/avocet_production_pipeline.md`.

In short:

- aggregate HDF5 is rebuilt from `/badc/ukmo-nimrod/data/single-site` and kept on GWS;
- pvol HDF5 is generated under `/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site`;
- only pvol is uploaded to HPOS under `ukmo-nimrod/pvol/...`;
- the pvol catalog is uploaded under `ukmo-nimrod/catalog/pvol/...`;
- the old `uk-radar/raw-volume` and aggregate object-store backfill scripts are retired.

Full rebuild:

```bash
cd /home/users/rrniii/uk-wsr-visualizer
nohup env MAX_ACTIVE=2500 PVOL_UPLOAD_WORKERS=96 \
  bash tools/jasmin_pipeline/run_full_avocet_rebuild.sh \
  > /gws/ssde/j25a/ncas_radar/vol2/avocet/full_rebuild_logs/full_rebuild.nohup 2>&1 < /dev/null &
```

Daily cron entry on `cron-01.jasmin.ac.uk`:

```cron
CRON_TZ=UTC
0 20 * * * crontamer -t 23h -l /home/users/rrniii/uk-wsr-visualizer/tools/jasmin_pipeline/run_daily_avocet_pipeline.sh
```
