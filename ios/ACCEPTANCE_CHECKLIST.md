# UK WSR iOS Acceptance Checklist

Use this checklist for native iPhone beta builds installed on Overman with:

```bash
ios/install_to_device.sh
```

The public catalog and object-store source data are published. Treat missing
source URLs, missing pulse/time/variable metadata, and metadata-only catalog rows
as data availability issues in the published catalog unless a catalog metadata
flag says otherwise. This checklist verifies app behavior only.

## Build and Install

- Confirm `tests/test_ios_app.py` passes.
- Confirm the Swift unit tests pass for `UKWSRVisualizerTests`.
- Confirm the UI smoke tests pass for the `UKWSRVisualizerUITests` scheme on
  the current iOS simulator. Running that suite on Overman additionally
  requires a provisioning profile for the UI-test `.xctrunner` helper app.
- Confirm the generic iOS Xcode build succeeds with `CODE_SIGNING_ALLOWED=NO`
  and `ENABLE_DEBUG_DYLIB=NO`.
- Run `ios/install_to_device.sh` and confirm the printed installed version and
  build match `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` (`0.10` build
  `23` for this beta).
- Unlock Overman before launching from Xcode or `devicectl`.

## Launch and Selection

- The native launch screen shows the full-screen UK WSR icon while iOS starts
  the app.
- The first in-app screen keeps the full-screen UK WSR icon visible until the
  initial catalog/default-selection attempt finishes.
- Fresh launch loads the public catalog without crashing.
- If location is allowed, the default selection is the latest catalog day from
  the nearest available radar.
- Metadata shows the selected radar site latitude, longitude, and height when
  the root catalog provides `radars[].spatial`.
- If location is denied or unavailable, the app falls back to the latest
  available catalog day.
- Manual catalog search opens, filters by radar/date/text, and dismisses after
  selecting a row.
- Catalog search quick actions select nearest latest, latest published, and the
  current radar without needing to scroll through every available day.
- Catalog search filters by radar, year, date, pulse, and text.
- Recent selections appear after choosing a day and can be restored from the
  catalog search sheet.
- Selecting a radar/year in search shows whether full published coverage is
  loaded or will be loaded lazily.
- Selecting a new radar/day immediately clears the previous render, identify
  result, and warning text.
- Selecting Castor after a Chenies error does not leave a stale Chenies status
  or warning on screen.

## Unavailable Current Data

- A row with no pulse metadata shows `No pulses`.
- A row with no scan times shows `No times`.
- A row with no variables shows `No variables`.
- Non-renderable rows remain selectable and show availability messaging instead
  of presenting blank controls or a stale error.
- PVOL rows do not offer inferred variable/elevation choices. They use Auto
  until the HDF5 file is cached, then show only fields found inside that file.
- Missing source URLs are reported as data availability issues; do not treat
  them as app failures.
- Catalog, coverage, day scan catalog, source download, and HDF5 decode
  failures use distinct status text.

## Known Renderable Flow

- Select a known renderable row and confirm the app downloads/caches the source
  HDF5 if needed.
- Confirm the native PPI renders and the status names the selected radar/day,
  pulse, time, quantity, and dataset.
- Step backward and forward through scan times without changing radar/day.
- Tap the PPI and confirm identify updates for the selected frame.
- Change palette, opacity, range, azimuth, value limits, CAPPI height, and
  noise-floor filtering without crashing.

## Cache, Metadata, and Export

- `Clear Raw Cache` removes cached raw HDF5 files and disables itself when the
  cache is empty.
- Re-rendering after cache clear downloads the selected source again.
- Metadata rows update after each selected radar/day and no longer describe the
  previous selection.
- `Copy Source URL` copies the selected source URL when one exists.
- `Create PNG` enables only after a frame is rendered.
- `Share PNG` appears after PNG creation and shares the rendered PPI image.
