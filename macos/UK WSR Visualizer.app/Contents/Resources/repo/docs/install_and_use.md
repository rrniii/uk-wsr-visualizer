<p align="center">
  <img src="assets/uk-wsr-visualizer-logo.png" alt="UK WSR Visualizer radar logo" width="130">
</p>

# UK WSR Visualizer Install and Use Guide

This guide is for collaborators and beta testers who want to run UK WSR Visualizer.

## What The App Does

UK WSR Visualizer lets you search UK radar days, open radar variables, choose sweep elevation, step through times, compare four panels, and inspect radar values on a georeferenced map.

The macOS app runs locally on your Mac. It connects to a public JASMIN Object Store catalog and downloads selected radar source files into a disposable local cache when plotting is needed.

## Data Source

The original observations are Met Office NIMROD single-site UK radar files held by CEDA. On JASMIN, those original files are mounted at:

```text
/badc/ukmo-nimrod/data/single-site
/badc/ukmo-nimrod/data/single-site/storage_by_year
```

The Avocet/JASMIN processing pipeline converts the original CEDA/NIMROD files into daily ODIM-like UK WSR aggregate HDF5 files at:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

Approved aggregate HDF5 files, raw-volume objects, and catalog metadata are mirrored to the JASMIN Object Store for the app:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

The default public catalog is:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

The app does not use a separate app-specific copy of the science data. It uses the public catalog, fetches the selected source object when needed, scans HDF5 metadata locally, and caches only what it needs for the current work.

## macOS App Install

The local app bundle is:

```text
macos/UK WSR Visualizer.app
```

To run it:

1. Double-click `UK WSR Visualizer.app` in Finder.
2. On first launch, wait on the logo screen while the app creates its local Python environment.
3. If macOS blocks the app because it is unsigned, right-click the app and choose **Open**.
4. The app opens its own macOS window and serves the viewer locally from `http://127.0.0.1:8765`.

Runtime files are stored in:

```text
~/Library/Application Support/UK WSR Visualizer/
```

Logs are written to:

```text
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
```

If the app does not start, send that log file with your bug report.

## Local Cache

Downloaded source files are cached at:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

The cache is disposable:

- Default TTL: 1 hour.
- Default max size: 25 GB.
- Press **Clear Raw Cache** in the app to remove cached radar source files.
- The app will re-download a source file from the object store if it is needed again.

## Basic Workflow

1. Open the app.
2. In **Data Selection**, choose a start date, end date, radar, and pulse.
3. Click **Search Catalog**.
4. In **Radar Controls**, choose the catalog item, variable, time, and elevation.
5. Use the map like a normal map: scroll to zoom, drag to pan, and click a point to read the plotted radar value.
6. Use the palette and opacity controls to adjust the display.
7. Use **Prev Time** and **Next Time** to step through the linked time list.
8. Use **4 Panel** to compare multiple items, variables, or elevations at one linked time.

## 4-Panel Comparison

In 4-panel mode:

- Each panel has its own `Item`, `Variable`, and `Elevation` selectors.
- The time control is shared across all four panels.
- If a panel does not have the linked time, it shows a message instead of plotting a different time silently.
- Clicks and hover readouts report the value from the panel you are using.

## Developer Install

Use Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store]"
```

Build a local catalog from the JASMIN GWS aggregate tree:

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output data/catalog.json
```

Run the API and static UI:

```bash
uk-wsr-visualizer api --catalog data/catalog.json --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Run tests:

```bash
pytest
```

## Object Store Layout

The app expects public catalog and data objects under:

```text
uk-radar/catalog/inventory/catalog.json
uk-radar/catalog/stac/...
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
uk-radar/raw-volume/radar={radar}/year={YYYY}/date={YYYYMMDD}/...
uk-radar/checksums/sha256/...
```

The object-store setup and operations notes are in:

- [jasmin_object_store_setup.md](jasmin_object_store_setup.md)
- [ncas_radar_object_store_release.md](ncas_radar_object_store_release.md)

## Web Deployment

The planned web implementation target is:

```text
ncas-rsg-cloud-workstation-ssh
130.246.214.121
```

See [../deploy/README.md](../deploy/README.md) and [uk_wsr_visualizer_deployment.md](uk_wsr_visualizer_deployment.md) for deployment details.
