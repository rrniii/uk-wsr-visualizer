# Cross-Platform Parity

UK WSR Visualizer has three user-facing shells over the same radar workflow:

- macOS desktop app;
- Windows desktop app;
- iPhone app.

The shells can use different native UI technology, but they should expose the
same scientific choices and preserve the same data provenance.

## Required shared workflow

Each supported app should let a user:

- discover the published PVOL catalog lazily;
- select radar, date, pulse, variable, time, and elevation;
- load a single-site UK WSR source object without modifying it;
- inspect a georeferenced PPI;
- pan, zoom, and identify values interactively;
- apply display scaling and noise-floor masking controls where supported;
- export a PNG quick-look;
- export an MP4 time animation;
- inspect citation and provenance metadata;
- clear local raw-data caches;
- restore recent selections stored on the device.

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

## Packaging checks

Before a desktop beta release:

- build and smoke-test the macOS zip;
- build and smoke-test the Windows portable zip;
- confirm both include the MP4 encoder dependencies;
- confirm recent selections are written under the platform app-data directory;
- confirm source files are not modified by plotting, masking, or export.

## Do not regress desktop-only features

The iPhone app does not need every desktop workflow, but desktop changes should
not remove:

- 4-panel comparison;
- session/project save and load;
- export provenance manifests;
- citation panel;
- help tooltips;
- pointer-field toggles.
