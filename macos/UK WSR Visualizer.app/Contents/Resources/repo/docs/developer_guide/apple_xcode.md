# Mac Xcode Development

UK WSR Visualizer has an Xcode-managed macOS shell for the desktop app:

```text
macos/UKWSRVisualizerMac.xcodeproj
```

The desktop Mac app remains powered by the Python FastAPI/static viewer. The
Xcode shell is responsible for the native window, splash screen, app menus,
server startup/shutdown, logs, and packaging.

## Build the Mac app

Use the release helper from the repository root:

```bash
macos/build-xcode-macos.sh
```

The script builds with `xcodebuild`, embeds a clean copy of the repository into
the app bundle, sets the bundle version from `pyproject.toml`, writes the Git
commit into `Info.plist`, and creates:

```text
build/xcode-macos/UK WSR Visualizer macOS Xcode Beta.zip
```

GitHub Actions also has a `macOS Beta` workflow that runs the focused macOS
packaging tests, builds this zip on `macos-latest`, and publishes it as a
workflow artifact.

To sign a local beta, set:

```bash
DEVELOPER_ID_APPLICATION="Developer ID Application: ..."
macos/build-xcode-macos.sh
```

To sign and notarize locally, set the Developer ID identity and either an
existing notarytool keychain profile:

```bash
DEVELOPER_ID_APPLICATION="Developer ID Application: ..." \
NOTARYTOOL_KEYCHAIN_PROFILE="uk-wsr-notary" \
NOTARIZE=1 \
macos/build-xcode-macos.sh
```

or Apple ID notary credentials:

```bash
DEVELOPER_ID_APPLICATION="Developer ID Application: ..." \
APPLE_ID="name@example.org" \
APPLE_TEAM_ID="ABCDE12345" \
APPLE_APP_SPECIFIC_PASSWORD="app-specific-password" \
NOTARIZE=1 \
macos/build-xcode-macos.sh
```

The GitHub Actions workflow supports the same path when these repository
secrets are configured:

```text
MACOS_CERTIFICATE_P12_BASE64
MACOS_CERTIFICATE_PASSWORD
MACOS_SIGNING_KEYCHAIN_PASSWORD
DEVELOPER_ID_APPLICATION
NOTARYTOOL_KEYCHAIN_PROFILE
APPLE_ID
APPLE_TEAM_ID
APPLE_APP_SPECIFIC_PASSWORD
```

Only the certificate and identity are required for signing. Notarization uses
`NOTARYTOOL_KEYCHAIN_PROFILE` when present, otherwise it uses the Apple ID,
Team ID, and app-specific password. When signing secrets are absent, the
workflow still publishes an unsigned beta artifact for internal testing.

## Run from Xcode

Open:

```text
macos/UKWSRVisualizerMac.xcodeproj
```

Select the `UKWSRVisualizerMac` scheme and run it. The scheme sets
`UK_WSR_VISUALIZER_REPO_ROOT=$(SRCROOT)/..` so Debug launches can use the
working tree instead of requiring an embedded repository copy.

Runtime files remain outside the repository:

```text
~/Library/Application Support/UK WSR Visualizer/
```

Use the app menu items to open logs, clear the raw cache, or reload the viewer.

## Instruments

Use Instruments from Xcode against the `UKWSRVisualizerMac` scheme:

- Time Profiler: launch to `/api/ready`, PPI render, time stepping.
- Allocations: loading and clearing large HDF5 source objects.
- Network: object-store catalogue and source-object downloads.
- File Activity: raw cache writes, pruning, and export writes.
- Energy Log: idle viewer and animation/time stepping.

Save trace summaries with release artifacts, not inside the repository.

## Beta distribution

For desktop Mac beta distribution, prefer a Developer ID signed and notarized
zip or dmg.

## Local permission notes

Command-line Simulator and Instruments runs can fail if Terminal or the agent
process lacks access to Xcode developer services and user caches. If `simctl`
or `xctrace` fails with permission errors, grant the exact terminal app used for
automation the required macOS permissions and retry from a normal user session.
