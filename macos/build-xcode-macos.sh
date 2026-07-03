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
FINAL_APP="$ARTIFACT_ROOT/$APP_NAME"
ZIP_PATH="$ARTIFACT_ROOT/UK WSR Visualizer macOS Xcode Beta.zip"
PACKAGING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/uk-wsr-visualizer-macos.XXXXXX")"
PACKAGED_APP="$PACKAGING_ROOT/$APP_NAME"
VERSION="$("$ROOT_DIR"/tools/project_version.py)"
GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || printf 'unknown')"

cleanup() {
  rm -rf "$PACKAGING_ROOT"
}
trap cleanup EXIT

create_zip() {
  rm -f "$ZIP_PATH"
  clean_extended_attributes "$PACKAGED_APP"
  ditto -c -k --norsrc --keepParent "$PACKAGED_APP" "$ZIP_PATH"
}

clean_extended_attributes() {
  local target="$1"
  xattr -cr "$target" 2>/dev/null || true
  find "$target" -print0 | xargs -0 -n 1 xattr -d com.apple.FinderInfo 2>/dev/null || true
  find "$target" -print0 | xargs -0 -n 1 xattr -d com.apple.ResourceFork 2>/dev/null || true
  find "$target" -print0 | xargs -0 -n 1 xattr -d 'com.apple.fileprovider.fpfs#P' 2>/dev/null || true
  find "$target" -print0 | xargs -0 -n 1 xattr -d com.apple.macl 2>/dev/null || true
  for _ in 1 2 3; do
    xattr -d com.apple.FinderInfo "$target" 2>/dev/null || true
    xattr -d com.apple.ResourceFork "$target" 2>/dev/null || true
    xattr -d 'com.apple.fileprovider.fpfs#P' "$target" 2>/dev/null || true
    xattr -d com.apple.macl "$target" 2>/dev/null || true
    if ! xattr "$target" 2>/dev/null | grep -Eq 'com\\.apple\\.(FinderInfo|ResourceFork|macl|fileprovider\\.fpfs#P)'; then
      break
    fi
    sleep 0.1
  done
}

sign_packaged_app() {
  if [[ -n "${DEVELOPER_ID_APPLICATION:-}" ]]; then
    echo "Signing with Developer ID identity: $DEVELOPER_ID_APPLICATION"
    codesign --force --deep --options runtime --sign "$DEVELOPER_ID_APPLICATION" "$PACKAGED_APP"
  else
    echo "Ad-hoc signing beta app"
    codesign --force --deep --sign - "$PACKAGED_APP"
  fi
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
mkdir -p "$PACKAGING_ROOT"
ditto --norsrc "$BUILT_APP" "$PACKAGED_APP"

echo "Embedding app resources..."
mkdir -p "$PACKAGED_APP/Contents/Resources"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PACKAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${BUILD_NUMBER:-1}" "$PACKAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :UKWSRGitCommit string $GIT_COMMIT" "$PACKAGED_APP/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :UKWSRGitCommit $GIT_COMMIT" "$PACKAGED_APP/Contents/Info.plist"

rm -rf "$PACKAGED_APP/Contents/Resources/repo"
mkdir -p "$PACKAGED_APP/Contents/Resources/repo/src"
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.py[co]' \
  "$ROOT_DIR/src/" "$PACKAGED_APP/Contents/Resources/repo/src/"
for metadata_file in README.md pyproject.toml LICENSE CITATION.cff CITATION.md; do
  if [[ -f "$ROOT_DIR/$metadata_file" ]]; then
    cp "$ROOT_DIR/$metadata_file" "$PACKAGED_APP/Contents/Resources/repo/"
  fi
done

chmod +x "$PACKAGED_APP/Contents/Resources/uk-wsr-visualizer-server.zsh"
find "$PACKAGED_APP" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$PACKAGED_APP" \( -name '*.pyc' -o -name '*.pyo' \) -type f -delete
clean_extended_attributes "$PACKAGED_APP"

if ! sign_packaged_app; then
  echo "Initial signing failed; stripping extended attributes and retrying..." >&2
  clean_extended_attributes "$PACKAGED_APP"
  sign_packaged_app
fi

echo "Creating $ZIP_PATH"
create_zip
rm -rf "$FINAL_APP"
ditto --norsrc "$PACKAGED_APP" "$FINAL_APP"
clean_extended_attributes "$FINAL_APP"

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
  rm -rf "$FINAL_APP"
  ditto --norsrc "$PACKAGED_APP" "$FINAL_APP"
  clean_extended_attributes "$FINAL_APP"
fi

echo "$ZIP_PATH"
