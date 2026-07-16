# UK WSR Visualizer Install and Use Guide

This guide is for users and collaborators who want to run the UK WSR quick-look access and visualisation toolkit.

## Repository Status

The repository currently exists at:

```text
https://github.com/rrniii/uk-wsr-visualizer
```

If the repository is private, installation from GitHub requires collaborator access. Before a public release, confirm the long-term repository home, visibility, licence, source-data access statement, and citation wording.

Clone with the route appropriate for your GitHub access:

```bash
git clone git@github.com:rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
```

or:

```bash
git clone https://github.com/rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
```

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

The app is designed to use approved UK WSR aggregate HDF5 source objects as the source of truth. It does not require a special app-specific copy of the science data.

Default catalogue:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json
```

When a user selects a day, the local API first uses the public catalogue and any published field-index sidecar to populate time, variable, and elevation controls. It downloads a source HDF5 object only when a plot, export, or diagnostic needs the file:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

The source-file cache is size-bounded LRU storage. The default limit is 25 GB; the oldest unused files are evicted only when the limit is exceeded or when **Clear Raw Cache** is clicked in the UI.

## Basic Use

1. Open `macos/UK WSR Visualizer.app`.
2. Choose a radar and date range in **Data Selection**.
3. Click **Search Catalog**.
4. Use **Radar Controls** to choose a scan type, a long-name variable such as **Horizontal Reflectivity**, time, and elevation. The scan type states the available elevation angles and maximum range.
5. Step through time, change palette, adjust opacity, and filter range, azimuth, or values.
6. Use the map controls to pan and zoom. The PPI is georeferenced over the selected basemap.
7. Click on the PPI/map to identify the nearest radar value.

Only functional controls should appear in the current UI. Features that are not wired into the app should remain in CLI/API documentation until tested for user-facing release.

## Developer Install

Use Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,desktop,export,object-store]"
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

Print the current citation guidance:

```bash
uk-wsr-visualizer-citation
uk-wsr-visualizer-citation --json
```

## Object Store Setup

The planned object-store layout is documented in [jasmin_object_store_setup.md](jasmin_object_store_setup.md) and [ncas_radar_object_store_release.md](ncas_radar_object_store_release.md).

Current target buckets:

```text
uk-wsr-visualizer-staging
uk-wsr-visualizer-public
```

Current object-store project:

```text
ncas-radar-o
```

The app expects browser-readable catalog and approved source objects under:

```text
ukmo-nimrod/catalog/pvol/catalog.json
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
```

For community use, publish only approved source objects, configure CORS for browser reads, and keep operational sync jobs on JASMIN/GWS-side machines.

## Web Deployment

The planned web deployment is documented in the repository
[`deploy/README.md`](https://github.com/rrniii/uk-wsr-visualizer/blob/master/deploy/README.md)
and [uk_wsr_visualizer_deployment.md](uk_wsr_visualizer_deployment.md).
Confirm the stable public host name, access route, licence text,
source-data citation, and support contact before advertising a community
endpoint.
