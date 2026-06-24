# UK WSR Visualizer

UK radar Weather and Climate Toolkit-style app and CLI for UK WSR Visualizer radar HDF5 files.

The implementation is UK-radar-specific. The current Mac app connects to the public JASMIN Object Store catalog, downloads the selected raw aggregate HDF5 object into a disposable local cache, and renders georeferenced PPI views over maps with WCT-style field, time, palette, opacity, range, azimuth, value, and identify controls. The CLI also contains catalog, object-store, validation, preview, export, and deployment operations for building out the community service.

For collaborators, start with [docs/install_and_use.md](docs/install_and_use.md).

## Quick Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export]"
uk-wsr-visualizer catalog build --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site --output data/catalog.json
uk-wsr-visualizer api --catalog data/catalog.json --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

For the packaged local app, open:

```text
macos/UK WSR Visualizer.app
```

## Implemented Commands

```bash
uk-wsr-visualizer catalog build
uk-wsr-visualizer catalog stac
uk-wsr-visualizer preview build
uk-wsr-visualizer tile build|batch
uk-wsr-visualizer animation build
uk-wsr-visualizer export
uk-wsr-visualizer math
uk-wsr-visualizer object-store plan|sync|verify|publish|reconcile|release-candidate|cors-template
uk-wsr-visualizer freshness check
uk-wsr-visualizer session list|get|save|export|import
uk-wsr-visualizer deployment preflight
uk-wsr-visualizer validate wct|wct-suite
uk-wsr-visualizer api
```

Export formats are `native_hdf5`, `metadata_json`, `png`, `kmz`, `field_csv`, `geotiff`, `cf_netcdf`, `geojson`, `shapefile`, and `wct_batch_config`.

Completed exports include an `artifact-manifest.json` and can be downloaded through `GET /api/export/{job_id}/download`. Multi-file Shapefile outputs are bundled as ZIP downloads.

`uk-wsr-visualizer catalog stac` writes a STAC root catalog, `uk-wsr-aggregate-h5` collection, and per-radar-day item JSON.

WCT 4.9.1 parity validation is documented in [docs/wct_parity_validation.md](docs/wct_parity_validation.md).

The full UK radar WCT-replica roadmap is tracked in [docs/uk_radar_wct_replica_roadmap.md](docs/uk_radar_wct_replica_roadmap.md).

Preview and export commands support WCT-style filters: `--min-range-km`, `--max-range-km`, `--min-azimuth-deg`, `--max-azimuth-deg`, `--min-value`, `--max-value`, and `--cappi-height-m`.

`--cappi-height-m` selects the closest available sweep/dataset by ODIM height metadata or a beam-height estimate when a dataset is not explicitly pinned.

Use `--palette custom --palette-stops "0:#000000,0.5:#28b450,1:#ffffff"` to create WCT-style editable color ramps for previews, tiles, animation frames, PNG/KMZ exports, and math PNG products.

`uk-wsr-visualizer math` creates derived products between two selected fields or times using difference, sum, product, ratio, mean, min, or max operations.

`uk-wsr-visualizer animation build` exports timeline preview frames and a manifest as a ZIP package.

`uk-wsr-visualizer tile build` creates browser-friendly tile pyramids and tile manifests for selected fields; production workers should precompute these for public object-store reads.

The browser contour overlay uses `/api/contours/...`, which shares the same gridded contour path as GeoJSON and Shapefile export.

Viewer state can be saved as server-side sessions or downloaded as portable `uk-wsr-visualizer-project` JSON files. Use `uk-wsr-visualizer session export SESSION_ID --output project.json` and `uk-wsr-visualizer session import --project-json project.json` for operational handoff.

Object Store setup is documented in [docs/jasmin_object_store_setup.md](docs/jasmin_object_store_setup.md). Live object-store operations require:

```bash
pip install -e ".[object-store]"
```

## Deployment Target

The planned web host is `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121`. See [docs/uk_wsr_visualizer_deployment.md](docs/uk_wsr_visualizer_deployment.md).
