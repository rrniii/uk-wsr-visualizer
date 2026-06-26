<p align="center">
  <img src="docs/assets/uk-wsr-visualizer-logo.png" alt="UK WSR Visualizer radar logo" width="150">
</p>

# UK WSR Visualizer

UK WSR Visualizer is a desktop app and Python toolkit for exploring UK weather radar HDF5 data. It connects to a public JASMIN Object Store catalog, downloads only the selected radar source file into a disposable local cache, and plots georeferenced PPI radar sweeps over maps.

For collaborator setup, start with [docs/install_and_use.md](docs/install_and_use.md).

## Data Provenance

The original radar observations are Met Office NIMROD single-site UK radar files held by CEDA and available on JASMIN under:

```text
/badc/ukmo-nimrod/data/single-site
/badc/ukmo-nimrod/data/single-site/storage_by_year
```

The Avocet/JASMIN processing pipeline converts those original NIMROD single-site files into daily ODIM-like UK WSR aggregate HDF5 files on GWS:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

Approved aggregate HDF5 files and catalog metadata are then mirrored to the JASMIN Object Store for app access:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

The app does not require a special app-specific science dataset. It reads the public catalog, downloads the selected aggregate or raw-volume object when needed, scans its HDF5 metadata locally, and removes cached source files according to the cache settings or when **Clear Raw Cache** is pressed.

## macOS App

Open the packaged local app:

```text
macos/UK WSR Visualizer.app
```

On first launch the app:

1. Creates a local Python virtual environment under `~/Library/Application Support/UK WSR Visualizer/`.
2. Installs the bundled Python runtime dependencies.
3. Starts a local API server on `127.0.0.1:8765`.
4. Opens the viewer in its own native macOS window.

The startup log is:

```text
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
```

The disposable source-file cache is:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

## Windows App

The Windows beta is built as a portable zip:

```text
build/windows-beta/UK WSR Visualizer Windows Beta.zip
```

After extraction, double-click `UK WSR Visualizer.exe`. The app opens a native WebView2 window, starts the bundled local Python server, and stores runtime files under:

```text
%LOCALAPPDATA%\UK WSR Visualizer\
```

Windows build and beta-user notes are in [docs/windows_install_and_use.md](docs/windows_install_and_use.md) and [windows/README.md](windows/README.md).

## Basic Use

1. Open `macos/UK WSR Visualizer.app` or the extracted Windows `UK WSR Visualizer.exe`.
2. Choose a date range, radar, and pulse in **Data Selection**.
3. Click **Search Catalog**.
4. Select an item in **Radar Controls**.
5. Choose the variable, time, and elevation.
6. Pan and zoom the map with the mouse.
7. Click the radar image to read the plotted value, range, azimuth, latitude, longitude, and elevation.
8. Use **4 Panel** to compare items, variables, and elevations with a linked time control.
9. Use **Clear Raw Cache** to delete locally cached source files.

## Developer Install

Use Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store]"
```

Build a local catalog from GWS aggregate files:

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output data/catalog.json
```

Run the local API and static UI:

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

## CLI Overview

```bash
uk-wsr-visualizer catalog build
uk-wsr-visualizer catalog stac
uk-wsr-visualizer preview build
uk-wsr-visualizer tile build|batch
uk-wsr-visualizer animation build
uk-wsr-visualizer export
uk-wsr-visualizer math
uk-wsr-visualizer citation
uk-wsr-visualizer object-store plan|sync|verify|publish|reconcile|release-candidate|cors-template
uk-wsr-visualizer freshness check
uk-wsr-visualizer session list|get|save|export|import
uk-wsr-visualizer deployment preflight
uk-wsr-visualizer api
```

Export formats include `native_hdf5`, `metadata_json`, `png`, `kmz`, `field_csv`, `geotiff`, `cf_netcdf`, `geojson`, and `shapefile`.

## Citation

If you use UK WSR Visualizer in research, cite the archived software release and the accompanying Weather article when available. Also cite the underlying UK WSR source-data record and acknowledge JASMIN where JASMIN storage or compute is used.

```bash
uk-wsr-visualizer citation
uk-wsr-visualizer citation --json
```

The citation command and export manifests currently contain DOI placeholders until the first Zenodo software release and the Weather article DOI are available. Do not replace the source-data citation with a generic radar-data citation; use the formal citation agreed with the data owner and archive.

## Object Store

Object Store setup is documented in [docs/jasmin_object_store_setup.md](docs/jasmin_object_store_setup.md). Live object-store operations require:

```bash
pip install -e ".[object-store]"
```

Current public catalog:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

Current public object layout:

```text
uk-radar/catalog/inventory/catalog.json
uk-radar/catalog/stac/...
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
uk-radar/raw-volume/radar={radar}/year={YYYY}/date={YYYYMMDD}/...
uk-radar/checksums/sha256/...
```

## Web Deployment

The planned web host is `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121`. See [docs/uk_wsr_visualizer_deployment.md](docs/uk_wsr_visualizer_deployment.md).
