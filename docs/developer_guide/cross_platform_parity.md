# Cross-Platform Parity

UK WSR Visualizer has two product families:

- desktop applications for macOS, Windows, and Linux, built from the shared
  Python/FastAPI viewer on `master`;
- native iPhone and iPad applications, developed separately while the mobile
  beta is evaluated.

The native shells differ, but equivalent selections must mean the same thing.
Every platform should preserve the source object, radar, UTC time, pulse,
variable, sweep, display choices, optional processing choices, and software
version needed to reproduce a view or export.

## Required shared workflow

Each supported app should let a user:

- discover the published PVOL catalog lazily;
- select radar, date, pulse, variable, time, and elevation;
- load a single-site UK WSR source object without modifying it;
- inspect a georeferenced PPI;
- pan, zoom, and identify values interactively;
- compare the unmodified decoded view with optional in-memory cleanup where
  supported;
- export a PNG quick-look;
- export an MP4 time animation;
- inspect citation and provenance metadata;
- clear local raw-data caches;
- restore recent selections stored on the device.

## Standard user surface

The default interface should be aimed at a broad weather-radar user, not at a
developer debugging the pipeline. These controls should remain easy to find:

- date, radar, pulse, source item, variable, time, and elevation selection;
- previous/next time stepping and animation playback;
- zoom, pan, fit view, and click identify;
- a clearly labelled optional cleanup control and an obvious baseline state;
- opacity and colour legend;
- recent selections;
- screenshot, polar PPI PNG, MP4 animation, and source-file download where the
  platform supports them;
- citation, provenance, metadata, refresh, and clear-cache actions.

The current desktop interface starts with cleanup enabled, but this is a
reversible viewing choice, not a claim that every retained gate is signal or
every removed gate is nuisance. Scientific users must be able to turn cleanup
off, compare the decoded baseline, and retain the selected settings in export
provenance. Cleanup must never modify the source PVOL HDF5 object.

## Advanced diagnostics

Controls that are mainly for method development or audit should not dominate
the main workflow. Keep these behind a collapsed **Advanced diagnostics and
filters** section on desktop, or an **Advanced** sheet on iOS:

- palette override and manual display min/max;
- range-ring spacing and specialist basemap selection;
- range, azimuth, value, and CAPPI-style filters;
- cleanup method and evidence-margin tuning;
- raw mask diagnostics and component-level QC evidence;
- 4-panel link options beyond the default linked time.

These controls are still important for beta testing and publication support,
but they should be presented as diagnostics rather than as decisions every
standard user must make.

## Desktop-specific expectations

The desktop apps share the FastAPI/static viewer implementation. The macOS shell
uses a native WebKit window and the Windows shell uses WebView2. The app should
not depend on the user's default browser for normal operation.

Desktop interaction support should include:

- mouse-wheel or trackpad zoom around the pointer;
- drag pan;
- double-click zoom;
- touch pan and pinch zoom where the hardware supports it;
- click identify without firing accidentally after drag;
- linked view in 4-panel comparison mode.

Desktop export support includes richer server-backed products than the iPhone
app: screenshot manifests, polar PPI PNG/MP4, metadata JSON, KMZ overlays,
GeoTIFF, and provenance manifests. These exports should label their coordinate
mode clearly so users know whether a product is screen-view, polar radar
coordinates, or georeferenced.

## Mobile-specific expectations

The iPhone and iPad apps are native SwiftUI applications and should not become
WebView wrappers. They should preserve the same scientific choices using
platform-appropriate controls:

- the final published PVOL catalog is loaded lazily;
- radar site metadata from the root catalog is used for nearest-radar behavior;
- source PVOL objects are cached locally and decoded on device;
- MapKit provides the map underlay;
- recent selections are stored with `UserDefaults`;
- PNG and MP4 are exported through the native share/files workflow;
- cleanup parameters and provenance mean the same thing as on desktop, even
  when controls are arranged differently.

The mobile apps can have fewer operational export formats than desktop, but
catalogue, filtering, cache, rendering, and provenance semantics should remain
compatible.

## Packaging checks

Before a desktop beta release:

- build and smoke-test the macOS zip;
- build and smoke-test the Windows portable zip;
- build and smoke-test the Linux AppImage and portable tarball on the supported
  Linux runners;
- confirm both include the MP4 encoder dependencies;
- confirm recent selections are written under the platform app-data directory;
- confirm source files are not modified by plotting, masking, or export.

Before a mobile beta release, test both iPhone and iPad layouts, catalogue
loading, local cache behavior, PPI rendering, sharing, and recent selections on
the exact build distributed through TestFlight or direct installation.

## Do not regress desktop-only features

The mobile apps do not need every desktop workflow, but desktop changes should
not remove:

- 4-panel comparison;
- session/project save and load;
- export provenance manifests;
- citation panel;
- help tooltips;
- pointer-field toggles.
