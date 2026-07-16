# Release Notes

## 0.2.1

Unreleased beta polish for app-visible provenance and package guidance.

### Viewer

- Added an **Export & Provenance** panel with explicit screenshot, polar PPI, georeferenced map, and metadata export modes.
- Added manifest viewing and artifact download controls for completed exports.
- Kept the current radar frame visible while animation frames load, with adjacent-frame preloading and preserved zoom/pan during playback.
- Added device-local recent selections for reopening successful radar/date/pulse/time/variable/elevation plots.
- Added touch pan and pinch zoom to the desktop map interaction path.
- Kept advanced export products in the CLI/API while exposing only tested app controls.
- Made **Raw decoded data** the default cleanup mode. Basic range-dependent
  noise removal is available separately, while learned/noise-and-clutter
  cleanup is explicitly labelled experimental after beta feedback showed it
  could remove real weak echoes.
- Replaced ODIM codes in normal viewer controls, legends, recents, saved
  figures, and manifests with scientific long names such as **Horizontal
  Reflectivity**, while retaining the codes in source/provenance metadata.
- Added a time slider, explicit long-pulse/short-pulse scan selection, and
  scan geometry text showing available elevations and maximum range.
- Extended four-panel comparison with independent scan type, palette, and
  display limits per panel; users can optionally link those controls.
- Added date-scoped multiple-radar selection for opening up to four radars in
  the comparison workspace.
- Added a publication-oriented **Save Figure** action that includes the map,
  colour legend, and selection metadata rather than saving an unadorned PPI.
- Updated catalog discovery messaging for the final published PVOL catalog.
- Added support for lazy PVOL field-index sidecars so time, variable, and elevation controls can populate without downloading a representative HDF5 file.
- Added raw-file prefetch and cached-time labels so animation and time stepping warm adjacent source files in the background.
- Added a bounded in-process PPI response cache to reduce repeated HDF5 reads during cached playback and rapid control changes.

### Export

- Added `/api/export/{job_id}/manifest` for reading completed artifact manifests.
- Added `/api/ppi-image/...` as a server-rendered polar PPI image route for fast frame/image products.
- Added MP4 animation export with frame metadata and provenance manifests.
- Added standard radar palette support to the PNG preview/export path, including Homeyer.
- Added coordinate-mode metadata to export requests, manifests, and artifacts so users can distinguish screen-view screenshots, polar radar-coordinate images, and georeferenced products.
- Package builds now include MP4 and GeoTIFF runtime dependencies for Mac,
  Windows, and Linux desktop distributions.

### Documentation

- Updated viewer, export, macOS, and Windows beta instructions to match the current app workflow.
- Added a macOS/Linux helper for dispatching the Windows GitHub Actions build and downloading the portable zip artifact.
- Replaced interim-catalog language with final PVOL catalog guidance for app users and beta testers.
- Added a desktop parity contract for the Mac, Windows, and Linux apps, including what belongs in the signal-preserving interface versus advanced diagnostics.
- Documented the size-bounded LRU source-file cache and catalogue/field-index sidecar cache behavior.

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
