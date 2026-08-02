<p align="center">
  <img src="../docs/_static/uk-wsr-visualizer-logo.png" alt="UK WSR Visualizer radar logo" width="130">
</p>

# UK WSR Visualizer macOS App

The supported macOS app is built from the Xcode project in this repository.
Build it with:

```bash
macos/build-xcode-macos.sh
```

The distributable archive is written to:

```text
build/xcode-macos/UK WSR Visualizer macOS Xcode Beta.zip
```

Extract the archive, move **UK WSR Visualizer.app** to `/Applications`, and
double-click it. The app opens a native macOS window, shows the radar logo while
the local viewer starts, then loads the interface from `127.0.0.1:8765`. It
does not open the default browser.

By default, the app connects to the public JASMIN Object Store catalog:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json
```

## Original Data Source

The radar observations originate from the Met Office NIMROD single-site UK radar archive held by CEDA. On JASMIN, those original files are available under:

```text
/badc/ukmo-nimrod/data/single-site
/badc/ukmo-nimrod/data/single-site/storage_by_year
```

The Avocet/JASMIN processing pipeline uses daily aggregate HDF5 working
products on GWS:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

The public app does not fetch those daily aggregates. Checked scans are
published as per-volume ODIM PVOL HDF5 objects with lazy root, radar-year, and
day catalogues under `ukmo-nimrod/pvol` and `ukmo-nimrod/catalog/pvol` in the
JASMIN Object Store.

## Runtime Files

Runtime files are kept outside the repository:

```text
~/Library/Application Support/UK WSR Visualizer/
```

The launcher creates a local Python virtual environment on first run and installs the bundled app code into it. During that first setup, the native window remains on the logo splash until the local server is ready.

Logs are written to:

```text
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
```

## Source File Cache

The app does not require a special public science dataset. It starts from the public catalog, then downloads the selected source object into a temporary working cache when plotting needs the file:

```text
~/Library/Application Support/UK WSR Visualizer/data/remote-aggregate-cache/
```

When the public catalogue provides a field-index sidecar, the local API uses it to enable pulse, time, variable, and elevation controls without downloading a representative HDF5 file first. If the sidecar is missing, the app falls back to scanning the selected source file locally. Cached source files are local copies of the original published objects, not app-specific derivatives.

The raw cache is disposable:

- Default time-to-live: disabled.
- Default max size: 25 GB, evicted least-recently-used.
- Click **Clear Raw Cache** in the app to remove cached radar source files immediately.
- The app will re-fetch a source object from the object store if it is needed again after cleanup or LRU eviction.

Previews, exports, tiles, and sessions are still written separately under the app data directory because they are user-generated products.

## Basic Workflow

1. Enter a date or date range.
2. Select an available radar, source item, variable, time, and elevation.
3. Inspect the georeferenced single-site PPI with mouse wheel zoom, drag pan, and click readout.
4. Use **4 Panel** for linked-time comparisons across source items, variables, and elevations.
5. Use **Export & Provenance** to download a current-view screenshot, a polar PPI image/animation, a georeferenced map product, or metadata JSON with provenance.

When reporting bugs, include the radar, date, time, variable, elevation, and the log file path shown above.

## Environment Overrides

```bash
UK_WSR_VISUALIZER_MAC_PORT=8766
UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
UK_WSR_VISUALIZER_REMOTE_CATALOG_URL=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json
UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS=0
UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES=26843545600
```
