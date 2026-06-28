# UK WSR Visualizer iOS App

This folder contains the native iPhone app project:

```text
ios/UKWSRVisualizer.xcodeproj
```

The app is SwiftUI-native. It no longer wraps a web server in `WKWebView`.
It loads the public catalog directly from the NCAS/JASMIN object-store
inventory, hydrates raw-volume day entries from their linked scan catalog, lets
the user choose radar/date/pulse/time/variable/elevation, and renders a native
PPI canvas with the same display concepts as the Mac viewer: palette, opacity,
range, azimuth, value, CAPPI height, noise-floor masking, and tap identify.

The default public catalog is:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

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

## Install on an iPhone

On this Mac, the repeatable command-line installer is:

```bash
ios/install_to_device.sh
```

It builds the app for iPhone, signs it with the existing Apple Development
certificate/profile, installs it on Overman, and prints the installed version.

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
