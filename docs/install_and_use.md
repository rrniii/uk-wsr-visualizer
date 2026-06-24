# UK WSR Visualizer Install and Use Guide

This guide is for collaborators who want to run the current UK radar WCT-style toolkit.

## Repository Status

This checkout is not yet published to GitHub from this machine. The local repository currently has no commits and no configured remote. Before other users can install from GitHub, create the repository, commit the files, add a remote, and push.

Expected publish sequence:

```bash
git status --short --branch
git add .gitignore README.md pyproject.toml src tests docs deploy configs examples jasmin_code macos tools
git commit -m "Initial UK WSR Visualizer implementation"
git remote add origin git@github.com:NCAS-CMS/uk-wsr-visualizer.git
git push -u origin master
```

Adjust the GitHub organisation and repository name before running those commands.

## macOS App

The local app bundle is:

```text
macos/UK WSR Visualizer.app
```

Double-click it in Finder. On first launch it creates a Python virtual environment and installs the bundled checkout into:

```text
~/Library/Application Support/UK WSR Visualizer/
```

Logs are written to:

```text
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
```

The app opens a local browser UI at `http://127.0.0.1:8765`.

## Data Model

The app is designed to use the raw UK WSR aggregate HDF5 files as the source of truth. It does not require a special app-specific copy of the science data.

Default public catalog:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

When a user selects an item, the local API downloads only the selected raw aggregate into a disposable cache:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

The cache can be cleared with **Clear Raw Cache** in the UI. It is also bounded by TTL and size settings.

## Basic Use

1. Open `macos/UK WSR Visualizer.app`.
2. Choose a radar, date range, pulse, and quantity in **Data Selection**.
3. Click **Search Catalog**.
4. Select the returned item and source.
5. Use **Radar Controls** to step through time, switch quantity, change palette, adjust opacity, and filter range, azimuth, or values.
6. Use the map controls to pan and zoom. The PPI is georeferenced over the selected basemap.
7. Click on the PPI/map to identify the nearest radar value.

Only functional controls should appear in the current UI. Features such as full export workflows, contours, tiles, and derived math products remain CLI/API capabilities or future UI work until they are wired into the app.

## Developer Install

Use Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store]"
```

Run the API and static UI:

```bash
uk-wsr-visualizer api --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Run tests:

```bash
pytest
```

## Object Store Setup

The planned public object-store layout is documented in [jasmin_object_store_setup.md](jasmin_object_store_setup.md) and [ncas_radar_object_store_release.md](ncas_radar_object_store_release.md).

Current target buckets:

```text
uk-wsr-visualizer-staging
uk-wsr-visualizer-public
```

Current object-store project:

```text
ncas-radar-o
```

The app expects public browser-readable catalog and raw aggregate objects under:

```text
uk-radar/catalog/inventory/catalog.json
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
```

For community use, publish the catalog and raw aggregates to the public bucket, configure CORS for browser reads, and keep operational sync jobs on JASMIN/GWS-side machines.

## Web Deployment

The planned web implementation target is:

```text
ncas-rsg-cloud-workstation-ssh
130.246.214.121
```

See [../deploy/README.md](../deploy/README.md) and [uk_wsr_visualizer_deployment.md](uk_wsr_visualizer_deployment.md) for the systemd, Nginx, API, catalog refresh, object-store sync, and smoke-test plan.
