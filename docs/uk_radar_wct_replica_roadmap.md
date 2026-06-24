# UK Radar WCT Replica Roadmap

This project is not intended to stop at a minimal viewer. The target is a UK-radar-specific web and CLI replacement for the WCT workflows that matter for UK WSR aggregate HDF5 data, with public community delivery through the JASMIN Object Store.

## Implemented Foundation

- Catalog discovery from UK WSR aggregate HDF5 metadata without reading full arrays.
- STAC/catalog publication, private-path redaction, checksum manifests, and object-store status/manifest generation.
- Browser data selection by radar, date, pulse, time, quantity, and dataset.
- Preview rendering with palette, opacity, range, azimuth, value, and CAPPI-style nearest-sweep controls.
- Timeline stepping, animation ZIP export, four-panel comparison, snapshot capture, contours, click identify/readout, and object URL display.
- Export jobs for native HDF5, metadata JSON, PNG, KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and WCT batch config.
- Derived math products across selected times/fields.
- Preview-derived tile pyramids for browser/object-store delivery.
- Server sessions plus portable `uk-wsr-visualizer-project` files for WCT-style project handoff.
- Deployment assets for `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121` using FastAPI, Nginx, systemd timers, and dry-run-first object-store publishing.
- A lightweight macOS app bundle at `macos/UK WSR Visualizer.app` that launches the local FastAPI/static viewer and connects to the public JASMIN Object Store catalog.

## Current Mac-First Scope

The near-term app does not require a Linux WCT runtime. It runs locally on macOS and connects remotely to:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

The default remote catalog is:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

This supports public catalog browsing, object URL discovery, STAC/public metadata inspection, and sessions. For field-level HDF5 rendering, the Mac app uses a WCT-style disposable working cache: when the user clicks **Load Raw Aggregate**, it downloads the selected raw aggregate HDF5 object from the public object store, scans that file locally, enables pulse/time/quantity controls, and prunes the raw cache by TTL/size or when the user clicks **Clear Raw Cache**. This avoids a special app-specific public dataset while still avoiding browser-side parsing of multi-GB HDF5 objects.

The daily aggregate is the right archival/public source-of-truth, but it is not the ideal interactive unit for a WCT-like desktop experience. WCT feels responsive because it opens smaller product or volume files and only reads the selected field/sweep. The app should therefore add a second raw-source mode for approved per-volume files, including BioRad/ODIM-compatible files from the existing JASMIN BioDAR workflow if redistribution and object-store access are allowed. In that mode the public catalog should index each volume/time/pulse/elevation object directly, the Mac app should cache only the selected object, and the aggregate should remain the provenance and full-day archive path.

## Replica Parity Work Still Required

These items are the next engineering targets before calling the app a full WCT replacement for UK radar:

1. Run the WCT 4.9.1 parity suite with `uk-wsr-visualizer validate wct-suite --execute-wct --require-comparison` against representative real aggregate files for GeoTIFF, KMZ, Shapefile, and CF NetCDF. This is explicitly a later parity task, not a blocker for the current macOS object-store app.
2. Compare gridded exports numerically and visually against WCT output, then record accepted tolerances by radar/product.
3. Add a per-volume raw-source adapter for BioRad/ODIM-compatible files, with catalog entries keyed by radar/date/time/pulse/elevation/quantity and object-store URLs under a raw-volume prefix.
4. Replace preview-derived map tiles with geospatially correct Web Mercator or radar-native map tiles where appropriate.
5. Implement true multi-sweep CAPPI interpolation where volume geometry supports it; keep current nearest-sweep CAPPI as a fallback.
6. Add WMS/XYZ overlay support for external layers, including object-store-hosted tile manifests.
7. Add saved layer stacks and project/session version migration for long-lived community workflows.
8. Extend math operations with time-window aggregations, thresholds, masks, and field algebra expressions.
9. Add operational job queueing for large exports instead of synchronous API execution.
10. Add admin-only local/GWS browsing and public-safe source browsing as separate UI modes.
11. Build a public dataset landing page backed by STAC, checksums, licence/terms text, and freshness status.

## Object Store Migration Plan

The migration should be staged, not a one-shot copy.

1. Confirm release policy: public UK WSR aggregate HDF5 is allowed; original NIMROD archives remain private unless explicitly approved.
2. Create staging and public buckets in the JASMIN Object Store tenancy.
3. Run a small dry-run publication plan for one radar/day and inspect every object key.
4. Run live sync to staging for one radar/day, verify checksum and object metadata, then publish the public manifest.
5. Apply CORS to the public bucket and test browser reads from the deployed web origin.
6. Backfill one radar/year, measuring upload throughput, multipart behavior, public read latency, and total bucket size.
7. Publish yearly/radar checksum manifests and STAC assets.
8. If per-volume BioRad/ODIM-compatible files are approved for publication, add them as raw source objects, not app-specific derivatives, for example `uk-radar/raw-volume/radar={radar}/year={YYYY}/date={YYYYMMDD}/...`.
9. Enable scheduled catalog, preview/tile, object-store sync, verify, publish, reconcile, and freshness timers.
10. Only then scale to all approved radar/day aggregate HDF5 objects and raw-volume objects.

## User Decisions Needed

- JASMIN Object Store tenancy name and manager/deputy contact.
- Whether bucket names remain `uk-wsr-visualizer-staging` and `uk-wsr-visualizer-public`.
- S3 token owner, credential location, and rotation process.
- Public web origin to lock into CORS after smoke testing.
- Written approval for public redistribution of UK WSR aggregate HDF5.
- Dataset licence/terms, citation text, and support contact.
- First radar/day and first radar/year to use for live migration rehearsal.
