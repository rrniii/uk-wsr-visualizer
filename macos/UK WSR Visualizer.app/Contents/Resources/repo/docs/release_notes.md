# Release Notes

## 0.2.1

Unreleased beta polish for app-visible provenance and package guidance.

### Viewer

- Fixed open-ended catalogue searches so a start-only date means "from this
  date onward" and an end-only date means "up to this date", including across
  PVOL year-coverage files.
- Moved four-panel selectors into a compact header above each plot so controls
  no longer cover radar data. Per-panel palette and display limits remain
  available through a compact **Display** control.
- Made linked pan and zoom responsive by previewing the existing rendered
  layers during interaction and doing the expensive radar redraw only after
  the interaction settles.
- Fixed year/month catalogue searches: `YYYY`, `YYYY-MM`, and `YYYY-MM-DD`
  now expand predictably and invalid partial dates are rejected rather than
  silently interpreted as a different month.
- Made each four-panel comparison retain its own variable, elevation, palette,
  and display range. **Fit View** now fits each visible radar panel rather
  than using one panel's extent for all four.
- Made the displayed sweep elevation authoritative, so selectors no longer
  revert to the lowest sweep after an independent panel change.
- Moved comparison-only palette and display-range controls into each panel and
  added an explicit colour-scale linking option.
- Renamed **Capture PPI** to **Save current map image** and prevented the
  browser context menu from offering a misleading transparent radar-only image.
- Added an **Export & Provenance** panel with explicit screenshot, polar PPI, georeferenced map, and metadata export modes.
- Added manifest viewing and artifact download controls for completed exports.
- Kept the current radar frame visible while animation frames load, with adjacent-frame preloading and preserved zoom/pan during playback.
- Added device-local recent selections for reopening successful radar/date/pulse/time/variable/elevation plots.
- Added touch pan and pinch zoom to the desktop map interaction path.
- Kept advanced export products in the CLI/API while exposing only tested app controls.
- Made signal-preserving noise/clutter cleanup the visible default and moved method tuning into advanced diagnostics.
- Updated catalog discovery messaging for the final published PVOL catalog.
- Added support for lazy PVOL field-index sidecars so time, variable, and elevation controls can populate without downloading a representative HDF5 file.
- Added raw-file prefetch and cached-time labels so animation and time stepping warm adjacent source files in the background.
- Added a bounded in-process PPI response cache to reduce repeated HDF5 reads during cached playback and rapid control changes.
- Retried transient representative-file scans and incomplete cached hydration so
  all four comparison panels receive their available variables and elevations.
- Stopped rebuilding large per-panel item menus on every control change, making
  cached independent time and elevation changes respond immediately.

### Export

- Added explicit full-day and start/end controls for MP4 exports. The app now
  shows frame count, frame delay, frame rate, and estimated video duration
  before export.
- Added MP4 timing details to export sidecars and artifact manifests, including
  selected frame times, expected and actual duration, and skipped frames.
- Improved screenshot composition so the field legend fits within the exported
  image and the header records the selected radar, date, pulse, time, variable,
  and sweep.
- Improved the screen-view PNG so it includes the map, PPI, range rings,
  colour legend, and selected radar metadata.
- Clarified labels for screen-view, polar radar-coordinate, and georeferenced
  exports so their coordinate systems and intended uses are explicit.
- Added a packaged MP4 encoder smoke test to macOS, Windows, and Linux release
  builds, preventing a beta release when the animation encoder is absent.
- Added `/api/export/{job_id}/manifest` for reading completed artifact manifests.
- Added `/api/ppi-image/...` as a server-rendered polar PPI image route for fast frame/image products.
- Added MP4 animation export with frame metadata and provenance manifests.
- Added standard radar palette support to the PNG preview/export path, including Homeyer.
- Added coordinate-mode metadata to export requests, manifests, and artifacts so users can distinguish screen-view screenshots, polar radar-coordinate images, and georeferenced products.

### Documentation

- Updated viewer, export, macOS, and Windows beta instructions to match the current app workflow.
- Added a macOS/Linux helper for dispatching the Windows GitHub Actions build and downloading the portable zip artifact.
- Replaced interim-catalog language with final PVOL catalog guidance for app users and beta testers.
- Added a cross-platform parity contract for the Mac, Windows, and iPhone apps, including what belongs in the signal-preserving interface versus advanced diagnostics.
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
