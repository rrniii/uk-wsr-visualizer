# Avocet Radar Toolkit Deployment Assets

These files target `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121`.

The workstation should serve the FastAPI app and static frontend. Catalog refresh, preview generation, object-store publication, and freshness checks are represented as systemd units so they can run predictably and be moved to JASMIN-side workers later.

## Paths

```text
/opt/avocet-radar-toolkit/
  repo/
  venv/
  data/
/etc/avocet-wct/
  avocet-wct.env
  object_store.toml
```

## Install Sequence

```bash
ssh ncas-rsg-cloud-workstation-ssh
sudo useradd --system --home /opt/avocet-radar-toolkit --shell /usr/sbin/nologin avocet
sudo mkdir -p /opt/avocet-radar-toolkit/{repo,venv,data} /etc/avocet-wct
sudo chown -R avocet:avocet /opt/avocet-radar-toolkit
```

Copy or clone this repository into `/opt/avocet-radar-toolkit/repo`, then install:

```bash
sudo -u avocet python3 -m venv /opt/avocet-radar-toolkit/venv
sudo -u avocet /opt/avocet-radar-toolkit/venv/bin/pip install -e "/opt/avocet-radar-toolkit/repo[export,object-store]"
sudo install -m 0640 -o root -g avocet deploy/env/avocet-wct.env.example /etc/avocet-wct/avocet-wct.env
sudo install -m 0640 -o root -g avocet configs/object_store.example.toml /etc/avocet-wct/object_store.toml
```

Edit `/etc/avocet-wct/avocet-wct.env` and `/etc/avocet-wct/object_store.toml` before enabling object-store publication.

## systemd

```bash
sudo install -m 0644 deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now avocet-wct-api.service
sudo systemctl enable --now avocet-wct-catalog-refresh.timer
sudo systemctl enable --now avocet-wct-preview-build.timer
sudo systemctl enable --now avocet-wct-freshness-check.timer
```

Do not enable `avocet-wct-object-store-publish.timer` until object-store credentials, CORS, and publication permission are confirmed:

```bash
sudo systemctl start avocet-wct-object-store-publish.service
sudo systemctl enable --now avocet-wct-object-store-publish.timer
```

## Nginx

```bash
sudo install -m 0644 deploy/nginx/avocet-wct.conf /etc/nginx/sites-available/avocet-wct.conf
sudo ln -sf /etc/nginx/sites-available/avocet-wct.conf /etc/nginx/sites-enabled/avocet-wct.conf
sudo nginx -t
sudo systemctl reload nginx
```

## Smoke Test

Deployment preflight on the host:

```bash
/opt/avocet-radar-toolkit/venv/bin/avocet-wct deployment preflight \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --catalog /opt/avocet-radar-toolkit/data/catalog.json \
  --object-store-config /etc/avocet-wct/object_store.toml \
  --object-store-manifest /opt/avocet-radar-toolkit/data/object-store/latest-manifest.json \
  --validation-dir /opt/avocet-radar-toolkit/data/validation/wct \
  --base-url http://127.0.0.1:8000 \
  --require-object-store \
  --require-wct-validation
```

Local API:

```bash
bash deploy/bin/avocet-wct-remote-smoke-test.sh http://127.0.0.1:8000
```

Through Nginx:

```bash
bash deploy/bin/avocet-wct-remote-smoke-test.sh http://130.246.214.121
```

Remote host release readiness:

```bash
bash deploy/bin/avocet-wct-remote-release-smoke.sh ncas-rsg-cloud-workstation-ssh http://127.0.0.1:8000
```

This SSHes to the workstation, loads `/etc/avocet-wct/avocet-wct.env`, checks the local API, runs strict freshness with WCT validation required, and runs `avocet-wct object-store release-candidate` using the host's configured catalog, manifest, previews, tiles, exports, and validation report paths.

## Dry-Run Object Store

Before enabling live publish, run as `avocet`:

```bash
/opt/avocet-radar-toolkit/venv/bin/avocet-wct object-store plan \
  --config /etc/avocet-wct/object_store.toml \
  --catalog /opt/avocet-radar-toolkit/data/catalog.json \
  --staging-dir /opt/avocet-radar-toolkit/data/object-store/staging \
  --preview-dir /opt/avocet-radar-toolkit/data/previews \
  --tile-dir /opt/avocet-radar-toolkit/data/tiles \
  --export-dir /opt/avocet-radar-toolkit/data/exports \
  --validation-dir /opt/avocet-radar-toolkit/data/validation/wct \
  --output /opt/avocet-radar-toolkit/data/object-store/plan.json

/opt/avocet-radar-toolkit/venv/bin/avocet-wct object-store sync \
  --config /etc/avocet-wct/object_store.toml \
  --plan /opt/avocet-radar-toolkit/data/object-store/plan.json \
  --manifest /opt/avocet-radar-toolkit/data/object-store/synced.json

/opt/avocet-radar-toolkit/venv/bin/avocet-wct object-store verify \
  --config /etc/avocet-wct/object_store.toml \
  --manifest /opt/avocet-radar-toolkit/data/object-store/synced.json \
  --output /opt/avocet-radar-toolkit/data/object-store/latest-manifest.json

/opt/avocet-radar-toolkit/venv/bin/avocet-wct freshness check \
  --catalog /opt/avocet-radar-toolkit/data/catalog.json \
  --object-store-manifest /opt/avocet-radar-toolkit/data/object-store/latest-manifest.json \
  --require-object-store \
  --require-wct-validation

/opt/avocet-radar-toolkit/venv/bin/avocet-wct object-store release-candidate \
  --config /etc/avocet-wct/object_store.toml \
  --catalog /opt/avocet-radar-toolkit/data/catalog.json \
  --manifest /opt/avocet-radar-toolkit/data/object-store/latest-manifest.json \
  --staging-dir /opt/avocet-radar-toolkit/data/object-store/release-candidate-staging \
  --preview-dir /opt/avocet-radar-toolkit/data/previews \
  --tile-dir /opt/avocet-radar-toolkit/data/tiles \
  --export-dir /opt/avocet-radar-toolkit/data/exports \
  --validation-dir /opt/avocet-radar-toolkit/data/validation/wct \
  --plan-output /opt/avocet-radar-toolkit/data/object-store/release-candidate-plan.json \
  --output /opt/avocet-radar-toolkit/data/object-store/release-candidate-summary.json
```

Add `--execute` only after the plan has been inspected and the JASMIN Object Store credentials are installed.
