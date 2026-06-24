# Avocet Radar Toolkit Implementation Notes

This repository now contains a first implementation scaffold for the UK Radar WCT-style web toolkit.

## Components

- `src/avocet_radar_toolkit/catalog.py`: scans Avocet aggregate HDF5 metadata and writes `catalog.json`.
- `src/avocet_radar_toolkit/preview.py`: generates browser-friendly PNG previews from selected ODIM quantity groups.
- `src/avocet_radar_toolkit/tiles.py`: generates preview-derived XYZ-style tile pyramids and tile manifests for browser/object-store delivery.
- `src/avocet_radar_toolkit/animation.py`: packages timeline preview frames and metadata into animation ZIP products.
- `src/avocet_radar_toolkit/geospatial.py`: reads ODIM-like radar field metadata and converts polar radar bins to a radar-centred azimuthal-equidistant Cartesian grid.
- `src/avocet_radar_toolkit/export.py`: records export jobs and supports native HDF5, metadata JSON, PNG preview, georeferenced KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON contours, Shapefile contours, WCT-style batch config XML exports, artifact manifests, and safe download bundles.
- `src/avocet_radar_toolkit/math_ops.py`: creates WCT-style derived products from two radar fields using difference, sum, product, ratio, mean, min, or max operations.
- `src/avocet_radar_toolkit/object_store_*.py`: builds checksummed publication plans and dry-run-first JASMIN Object Store sync, verify, publish, reconcile, and CORS workflows.
- `src/avocet_radar_toolkit/freshness.py`: checks catalog age, data latency, object-store manifest verification, public inventory private-path redaction, and required WCT validation report parity status.
- `src/avocet_radar_toolkit/wct_parity.py`: generates WCT 4.9.1 batch configs, runs Avocet exports, optionally runs WCT batch export, and writes parity validation reports with strict comparison metrics for GeoTIFF, CF NetCDF, Shapefile, and KMZ.
- `src/avocet_radar_toolkit/api/app.py`: FastAPI app serving API endpoints and the static web UI.
- `src/avocet_radar_toolkit/session.py`: stores and loads WCT-style viewer sessions as JSON and imports/exports portable `avocet-wct-project` files.
- `src/avocet_radar_toolkit/static/`: WCT-style browser UI with catalog search, radar controls, range/azimuth/value filters, palette/opacity/basemap controls, four-panel view, animation, tile-product generation, data-derived contour overlays, snapshots, click-to-identify readout, session/project state, and export actions.
- `src/avocet_radar_toolkit/cli.py`: `avocet-wct` command-line entrypoint.

## Current Limits

- GeoTIFF and CF NetCDF export use a nearest-neighbour polar-to-Cartesian grid in a radar-centred azimuthal-equidistant CRS. This is a production export path, but it still needs validation against WCT output on real aggregate files before claiming numerical parity.
- GeoJSON, Shapefile, and browser contour overlays are generated from the same gridded field values. Browser contours are served through `/api/contours/...`.
- Browser readout maps image coordinates back to source row/column and calls the identify API for raw values. When ODIM geospatial metadata are available, the readout also reports range, azimuth, latitude, and longitude.
- Range, azimuth, value, and `cappi_height_m` filters are applied to preview generation and geospatial export paths. Azimuth wraparound such as 300 to 60 degrees is supported.
- CAPPI-style height selection chooses the nearest available sweep/dataset by ODIM `height` metadata or a beam-height estimate when the user has not explicitly selected a dataset. It is not yet full multi-sweep volumetric CAPPI interpolation.
- Math products support PNG, CSV, NumPy array, and metadata JSON outputs. They currently require same-shape operands from the same aggregate file.
- Animation export creates a ZIP containing PNG frames plus `manifest.json`; it reuses the same palette and filter controls as the viewer.
- Export jobs write `artifact-manifest.json`; multi-file Shapefile exports download as ZIP bundles through `/api/export/{job_id}/download`.
- Custom color tables use normalized stops such as `0:#000000,0.5:#28b450,1:#ffffff` and are supported by previews, tiles, animation frames, PNG/KMZ exports, and math PNG products.
- Tile generation creates preview-derived tile pyramids plus `tile-manifest.json`. These are not full Web Mercator radar reprojections yet; they are browser delivery artifacts for the selected radar field and include the radar geographic bbox when available.
- Georeferenced exports require ODIM `where` latitude/longitude attrs or equivalent radar registry coordinates. Missing coordinates fail the export rather than inventing a location.
- Session persistence is implemented as JSON files under the configured session directory. Portable project files use the `avocet-wct-project` JSON envelope and can be downloaded from the browser or moved between deployments with `avocet-wct session export` and `avocet-wct session import`.
- Browser previews and tiles can be generated on demand through the API; production should precompute them on JASMIN workers.
- JASMIN Object Store live sync requires configured S3 credentials and explicit `--execute`; dry-run planning works without credentials. Public catalog inventory is generated with private local paths redacted. Generated exports, animations, and math products are included in publication plans only when `publish_exports = true`.
- Public STAC items use object-store URLs for aggregate HDF5 and include links to SHA256 checksum manifests, preview prefixes, and tile prefixes.
- WCT parity validation is implemented as a repeatable harness. Live WCT execution still requires representative WCT-compatible input files and should be recorded with `--require-comparison` before claiming numerical parity.
- Public release readiness can be checked with `avocet-wct freshness check --require-object-store --require-wct-validation`, `/api/freshness?require_object_store=true&require_wct_validation=true`, or the full `avocet-wct object-store release-candidate` summary workflow.
