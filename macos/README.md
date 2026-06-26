<p align="center">
  <img src="../docs/assets/uk-wsr-visualizer-logo.png" alt="UK WSR Visualizer radar logo" width="130">
</p>

# UK WSR Visualizer macOS App

This folder contains the local macOS app bundle:

```text
macos/UK WSR Visualizer.app
```

Double-clicking the app opens a native macOS window, shows the radar logo while the local viewer starts, then loads the interface from `127.0.0.1:8765`. It does not open the default browser.

By default, the app connects to the public JASMIN Object Store catalog:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

## Original Data Source

The radar observations originate from the Met Office NIMROD single-site UK radar archive held by CEDA. On JASMIN, those original files are available under:

```text
/badc/ukmo-nimrod/data/single-site
/badc/ukmo-nimrod/data/single-site/storage_by_year
```

The Avocet/JASMIN processing pipeline converts those original files into daily ODIM-like UK WSR aggregate HDF5 files on GWS:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

Approved aggregate HDF5 files, raw-volume objects, and catalog metadata are then mirrored to the JASMIN Object Store for this app.

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

After a source file is cached, the local API scans the HDF5 metadata and enables the available pulse, time, variable, and elevation controls. The cached file is a local copy of the original published object, not an app-specific derivative.

The raw cache is disposable:

- Default TTL: 1 hour.
- Default max size: 25 GB.
- Click **Clear Raw Cache** in the app to remove cached radar source files immediately.
- The app will re-fetch a source object from the object store if it is needed again after cleanup.

Previews, exports, tiles, and sessions are still written separately under the app data directory because they are user-generated products.

## Environment Overrides

```bash
UK_WSR_VISUALIZER_MAC_PORT=8766
UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
UK_WSR_VISUALIZER_REMOTE_CATALOG_URL=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS=3600
UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES=26843545600
```
