# Release Notes

## 0.2.1

Unreleased beta polish for app-visible provenance and package guidance.

### Viewer

- Added an **Export & Provenance** panel for current-panel PNG quick-look and metadata JSON exports.
- Added manifest viewing and artifact download controls for completed exports.
- Kept advanced export products in the CLI/API while exposing only tested app controls.
- Updated catalog discovery messaging for the final published PVOL catalog.

### Export

- Added `/api/export/{job_id}/manifest` for reading completed artifact manifests.
- Added standard radar palette support to the PNG preview/export path, including Homeyer.

### Documentation

- Updated viewer, export, macOS, and Windows beta instructions to match the current app workflow.
- Added a macOS/Linux helper for dispatching the Windows GitHub Actions build and downloading the portable zip artifact.
- Replaced interim-catalog language with final PVOL catalog guidance for app users and beta testers.

## 0.2.0

Viewer interaction release informed by LROSE, Py-ART, and ARTView workflows.

### Viewer

- Added separate display min/max controls for colour scaling.
- Added range-ring visibility and ring-spacing controls.
- Added keyboard navigation: left/right for time, up/down for elevation, shift-left/right for item/day, and `0` to reset map view.
- Added four-panel comparison link toggles for map view, variable, and elevation while keeping time linked globally.
- Made panel readouts more explicit about rays, gates, sweep/dataset, elevation, palette, and display scale.

### Packaging

- Kept Mac and Windows packaging on the shared `master` code line.
- Updated the app/package version to `0.2.0`.

## 0.1.0

Initial implementation of the UK WSR Visualizer documentation site and toolkit foundation.

### Documentation

- Added a Sphinx documentation section using PyData Sphinx Theme.
- Added a landing page with user guide, example gallery, API reference, developer guide, and release notes sections.
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
