# UK WSR Visualizer Implementation Notes

This repository contains the macOS app, local API, CLI, catalog tools, and object-store publication tools for UK weather radar HDF5 data.

## Components

- `src/uk_wsr_visualizer/catalog.py`: scans UK WSR aggregate HDF5 metadata and writes `catalog.json`.
- `src/uk_wsr_visualizer/preview.py`: generates PNG previews from selected ODIM quantity groups.
- `src/uk_wsr_visualizer/tiles.py`: generates preview-derived tile pyramids and tile manifests for browser/object-store delivery.
- `src/uk_wsr_visualizer/animation.py`: packages timeline preview frames and metadata into animation ZIP products.
- `src/uk_wsr_visualizer/geospatial.py`: reads ODIM-like radar field metadata and converts polar radar bins to a radar-centred azimuthal-equidistant Cartesian grid.
- `src/uk_wsr_visualizer/export.py`: records export jobs and supports native HDF5, metadata JSON, PNG preview, georeferenced KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON contours, Shapefile contours, artifact manifests, and safe download bundles.
- `src/uk_wsr_visualizer/math_ops.py`: creates derived products from two radar fields using difference, sum, product, ratio, mean, min, or max operations.
- `src/uk_wsr_visualizer/object_store_*.py`: builds checksummed publication plans and dry-run-first JASMIN Object Store sync, verify, publish, reconcile, and CORS workflows.
- `src/uk_wsr_visualizer/freshness.py`: checks catalog age, data latency, object-store manifest verification, and public inventory private-path redaction.
- `src/uk_wsr_visualizer/api/app.py`: FastAPI app serving API endpoints and the static UI.
- `src/uk_wsr_visualizer/session.py`: stores and loads viewer sessions as JSON and imports/exports portable `uk-wsr-visualizer-project` files.
- `src/uk_wsr_visualizer/static/`: browser UI used inside the macOS app window, including catalog search, radar controls, range/azimuth/value filters, palette/opacity/basemap controls, four-panel comparison, animation, click-to-identify readout, session/project state, and export actions.
- `src/uk_wsr_visualizer/cli.py`: `uk-wsr-visualizer` command-line entrypoint.

## Data Flow

Original source data:

```text
/badc/ukmo-nimrod/data/single-site
/badc/ukmo-nimrod/data/single-site/storage_by_year
```

Processed aggregate HDF5 on JASMIN GWS:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

Public object-store mirror:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

The app uses the public catalog to locate aggregate or raw-volume objects. It downloads only the selected source object into a local cache, reads metadata and selected arrays locally, and clears cached source files by TTL/size or by user action.

## Current Limits

- GeoTIFF and CF NetCDF export use a nearest-neighbour polar-to-Cartesian grid in a radar-centred azimuthal-equidistant CRS.
- GeoJSON, Shapefile, and browser contour overlays are generated from the same gridded field values. Browser contours are served through `/api/contours/...`.
- Browser readout maps image coordinates back to source row/column and calls the identify API for raw values. When ODIM geospatial metadata are available, the readout also reports range, azimuth, latitude, longitude, variable, value, and elevation.
- Range, azimuth, value, and `cappi_height_m` filters are applied to preview generation and geospatial export paths. Azimuth wraparound such as 300 to 60 degrees is supported.
- Height selection chooses the nearest available sweep/dataset by ODIM `height` metadata or a beam-height estimate when the user has not explicitly selected a dataset. It is not full multi-sweep volumetric interpolation.
- Math products support PNG, CSV, NumPy array, and metadata JSON outputs. They currently require same-shape operands from the same aggregate file.
- Animation export creates a ZIP containing PNG frames plus `manifest.json`; it reuses the same palette and filter controls as the viewer.
- Export jobs write `artifact-manifest.json`; multi-file Shapefile exports download as ZIP bundles through `/api/export/{job_id}/download`.
- Custom color tables use normalized stops such as `0:#000000,0.5:#28b450,1:#ffffff` and are supported by previews, tiles, animation frames, PNG/KMZ exports, and math PNG products.
- Tile generation creates preview-derived tile pyramids plus `tile-manifest.json`. These are browser delivery artifacts for the selected radar field and include the radar geographic bbox when available.
- Georeferenced exports require ODIM `where` latitude/longitude attrs or equivalent radar registry coordinates. Missing coordinates fail the export rather than inventing a location.
- Session persistence is implemented as JSON files under the configured session directory. Portable project files use the `uk-wsr-visualizer-project` JSON envelope and can be downloaded from the browser or moved between deployments with `uk-wsr-visualizer session export` and `uk-wsr-visualizer session import`.
- Browser previews and tiles can be generated on demand through the API; production should precompute them on JASMIN workers.
- JASMIN Object Store live sync requires configured S3 credentials and explicit `--execute`; dry-run planning works without credentials. Public catalog inventory is generated with private local paths redacted. Generated exports, animations, and math products are included in publication plans only when `publish_exports = true`.
- Public STAC items use object-store URLs for aggregate HDF5 and include links to SHA256 checksum manifests, preview prefixes, and tile prefixes.
