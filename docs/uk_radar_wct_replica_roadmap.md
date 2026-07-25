# Development Roadmap

UK WSR Visualizer is a quick-look web app and CLI that make UK weather
surveillance radar aggregate HDF5 data easier to discover, inspect, export, and
cite.

## Design Position

The roadmap prioritises user needs, citation, provenance, reliable first
inspection, and clear publication workflows for approved UK WSR source objects.
It is not a technical parity checklist for another radar viewer.

## Implemented Foundation

- Catalogue discovery from UK WSR aggregate HDF5 metadata without reading full arrays.
- STAC/catalog publication, private-path redaction, checksum manifests, and object-store status/manifest generation.
- Browser data selection by radar, date, scan category, time, field, and dataset.
- Preview rendering with palette, opacity, range, azimuth, value, and nearest-sweep height controls.
- Timeline stepping, animation ZIP export, four-panel comparison, snapshot capture, contours, click identify/readout, and object URL display.
- Export jobs for native HDF5, metadata JSON, PNG, KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and batch-config workflows.
- Derived math products across selected times/fields.
- Preview-derived tile pyramids for browser/object-store delivery.
- Server sessions plus portable `uk-wsr-visualizer-project` files for project handoff.
- Xcode-built macOS, WebView2 Windows, and Qt Linux packages that launch the same local FastAPI/static viewer and connect to the configured JASMIN Object Store catalogue.
- Citation helper and export-manifest fields for software, article, source-data, and JASMIN attribution.

## Current App Scope

The near-term app runs locally on macOS and connects remotely to a configured catalogue, for example:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json
```

This supports catalogue browsing, object URL discovery, STAC/public metadata inspection, and sessions. For field-level HDF5 rendering, the app downloads only the selected source object into a disposable local cache, scans that file locally, enables pulse/time/field controls, and prunes the cache by TTL/size or when the user clicks **Clear Raw Cache**.

The daily aggregate remains the archive source of truth. If approved per-volume files become available, they should be indexed as source objects with clear provenance, licence, and citation metadata rather than as app-specific derivatives.

## User-Need Roadmap

1. Finalise the formal UK WSR aggregate HDF5 source-data citation, licence, access terms, and support contact.
2. Mint a Zenodo DOI from the first tagged software release and update README, CITATION files, app metadata, CLI output, and export manifests.
3. Add or expose an app-level citation panel using the same structured citation payload as the CLI and export manifest.
4. Keep the default UI limited to tested controls; hide unfinished controls before community screenshots or release.
5. Add representative smoke tests for catalogue search, selected source-object load, map render, time stepping, click identify, cache clear, and manifest generation.
6. Add a source-data citation registry that can be updated without editing multiple files by hand.
7. Replace preview-derived map tiles with geospatially correct Web Mercator or radar-native map tiles where appropriate.
8. Improve saved project/session versioning for long-lived community workflows.
9. Extend math operations with time-window aggregations, thresholds, masks, and field algebra expressions once the quick-look workflow is stable.
10. Add operational job queueing for large exports instead of synchronous API execution.
11. Build a public or community dataset landing page backed by STAC, checksums, licence/access text, citation text, and freshness status.

## Object Store Release Plan

The release should be staged, not a one-shot copy.

1. Confirm release policy for approved UK WSR aggregate HDF5 source objects.
2. Confirm that original restricted archives remain excluded unless explicitly approved.
3. Create or confirm staging and public/community buckets in the JASMIN Object Store tenancy.
4. Run a small dry-run publication plan for one radar/day and inspect every object key.
5. Run live sync to staging for one radar/day, verify checksum and object metadata, then publish the manifest.
6. Apply CORS to the public/community bucket and test browser reads from the deployed web origin.
7. Backfill one radar/year, measuring upload throughput, multipart behaviour, public read latency, and total bucket size.
8. Publish yearly/radar checksum manifests and STAC assets.
9. Enable scheduled catalog, preview/tile, object-store sync, verify, publish, reconcile, and freshness timers.
10. Only then scale to all approved radar/day source objects.

## Decisions Needed

- JASMIN Object Store tenancy name and manager/deputy contact.
- Whether bucket names remain `uk-wsr-visualizer-staging` and `uk-wsr-visualizer-public`.
- S3 token owner, credential location, and rotation process.
- Final public or community web origin to lock into CORS after smoke testing.
- Written approval for access to the approved UK WSR aggregate HDF5 source objects.
- Dataset licence/terms, citation text, and support contact.
- First radar/day and first radar/year to use for live migration rehearsal.
