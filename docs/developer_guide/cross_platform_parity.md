# Desktop Platform Parity

UK WSR Visualizer currently has three desktop shells over the same radar
workflow:

- macOS desktop app;
- Windows desktop app;
- Linux Qt desktop app.

The shells use different native window technology, but they should expose the
same scientific choices and preserve the same data provenance.

## Required shared workflow

Each supported desktop app should let a user:

- discover the published PVOL catalog lazily;
- select radar, date, pulse, variable, time, and elevation;
- load a single-site UK WSR source object without modifying it;
- inspect a georeferenced PPI;
- pan, zoom, and identify values interactively;
- apply display scaling and background-cleanup controls;
- export screenshot, polar PPI, georeferenced, metadata, and animation products;
- inspect citation and provenance metadata;
- clear local raw-data caches;
- restore recent selections stored on the device.

## Standard user surface

The default interface should be aimed at a broad weather-radar user, not at a
developer debugging the pipeline. These controls should remain easy to find:

- date, radar, pulse, source item, variable, time, and elevation selection;
- previous/next time stepping and animation playback;
- zoom, pan, fit view, and click identify;
- the signal-preserving cleanup mode, enabled by default;
- opacity and colour legend;
- recent selections;
- screenshot, polar PPI PNG, MP4 animation, and source-file download;
- citation, provenance, metadata, refresh, and clear-cache actions.

The signal-preserving cleanup mode is the operational default for app rendering
and scientific exports. It uses the range-dependent background profile as
evidence only, then removes gates only when texture, companion-field, learned
background, or static-clutter evidence supports a noise/clutter decision. It
must never modify the source PVOL HDF5 object.

## Advanced diagnostics

Controls that are mainly for method development or audit should not dominate
the main workflow. Keep these behind a collapsed **Advanced diagnostics and
filters** section:

- palette override and manual display min/max;
- range-ring spacing and specialist basemap selection;
- range, azimuth, value, and CAPPI-style filters;
- cleanup method and evidence-margin tuning;
- raw mask diagnostics and component-level QC evidence;
- 4-panel link options beyond the default linked time.

These controls are still important for beta testing and publication support,
but they should be presented as diagnostics rather than as decisions every
standard user must make.

## Platform expectations

The desktop apps share the FastAPI/static viewer implementation. The macOS shell
uses a native WebKit window, the Windows shell uses WebView2, and the Linux
shell uses Qt WebEngine. The app should not depend on the user's default browser
for normal operation.

Desktop interaction support should include:

- mouse-wheel or trackpad zoom around the pointer;
- drag pan;
- double-click zoom;
- touch pan and pinch zoom where the hardware supports it;
- click identify without firing accidentally after drag;
- linked view in 4-panel comparison mode.

Desktop export support includes screenshot manifests, polar PPI PNG/MP4,
metadata JSON, KMZ overlays, GeoTIFF, and provenance manifests. These exports
should label their coordinate mode clearly so users know whether a product is
screen-view, polar radar coordinates, or georeferenced.

## Packaging checks

Before a desktop beta release:

- build and smoke-test the macOS zip;
- build and smoke-test the Windows portable zip;
- build and smoke-test the Linux AppImage or tarball;
- confirm all include MP4 encoder dependencies where the platform supports MP4;
- confirm recent selections are written under the platform app-data directory;
- confirm source files are not modified by plotting, masking, or export.

## Do not regress desktop features

Desktop changes should not remove:

- 4-panel comparison;
- session/project save and load;
- export provenance manifests;
- citation panel;
- help tooltips;
- pointer-field toggles.
