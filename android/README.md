# UK WSR Visualizer for Android

Native Kotlin/Compose viewer for Android phones and tablets. It reads the public
PVOL catalogue lazily and decodes the selected HDF5 object on the device. There
is no Python installation, hosted rendering service or simulated-data fallback.

## Build

Use Java 21, Android SDK 36, NDK `28.2.13676358` and CMake `3.31.6`. Set `sdk.dir`
in an untracked `local.properties` file, or set `ANDROID_HOME`.

```sh
sdkmanager 'platforms;android-36' 'build-tools;36.0.0' 'ndk;28.2.13676358' 'cmake;3.31.6'
./gradlew lintDebug testDebugUnitTest assembleDebug
./gradlew connectedDebugAndroidTest
```

HDF5 2.1.0 source is downloaded from HDFGroup during native configuration and
verified against a fixed SHA-256. HDF5 and the shared ODIM C reader are compiled
into the JNI library for `arm64-v8a` and `x86_64`, with 16 KB ELF alignment.
`shared/native/UKHDF5Reader` is also used by iOS. The Android API minimum is 29
(Android 10); the target is 36. Tests exercise compressed HDF5, NODATA/UNDETECT,
measured ray sectors, centre-valued average azimuths, and malformed attributes.

## Viewer

- Both current dual-polarisation and earlier public catalogues; radar/year/date
  filtering, nearest radar with optional coarse location, and recent selections.
- Source-derived field/elevation choices, time stepping and playback, map
  pan/zoom, range rings, palettes, display limits, value/beam-height filters and
  gate readouts. Missing pulse/time/field selections produce explicit errors.
- Four independent panels, with separate time/map/variable/elevation links.
- Portable project save/import/share compatible with desktop and iOS JSON.
  Experimental learned-model settings are never enabled by a project import.
- PNG, original HDF5 and provenance export; H.264 MP4 with a fixed geographic
  grid, source hashes, exact frame times and explicit skipped-frame records.
  Completed video frames are cached, so repeating a cancelled export resumes.
- On-device bounded source cache (8 GiB, seven days); selected volumes are
  protected during normal pruning. Catalogue caches can support an explicitly
  labelled offline selection, and cached source objects can be reopened.

The map is an Android Canvas renderer using measured ray geometry and an OSM
raster background, with a grid option. It is not a WebView. OSM attribution,
application User-Agent and seven-day HTTP-equivalent tile reuse are retained;
there is no bulk/offline basemap download. Raw radar cache clearing does not
clear the separate basemap cache.

Cleanup implements the supported preservation-first mobile rules using canonical
companions and the selected field aliases, including per-ray scalar companions.
Android spatial masks use measured azimuths; this differs from the existing iOS
uniform-angle mask, so complete cross-platform processing parity is not claimed.
Missing companion evidence retains the gate. Optional texture, companion-moment and
static-clutter display masks are explicit advanced controls, recorded in
exports. Learned research models remain disabled. The original HDF5 object is
never edited. A height slice selects observed gates within 250 m of the chosen
height; it does not interpolate a CAPPI.

## Live verification

The regular test suite uses small declared fixtures. The live smoke is opt-in:

```sh
./gradlew assembleDebug assembleDebugAndroidTest
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w -e class com.rrniii.ukwsrvisualizer.RealSourceSmokeTest \
  -e runLive true com.rrniii.ukwsrvisualizer.debug.test/androidx.test.runner.AndroidJUnitRunner
```

It downloads real Castor Bay source volumes, checks rendered pixels and hashes,
exports PNG and MP4, decodes the MP4 with Android's media stack, and exercises
cancellation/resume. It also verifies missing requested fields fail rather than
silently substituting a different field.

## Signed artifacts

`tools/build-release.py` builds signed APK/AAB files from a clean committed
checkout using a UK WSR-specific signing configuration outside the repository.
The JSON configuration contains `store_file`, `store_password`, `key_alias`,
`key_password`; restrict that file and keystore to the owning account. Do not
reuse another app's key. `--version-code` must exceed any previously distributed
build. The script records source commit, checksums and certificate verification.

```sh
python3 tools/build-release.py --signing-config /private/path/signing.json \
  --version-code 1 --output /path/to/delivery
```

The package ID is `com.rrniii.ukwsrvisualizer` (debug adds `.debug`). Signed
artifacts are not proof of Google Play delivery. Play upload, processing, tester
availability and a Play-installed device check remain separate release steps.

Dependency and project notices are under `app/src/main/assets/licenses/`.
