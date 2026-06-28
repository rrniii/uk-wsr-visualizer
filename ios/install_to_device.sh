#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT="${PROJECT:-$ROOT_DIR/ios/UKWSRVisualizer.xcodeproj}"
SCHEME="${SCHEME:-UKWSRVisualizer}"
CONFIGURATION="${CONFIGURATION:-Debug}"
DEVICE_ID="${DEVICE_ID:-00008140-000160A43A38801C}"
BUNDLE_ID="${BUNDLE_ID:-com.rrniii.ukwsrvisualizer}"
TEAM_ID="${TEAM_ID:-D863HTPFQC}"
SIGNING_IDENTITY="${SIGNING_IDENTITY:-}"
DERIVED_DATA="${DERIVED_DATA:-/tmp/ukwsr-ios-install-derived}"

BUILD_DIR="$DERIVED_DATA/Build/Products/${CONFIGURATION}-iphoneos"
APP="$BUILD_DIR/UKWSRVisualizer.app"
PROFILE_ROOT="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ukwsr-ios-install.XXXXXX")"
PROFILE_PLIST="$TMP_DIR/profile.plist"
ENTITLEMENTS="$TMP_DIR/entitlements.plist"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

find_profile() {
  local profile
  local app_identifier
  local team_identifier

  [[ -d "$PROFILE_ROOT" ]] || return 1

  while IFS= read -r profile; do
    if ! security cms -D -i "$profile" -o "$PROFILE_PLIST" >/dev/null 2>&1; then
      continue
    fi

    app_identifier="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' "$PROFILE_PLIST" 2>/dev/null || true)"
    team_identifier="$(/usr/libexec/PlistBuddy -c 'Print :TeamIdentifier:0' "$PROFILE_PLIST" 2>/dev/null || true)"

    if [[ "$team_identifier" != "$TEAM_ID" || "$app_identifier" != "$TEAM_ID.$BUNDLE_ID" ]]; then
      continue
    fi

    if /usr/libexec/PlistBuddy -c 'Print :ProvisionedDevices' "$PROFILE_PLIST" 2>/dev/null | grep -q "$DEVICE_ID"; then
      printf '%s\n' "$profile"
      return 0
    fi
  done < <(find "$PROFILE_ROOT" -maxdepth 1 -name '*.mobileprovision' -print)

  return 1
}

profile_certificate_fingerprints() {
  local index=0
  local cert_b64
  local cert_der
  local fingerprint

  while true; do
    cert_b64="$TMP_DIR/profile-cert-$index.b64"
    cert_der="$TMP_DIR/profile-cert-$index.der"
    if ! plutil -extract "DeveloperCertificates.$index" raw -o "$cert_b64" "$PROFILE_PLIST" >/dev/null 2>&1; then
      break
    fi
    if base64 -D -i "$cert_b64" -o "$cert_der" >/dev/null 2>&1; then
      fingerprint="$(openssl x509 -inform DER -in "$cert_der" -noout -fingerprint -sha1 2>/dev/null | awk -F= '{print $2}' | tr -d ':' | tr '[:lower:]' '[:upper:]')"
      if [[ -n "$fingerprint" ]]; then
        printf '%s\n' "$fingerprint"
      fi
    fi
    index=$((index + 1))
  done
}

find_signing_identity_for_profile() {
  local profile_fingerprint
  local identity

  while IFS= read -r profile_fingerprint; do
    while IFS= read -r identity; do
      if [[ "$identity" == "$profile_fingerprint" ]]; then
        printf '%s\n' "$identity"
        return 0
      fi
    done < <(security find-identity -v -p codesigning | sed -n 's/^[[:space:]]*[0-9]*) \([A-F0-9]\{40\}\) .*/\1/p')
  done < <(profile_certificate_fingerprints)

  return 1
}

echo "Building $SCHEME for iOS..."
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$DERIVED_DATA" \
  CODE_SIGNING_ALLOWED=NO \
  ENABLE_DEBUG_DYLIB=NO \
  build

if [[ ! -d "$APP" ]]; then
  echo "error: build did not produce $APP" >&2
  exit 1
fi

PROFILE="$(find_profile || true)"
if [[ -z "${PROFILE:-}" ]]; then
  echo "error: no Xcode-managed provisioning profile found for $TEAM_ID.$BUNDLE_ID and device $DEVICE_ID" >&2
  echo "Open Xcode once, select the UKWSRVisualizer target, set the Signing team, and let Xcode create the profile." >&2
  exit 1
fi

security cms -D -i "$PROFILE" -o "$PROFILE_PLIST" >/dev/null
/usr/libexec/PlistBuddy -x -c 'Print :Entitlements' "$PROFILE_PLIST" > "$ENTITLEMENTS"

if [[ -z "$SIGNING_IDENTITY" ]]; then
  SIGNING_IDENTITY="$(find_signing_identity_for_profile || true)"
fi
if [[ -z "$SIGNING_IDENTITY" ]]; then
  echo "error: no local Apple Development signing identity matches $PROFILE" >&2
  echo "Open Xcode, select the UKWSRVisualizer target, and refresh Signing & Capabilities." >&2
  exit 1
fi

echo "Signing with $SIGNING_IDENTITY..."
echo "If macOS asks for keychain access, choose Allow or Always Allow for codesign."
rm -f "$APP/UKWSRVisualizer.cstemp"
rm -rf "$APP/_CodeSignature"
cp "$PROFILE" "$APP/embedded.mobileprovision"
/usr/bin/codesign \
  --force \
  --sign "$SIGNING_IDENTITY" \
  --entitlements "$ENTITLEMENTS" \
  --timestamp=none \
  "$APP"
/usr/bin/codesign -vvv "$APP"

VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Info.plist")"
BUILD="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Info.plist")"

echo "Installing $BUNDLE_ID version $VERSION build $BUILD to $DEVICE_ID..."
xcrun devicectl device install app --device "$DEVICE_ID" "$APP"

echo "Installed app metadata:"
xcrun devicectl device info apps --device "$DEVICE_ID" | grep -E "Bundle Identifier|$BUNDLE_ID|^Name"
