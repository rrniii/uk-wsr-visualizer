#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QC_ROOT="${UK_WSR_QC_ROOT:-$ROOT_DIR/../uk-wsr-qc}"
BUILD_PYTHON="${BUILD_PYTHON:-python3}"
ARCH="${TARGET_ARCH:-$(uname -m)}"
VERSION="$("$BUILD_PYTHON" "$ROOT_DIR/tools/project_version.py")"
GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$ROOT_DIR/build/xcode-macos}"
DERIVED_DATA="${DERIVED_DATA:-$ROOT_DIR/build/xcode-macos-derived}"
SERVER_DIST="$ROOT_DIR/build/macos-server-dist"
APP_NAME="UK WSR Visualizer.app"
PACKAGED_APP="$ARTIFACT_ROOT/$APP_NAME"
ZIP_PATH="$ARTIFACT_ROOT/UK-WSR-Visualizer-$VERSION-macOS-$ARCH-beta.zip"
export MACOSX_DEPLOYMENT_TARGET=13.0

freeze_args=(--qc-root "$QC_ROOT" --output "$SERVER_DIST" --work "$ROOT_DIR/build/macos-frozen-server" --target-arch "$ARCH")
if [[ -n "${DEVELOPER_ID_APPLICATION:-}" ]]; then
  freeze_args+=(--codesign-identity "$DEVELOPER_ID_APPLICATION")
fi
"$BUILD_PYTHON" "$ROOT_DIR/tools/build_frozen_server.py" "${freeze_args[@]}"

xcodebuild -project "$ROOT_DIR/macos/UKWSRVisualizerMac.xcodeproj" \
  -scheme UKWSRVisualizerMac -configuration Release -derivedDataPath "$DERIVED_DATA" \
  ARCHS="$ARCH" ONLY_ACTIVE_ARCH=YES MARKETING_VERSION="$VERSION" \
  CURRENT_PROJECT_VERSION="${BUILD_NUMBER:-1}" CODE_SIGNING_ALLOWED=NO build

mkdir -p "$ARTIFACT_ROOT"
rm -rf "$PACKAGED_APP"
ditto --norsrc "$DERIVED_DATA/Build/Products/Release/$APP_NAME" "$PACKAGED_APP"
mkdir -p "$PACKAGED_APP/Contents/Helpers"
ditto --norsrc "$SERVER_DIST/UKWSRServer.app" "$PACKAGED_APP/Contents/Helpers/UKWSRServer.app"
cp "$SERVER_DIST/uk-wsr-visualizer-server/build-info.json" "$ARTIFACT_ROOT/build-info.json"
/usr/libexec/PlistBuddy -c "Add :UKWSRGitCommit string $GIT_COMMIT" "$PACKAGED_APP/Contents/Info.plist"
xattr -cr "$PACKAGED_APP"
"$BUILD_PYTHON" "$ROOT_DIR/tools/check_macos_bundle.py" "$PACKAGED_APP" --report "$ARTIFACT_ROOT/runtime-platforms.json"
if [[ -n "${DEVELOPER_ID_APPLICATION:-}" ]]; then
  codesign --force --options runtime --sign "$DEVELOPER_ID_APPLICATION" "$PACKAGED_APP"
else
  codesign --force --deep --sign - "$PACKAGED_APP"
fi
codesign --verify --deep --strict "$PACKAGED_APP"

create_zip() {
  rm -f "$ZIP_PATH"
  ditto -c -k --norsrc --keepParent "$PACKAGED_APP" "$ZIP_PATH"
}
create_zip
if [[ "${NOTARIZE:-0}" == 1 ]]; then
  if [[ -z "${DEVELOPER_ID_APPLICATION:-}" ]]; then
    echo "NOTARIZE=1 requires a Developer ID Application identity" >&2
    exit 1
  fi
  if [[ -n "${NOTARYTOOL_KEYCHAIN_PROFILE:-}" ]]; then
    xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$NOTARYTOOL_KEYCHAIN_PROFILE" --wait
  elif [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
    xcrun notarytool submit "$ZIP_PATH" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_SPECIFIC_PASSWORD" --wait
  else
    echo "Notarization credentials are missing" >&2
    exit 1
  fi
  xcrun stapler staple "$PACKAGED_APP"
  xcrun stapler validate "$PACKAGED_APP"
  create_zip
fi
(cd "$ARTIFACT_ROOT" && shasum -a 256 "$(basename "$ZIP_PATH")" > SHA256SUMS)
echo "$ZIP_PATH"
