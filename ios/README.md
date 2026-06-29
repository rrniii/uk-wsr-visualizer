# UK WSR Visualizer iOS App

This folder contains the native iPhone app project:

```text
ios/UKWSRVisualizer.xcodeproj
```

The app is SwiftUI-native. It no longer wraps a web server in `WKWebView`.
It loads the public catalog directly from the NCAS/JASMIN object-store interim
PVOL publish, uses the phone location at launch to select the latest day from the
nearest available radar when radar coordinates are available, hydrates
raw-volume day entries from their linked scan catalog, lets the user
search/filter radar days by radar, year, date range, pulse, and text before
choosing time/variable/elevation, and renders a native PPI
canvas with the same display concepts as the Mac viewer: palette, opacity,
range, azimuth, value, CAPPI height, noise-floor masking, tap identify, time
stepping, source metadata diagnostics, and PNG sharing. If location permission
is denied or no radar coordinates are present in the catalog, the app falls
back to the latest available catalog day.

The default public catalog is:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json
```

This root catalog is an interim uploaded-only catalog for smoke testing. It
advertises `interim: true` and `upload_complete: false`, so missing dates should
be treated as "not uploaded here yet" rather than "no historical data exists".
The root `radars[]` entries include `spatial.latitude`, `spatial.longitude`,
`spatial.height_m`, and `spatial.source`, which the app uses for nearest-radar
startup selection before it downloads any day-level data. The app fetches only
the root catalog at startup, then loads per-radar/year `coverage.json` files
lazily as the catalog search needs them. It loads a day catalog only after a day
is selected, then downloads the selected HDF5 PVOL scan from that file record's
`object_url`.

The catalog browser is designed for the interim catalog scale rather than a
single long list. It provides quick actions for nearest latest, latest uploaded,
and the current radar; persists recent selections locally; labels rows as
cached, renderable, scan-catalog, no-source, no-pulse, or no-variable; and keeps
the heavy day catalogs lazy until a day is selected.
For interim PVOL file records, the app does not expose inferred variable or
elevation choices. It uses Auto until the HDF5 file is cached, inspects the ODIM
field metadata, and then enables only variables and datasets that actually exist
in that file.

## HDF5 Status

The app now links a vendored iOS HDF5 2.1.1 static build with DEFLATE/zlib
enabled. `NativeHDF5VolumeReader` calls the `UKHDF5Reader` C bridge to open
cached ODIM HDF5 scans, find the requested `datasetN/dataM` quantity, apply
ODIM `gain`, `offset`, `nodata`, and `undetect` metadata, and pass the decoded
polar grid to the native Swift PPI renderer.

The app does not display synthetic radar fields as a fallback. If a selected
scan has not been cached, the app downloads and caches the required raw HDF5
source before rendering. The raw cache is pruned by age and size, while the
currently selected scan is preserved during download and render. `Clear Raw Cache`
removes local raw files; they are downloaded again when needed. If HDF5 decode
fails, the native renderer reports the real decode error.

## Tests

The Xcode project includes the `UKWSRVisualizerTests` unit-test target. The
tests use fixture JSON to verify interim PVOL root decoding, root
`radars[].spatial` nearest-radar metadata, lazy year coverage loading, day
catalog hydration from `object_url`, fallback `uk_wsr:spatial` support, and
selection-state cleanup without hitting the live object store.

The `UKWSRVisualizerUITests` target is a simulator-first smoke suite for the
real SwiftUI app, run through the dedicated `UKWSRVisualizerUITests` shared
scheme so the main device scheme does not need a UI-test runner provisioning
profile. It launches the app with deterministic fixture catalog/location data,
waits for startup loading to finish, verifies the main radar/display/metadata
sections, opens catalog search, and confirms lazy coverage/search rows are
visible. Running the UI suite on a physical iPhone also requires Xcode to create
a provisioning profile for the `.xctrunner` helper app.

## Install on an iPhone

On this Mac, the repeatable command-line installer is:

```bash
ios/install_to_device.sh
```

It builds the app for iPhone, signs it with the existing Apple Development
certificate/profile, installs it on Overman, and prints the installed version.
The installer chooses the local signing identity that matches the selected
Xcode-managed provisioning profile. If it pauses at `Signing with ...`, approve
the macOS keychain prompt allowing `codesign` to use the Apple Development key.
After installing, run the manual checks in
[`ACCEPTANCE_CHECKLIST.md`](ACCEPTANCE_CHECKLIST.md). The checklist deliberately
treats missing source URLs or field metadata as expected temporary catalog/data
conditions while the object-store catalog is still being built.

1. Install full Xcode from the Mac App Store.
2. Open `ios/UKWSRVisualizer.xcodeproj`.
3. Select the `UKWSRVisualizer` target, then `Signing & Capabilities`.
4. Set `Team` to your Apple ID team.
5. If Xcode reports that the bundle identifier is unavailable, change
   `com.rrniii.ukwsrvisualizer` to a unique value.
6. Connect the iPhone, choose it from the run destination menu, and press Run.
7. If prompted on the iPhone, enable Developer Mode and trust the Mac.

After signing is configured, a command-line build should also work:

```bash
xcodebuild \
  -project ios/UKWSRVisualizer.xcodeproj \
  -scheme UKWSRVisualizer \
  -destination 'generic/platform=iOS' \
  build
```

## HDF5 Dependency

The committed HDF5 files live under:

```text
ios/ThirdParty/HDF5
```

They were built from the official HDFGroup HDF5 2.1.1 source release for
`iphoneos` and `iphonesimulator` with static libraries and zlib support. The
Xcode project links `libhdf5.a` from `ios/ThirdParty/HDF5/lib/$(PLATFORM_NAME)`
and the system `libz`.
