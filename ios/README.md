# UK WSR Visualizer iOS App

This folder contains the native iPhone app project:

```text
ios/UKWSRVisualizer.xcodeproj
```

The app is SwiftUI-native. It no longer wraps a web server in `WKWebView`.
It loads the public catalog directly from the NCAS/JASMIN object-store
inventory, lets the user choose radar/date/pulse/time/variable/elevation, and
renders a native PPI canvas with the same display concepts as the Mac viewer:
palette, opacity, range, azimuth, value, CAPPI height, noise-floor masking, and
tap identify.

The default public catalog is:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json
```

## HDF5 Status

The app has a native HDF5 reader boundary (`RadarVolumeReader` and
`NativeHDF5VolumeReader`) and the PPI renderer is implemented in Swift. The
machine did not have an iOS-buildable HDF5 C library available when this branch
was created, so arbitrary `.h5` decoding is currently reported explicitly in
the UI when a cached HDF5 object is selected.

Until an iOS HDF5 XCFramework is linked, the app uses catalog-derived sample
data to exercise the native renderer. That keeps the app installable and makes
the missing runtime visible rather than silently falling back to a web service.

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

## Next HDF5 Integration Step

Build or add an HDF5 C XCFramework for iOS, expose it as a `CHDF5` module, then
replace the guarded body in `NativeHDF5VolumeReader` with ODIM group traversal
and numeric dataset reads. The renderer, filter, palette, identify, catalog,
and cache code are already separated from that adapter.
