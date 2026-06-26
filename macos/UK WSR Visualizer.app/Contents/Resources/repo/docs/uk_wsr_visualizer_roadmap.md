# UK WSR Visualizer Roadmap

UK WSR Visualizer is intended to become a community tool for discovering, plotting, comparing, and exporting UK weather radar HDF5 data. The app is macOS-first for beta testing and uses the JASMIN Object Store for public data access.

## Current Scope

- macOS app with its own native window.
- Public catalog discovery from JASMIN Object Store.
- On-demand local caching of selected radar source files.
- Georeferenced PPI plotting over map tiles.
- Variable, time, elevation, palette, opacity, range, azimuth, and value controls.
- Four-panel comparison with linked time and per-panel item, variable, and elevation controls.
- Click and hover readout for plotted value, range, azimuth, latitude, longitude, and elevation.
- Session and project-state support.
- CLI tools for catalog, preview, tile, export, animation, math, freshness, and object-store operations.

## Data Source

Original source observations are Met Office NIMROD single-site UK radar files held by CEDA and mounted on JASMIN at:

```text
/badc/ukmo-nimrod/data/single-site
/badc/ukmo-nimrod/data/single-site/storage_by_year
```

The Avocet/JASMIN processing pipeline converts these into daily ODIM-like aggregate HDF5 files at:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

Approved data are mirrored to:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

## Next Engineering Targets

1. Improve catalog discovery for all available radars and years as the object-store backfill grows.
2. Finish robust per-volume raw-source publication for faster app interaction where redistribution is approved.
3. Add clearer progress and cache status for long source-file downloads.
4. Improve four-panel comparison presets for common workflows: four elevations, four variables, four times, and four radars.
5. Add export controls to the UI for the formats already supported by the CLI/API.
6. Add stronger automated browser tests for search, plot, compare, identify, and cache-clear workflows.
7. Build a repeatable beta release process with a zipped app bundle, checksum, GitHub prerelease notes, and known-issues list.
8. Keep object-store publication dry-run-first and checksum verified before updating public manifests.

## Object Store Layout

```text
uk-radar/catalog/inventory/catalog.json
uk-radar/catalog/stac/...
uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5
uk-radar/raw-volume/radar={radar}/year={YYYY}/date={YYYYMMDD}/...
uk-radar/previews/...
uk-radar/tiles/...
uk-radar/checksums/sha256/...
uk-radar/manifests/latest.json
```

## Release Gate

Before advertising a wider community beta:

- Confirm public redistribution approval for each published data product.
- Confirm public catalog inventory contains no private GWS, BADC, scratch, or home paths.
- Confirm object-store CORS works for the app origin and direct HTTPS downloads.
- Confirm representative radar/day plots work from a clean app cache.
- Confirm the app can recover cleanly from missing dates, unavailable times, unavailable elevations, and interrupted downloads.
