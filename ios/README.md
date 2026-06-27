# UK WSR Visualizer iOS App

This folder contains a native iPhone shell for UK WSR Visualizer:

```text
ios/UKWSRVisualizer.xcodeproj
```

The iOS app uses SwiftUI and `WKWebView`. It does not bundle the Python/FastAPI
server because a normal iPhone app cannot run this repository's scientific
Python stack and HDF5 cache in the same way as the macOS and Windows wrappers.
Instead, it opens a reachable UK WSR Visualizer server.

The default server is:

```text
http://130.246.214.121
```

Use the gear button in the app to point it at another server.

## Install on an iPhone

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

For local development, run the server on an address the iPhone can reach:

```bash
uk-wsr-visualizer api --host 0.0.0.0 --port 8000
```

Then set the iOS app server URL to your Mac's Wi-Fi address, for example:

```text
http://192.168.1.42:8000
```

Do not use `127.0.0.1` from the iPhone; that points back to the iPhone, not the
Mac.

## App Store Note

`Info.plist` currently permits arbitrary HTTP loads so the app can connect to
the existing HTTP deployment and local development servers. Before App Store
distribution, use HTTPS for the visualizer service and tighten App Transport
Security.
