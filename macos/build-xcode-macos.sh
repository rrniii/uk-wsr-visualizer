#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT_DIR/macos/UKWSRVisualizerMac.xcodeproj"
SCHEME="${SCHEME:-UKWSRVisualizerMac}"
CONFIGURATION="${CONFIGURATION:-Release}"
DERIVED_DATA="${DERIVED_DATA:-$ROOT_DIR/build/xcode-macos-derived}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$ROOT_DIR/build/xcode-macos}"
APP_NAME="UK WSR Visualizer.app"
BUILT_APP="$DERIVED_DATA/Build/Products/$CONFIGURATION/$APP_NAME"
PACKAGED_APP="$ARTIFACT_ROOT/$APP_NAME"
ZIP_PATH="$ARTIFACT_ROOT/UK WSR Visualizer macOS Xcode Beta.zip"
VERSION="$("$ROOT_DIR"/tools/project_version.py)"
GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || printf 'unknown')"

create_zip() {
  rm -f "$ZIP_PATH"
  ditto -c -k --keepParent "$PACKAGED_APP" "$ZIP_PATH"
}

echo "Building $SCHEME $CONFIGURATION with Xcode..."
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -derivedDataPath "$DERIVED_DATA" \
  MARKETING_VERSION="$VERSION" \
  CURRENT_PROJECT_VERSION="${BUILD_NUMBER:-1}" \
  CODE_SIGNING_ALLOWED="${CODE_SIGNING_ALLOWED:-NO}" \
  build

if [[ ! -d "$BUILT_APP" ]]; then
  echo "error: Xcode did not produce $BUILT_APP" >&2
  exit 1
fi

rm -rf "$ARTIFACT_ROOT"
mkdir -p "$ARTIFACT_ROOT"
cp -R "$BUILT_APP" "$PACKAGED_APP"

echo "Embedding app resources..."
mkdir -p "$PACKAGED_APP/Contents/Resources"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PACKAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${BUILD_NUMBER:-1}" "$PACKAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :UKWSRGitCommit string $GIT_COMMIT" "$PACKAGED_APP/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :UKWSRGitCommit $GIT_COMMIT" "$PACKAGED_APP/Contents/Info.plist"

rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv*/' \
  --exclude '.pytest_cache/' \
  --exclude 'data/' \
  --exclude 'build/' \
  --exclude 'dist/' \
  --exclude 'docs/_build/' \
  --exclude 'macos/UK WSR Visualizer.app/' \
  "$ROOT_DIR/" "$PACKAGED_APP/Contents/Resources/repo/"

chmod +x "$PACKAGED_APP/Contents/Resources/uk-wsr-visualizer-server.zsh"

if [[ -n "${DEVELOPER_ID_APPLICATION:-}" ]]; then
  echo "Signing with Developer ID identity: $DEVELOPER_ID_APPLICATION"
  codesign --force --deep --options runtime --sign "$DEVELOPER_ID_APPLICATION" "$PACKAGED_APP"
fi

echo "Creating $ZIP_PATH"
create_zip

if [[ "${NOTARIZE:-0}" == "1" ]]; then
  if [[ -z "${DEVELOPER_ID_APPLICATION:-}" ]]; then
    echo "error: NOTARIZE=1 requires DEVELOPER_ID_APPLICATION for a Developer ID signed app." >&2
    exit 1
  fi

  echo "Submitting $ZIP_PATH for Apple notarization..."
  if [[ -n "${NOTARYTOOL_KEYCHAIN_PROFILE:-}" ]]; then
    xcrun notarytool submit "$ZIP_PATH" \
      --keychain-profile "$NOTARYTOOL_KEYCHAIN_PROFILE" \
      --wait
  elif [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_APP_SPECIFIC_PASSWORD:-}" ]]; then
    xcrun notarytool submit "$ZIP_PATH" \
      --apple-id "$APPLE_ID" \
      --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_SPECIFIC_PASSWORD" \
      --wait
  else
    echo "error: NOTARIZE=1 requires NOTARYTOOL_KEYCHAIN_PROFILE or APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_SPECIFIC_PASSWORD." >&2
    exit 1
  fi

  echo "Stapling notarization ticket to $PACKAGED_APP"
  xcrun stapler staple "$PACKAGED_APP"

  echo "Recreating $ZIP_PATH with stapled app"
  create_zip
fi

echo "$ZIP_PATH"
