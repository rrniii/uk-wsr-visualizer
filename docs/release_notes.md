# Release Notes

## 0.1.0

Initial implementation of the UK WSR Visualizer documentation site and toolkit foundation.

### Documentation

- Added a Sphinx documentation section using PyData Sphinx Theme.
- Added a landing page with user guide, citation and attribution, example gallery, API reference, developer guide, and release notes sections.
- Added documentation build requirements and a `docs` optional dependency extra.
- Added a GitHub Pages workflow for publishing the built documentation.
- Added a release checklist for source-data attribution, Zenodo DOI minting, and Weather article preparation.

### Citation and release metadata

- Added BSD-3-Clause licence text.
- Added `CITATION.cff`, `CITATION.md`, and `.zenodo.json` templates.
- Added `uk-wsr-visualizer-citation` for human-readable and JSON citation output.
- Added a source-data citation registry template in `configs/data_citations.toml`.
- Added software, article, source-data, and JASMIN citation metadata to export manifests.

### Toolkit scope

The project currently includes catalogue, preview, export, tile, animation, derived math, session, STAC, object-store, freshness, deployment preflight, FastAPI, static viewer, and macOS launcher components. The public framing is quick-look access, visualisation, export, and citation for UK WSR aggregate HDF5 source objects.
