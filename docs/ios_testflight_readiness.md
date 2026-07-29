# UK WSR iOS TestFlight Readiness

Status date: 2026-07-30

## Build Identity

- App name: UK WSR
- Bundle ID: `com.rrniii.ukwsrvisualizer`
- Version: `0.10`
- Current build: `53`
- Signing team: `D863HTPFQC`
- Minimum iOS: 16.0

## Beta Release Notes

UK WSR is a native iPhone radar visualiser for UK weather surveillance radar PVOL/HDF5 data.

This TestFlight build focuses on the field workflow:

- Opens to a native radar display with lazy public-catalog loading.
- Defaults toward the latest data from the closest radar when location is allowed.
- Provides availability-driven radar, pulse, time, variable, and elevation selection.
- Renders real PVOL/HDF5 scans with colour bars, map underlay, zoom/pan, and tap probe readouts.
- Includes explicit background-cleaning modes: Off, Light, Standard, and Strong.
- Saves MP4 frame queues so long exports can be resumed after interruption.

Known limitation: iOS can still suspend long MP4 exports when the app is backgrounded or the phone locks. The app saves rendered frames and offers resume/retry controls, but full-day exports should still be tested with the phone awake.

## App Store Connect Privacy Notes

Recommended privacy answers for this build:

- Tracking: No.
- Data linked to user: No.
- Data used to track user: No.
- Location: Used on device to choose the nearest radar. The app does not send device location to the UK WSR object store.
- User content: Exported PNG/MP4 files are written locally to the app's Documents/Downloads area.
- Diagnostics/analytics: No custom analytics or telemetry are implemented in the app code.

The app includes `PrivacyInfo.xcprivacy` declaring UserDefaults access for app-local settings/recent selections.

## Capabilities And Permissions

- Location When In Use: required for nearest-radar default selection.
- Network access: standard HTTPS fetches from the public NCAS object store.
- File sharing / documents: enabled so exported PNG/MP4 files are visible in Files.
- Background execution: uses `beginBackgroundTask` and disables idle timer during MP4 export, but does not claim indefinite background processing.

## Export Compliance

The app uses Apple platform networking/TLS through `URLSession` and does not implement custom cryptography. Confirm the standard App Store Connect export-compliance answers during upload.

## Archive Checklist

1. Confirm the catalog endpoint is smoke-test ready.
2. Bump build number.
3. Run unit tests.
4. Build archive with the `UKWSRVisualizer` scheme.
5. Upload archive to App Store Connect.
6. Fill TestFlight beta notes using the release notes above.
7. Confirm privacy answers match this file.
8. Add internal testers first.
9. Smoke test on physical iPhone: launch, nearest latest, catalog search, selector changes, probe, map, PNG export, short MP4 export, interrupted/resumed MP4 export.

## Apple References

- TestFlight: https://developer.apple.com/testflight/
- App Store Connect Help: https://developer.apple.com/help/app-store-connect/
- Privacy manifest files: https://developer.apple.com/documentation/bundleresources/privacy-manifest-files
