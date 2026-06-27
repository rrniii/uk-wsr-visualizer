# UK WSR Visualizer

UK WSR Visualizer is a quick-look web app and command-line toolkit for discovering, visualising, exporting, and citing UK weather surveillance radar (WSR) aggregate HDF5 data.

The project is built around a simple community need: make it quick and easy to look at UK WSR data without requiring every user to first build a bespoke radar-processing stack. The current local/web app connects to an approved JASMIN Object Store catalogue, loads only the selected source object into a bounded local cache, and renders georeferenced plan-position-indicator (PPI) views over maps with field, time, palette, opacity, range, azimuth, value, and identify controls.

Start with the [documentation landing page](docs/index.md) or the [install and use guide](docs/install_and_use.md).

## Documentation

This repository includes a Sphinx documentation section with a PyData-style layout: landing page, user guide, example gallery, API reference, developer guide, and release notes.

Build the documentation locally with:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[docs]"
sphinx-build -b html docs docs/_build/html
python -m http.server --directory docs/_build/html 8080
```

Then open `http://127.0.0.1:8080`.

The `.github/workflows/docs.yml` workflow builds the same Sphinx site and deploys it through GitHub Pages when Pages is configured to use GitHub Actions.

## Scope

The current scope is deliberately practical:

- catalogue-driven discovery by radar, date, scan category, time, and field;
- rapid map-based PPI inspection;
- bounded local caching of selected source objects;
- CLI/API support for catalogue, preview, export, object-store, freshness, session, and deployment workflows;
- provenance and citation metadata in export manifests.

The tool is not an official data service and does not replace the formal citation or access conditions for the underlying UK WSR data.

## Design context

Existing radar viewers and scientific Python tools show the value of practical interfaces for opening environmental data, inspecting fields visually, and moving useful outputs into later analysis.

UK WSR Visualizer is an independent implementation for UK WSR aggregate HDF5 archives and JASMIN Object Store workflows. It is not affiliated with or endorsed by external radar-viewer projects, data centres, or service providers unless that relationship is stated explicitly.

## Citation

If UK WSR Visualizer is used to produce a figure, export, derived object, case selection, or research result, cite four distinct credit layers:

1. the archived software release used in the analysis;
2. the accompanying Weather article once published;
3. the formal source-data record for the underlying UK WSR data;
4. JASMIN, where JASMIN storage or compute supported the workflow.

The repository includes [CITATION.cff](CITATION.cff) and [CITATION.md](CITATION.md). The DOI fields remain marked as pending until a versioned archive has been minted.

The citation helper can be run as:

```bash
uk-wsr-visualizer-citation
uk-wsr-visualizer-citation --json
```

Completed exports include an `artifact-manifest.json` with software, article, source-data, and JASMIN citation metadata.

## Quick Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export]"
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/uk-wsr/aggregate-h5/single-site \
  --output data/catalog.json
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
uk-wsr-visualizer catalog build-raw-volume
uk-wsr-visualizer catalog stac
uk-wsr-visualizer preview build|batch
uk-wsr-visualizer tile build|batch
uk-wsr-visualizer animation build
uk-wsr-visualizer export
uk-wsr-visualizer math
uk-wsr-visualizer object-store plan|sync|verify|publish|reconcile|release-candidate|cors-template|buckets|backfill-status
uk-wsr-visualizer freshness check
uk-wsr-visualizer session list|get|save|export|import
uk-wsr-visualizer deployment preflight
uk-wsr-visualizer api
uk-wsr-visualizer-citation
```

Export formats are `native_hdf5`, `metadata_json`, `png`, `kmz`, `field_csv`, `geotiff`, `cf_netcdf`, `geojson`, and `shapefile`. A legacy batch-configuration output remains available for internal validation workflows.

Completed exports include an `artifact-manifest.json` and can be downloaded through `GET /api/export/{job_id}/download`. Multi-file Shapefile outputs are bundled as ZIP downloads.

`uk-wsr-visualizer catalog stac` writes a STAC root catalog, `uk-wsr-aggregate-h5` collection, and per-radar-day item JSON.

Preview and export commands support filters: `--min-range-km`, `--max-range-km`, `--min-azimuth-deg`, `--max-azimuth-deg`, `--min-value`, `--max-value`, and `--cappi-height-m`.

Use `--palette custom --palette-stops "0:#000000,0.5:#28b450,1:#ffffff"` to create editable colour ramps for previews, tiles, animation frames, PNG/KMZ exports, and math PNG products.

`uk-wsr-visualizer math` creates derived products between two selected fields or times using difference, sum, product, ratio, mean, min, or max operations.

`uk-wsr-visualizer animation build` exports timeline preview frames and a manifest as a ZIP package.

`uk-wsr-visualizer tile build` creates browser-friendly tile pyramids and tile manifests for selected fields; production workers should precompute these for object-store reads.

Viewer state can be saved as server-side sessions or downloaded as portable `uk-wsr-visualizer-project` JSON files. Use `uk-wsr-visualizer session export SESSION_ID --output project.json` and `uk-wsr-visualizer session import --project-json project.json` for operational handoff.

Object Store setup is documented in [docs/jasmin_object_store_setup.md](docs/jasmin_object_store_setup.md). Live object-store operations require:

```bash
pip install -e ".[object-store]"
```

## Deployment Target

The planned web deployment is documented in [docs/uk_wsr_visualizer_deployment.md](docs/uk_wsr_visualizer_deployment.md). Confirm the stable public host name, access conditions, licence text, and source-data citation before advertising a community endpoint.
