# Avocet Radar Toolkit macOS App

This folder contains a lightweight macOS app bundle:

```text
macos/Avocet Radar Toolkit.app
```

Double-clicking the app starts the local FastAPI/static viewer on `127.0.0.1:8765` and opens it in the default browser. By default it connects to the public JASMIN Object Store catalog:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public/uk-radar/catalog/inventory/catalog.json
```

Runtime files are kept outside the repository:

```text
~/Library/Application Support/Avocet Radar Toolkit/
```

The launcher creates a local Python virtual environment on first run and installs this checkout into it. Logs are written to:

```text
~/Library/Application Support/Avocet Radar Toolkit/avocet-radar-toolkit.log
```

Environment overrides:

```bash
AVOCET_WCT_MAC_PORT=8766
AVOCET_WCT_OBJECT_STORE_EXTERNAL_BASE=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public
AVOCET_WCT_REMOTE_CATALOG_URL=https://ncas-radar-o.s3-ext.jc.rl.ac.uk/avocet-uk-radar-public/uk-radar/catalog/inventory/catalog.json
AVOCET_WCT_REMOTE_CACHE_TTL_SECONDS=3600
AVOCET_WCT_REMOTE_CACHE_MAX_BYTES=26843545600
```

The app does not require a special public dataset for its field-level controls. It starts from the public catalog, then uses the selected raw aggregate HDF5 object when you click **Load Raw Aggregate**. The local API downloads that exact source aggregate into a temporary working cache:

```text
~/Library/Application Support/Avocet Radar Toolkit/data/remote-aggregate-cache/
```

After the raw aggregate is cached, the app scans the HDF5 metadata locally and enables the normal pulse/time/quantity preview and export controls. The cached file is a local copy of the original aggregate object, not an app-specific derivative.

The raw cache is disposable:

- Default TTL: 1 hour.
- Default max size: 25 GB.
- Click **Clear Raw Cache** in the app to remove cached raw aggregate files immediately.
- The app will re-fetch an aggregate from the object store if it is needed again after cleanup.

Previews, exports, tiles, and sessions are still written separately under the app data directory because they are user-generated products.
