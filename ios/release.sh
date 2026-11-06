#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-help}"
PROJECT="$ROOT_DIR/ios/UKWSRVisualizer.xcodeproj"
RELEASE_DIR="${IOS_RELEASE_DIR:-$ROOT_DIR/build/ios-release}"
ARCHIVE_PATH="${IOS_ARCHIVE_PATH:-$RELEASE_DIR/UKWSRVisualizer.xcarchive}"
TEAM_ID="${TEAM_ID:-D863HTPFQC}"

case "$ACTION" in
  help|--help|-h)
    cat <<'USAGE'
Usage: ios/release.sh check|archive|archive-unsigned|export|upload

check    Build Release for a generic iOS device without signing.
archive  Create a signed Release archive using the configured Xcode account.
archive-unsigned  Create a Release archive without signing, for build handoff.
export   Export an existing archive as an App Store Connect IPA.
upload   Upload an existing archive to App Store Connect for TestFlight processing.

Optional environment:
  IOS_BUILD_NUMBER, IOS_MARKETING_VERSION  Explicit archive version overrides.
  IOS_RELEASE_DIR, IOS_ARCHIVE_PATH        Output locations.
  TEAM_ID                                Existing Apple Developer team.
  ASC_KEY_PATH, ASC_KEY_ID, ASC_ISSUER_ID   App Store Connect API-key authentication.

Build numbers are never changed automatically. Upload success does not prove
TestFlight processing or tester availability; verify those in App Store Connect.
USAGE
    exit 0
    ;;
  check|archive|archive-unsigned|export|upload) ;;
  *) echo "Unknown action: $ACTION" >&2; exit 2 ;;
esac

AUTH_ARGS=(-allowProvisioningUpdates)
if [[ -n "${ASC_KEY_PATH:-}${ASC_KEY_ID:-}${ASC_ISSUER_ID:-}" ]]; then
  : "${ASC_KEY_PATH:?Set all three ASC authentication variables}"
  : "${ASC_KEY_ID:?Set all three ASC authentication variables}"
  : "${ASC_ISSUER_ID:?Set all three ASC authentication variables}"
  [[ -f "$ASC_KEY_PATH" ]] || { echo "ASC_KEY_PATH does not exist" >&2; exit 2; }
  AUTH_ARGS+=(-authenticationKeyPath "$ASC_KEY_PATH" -authenticationKeyID "$ASC_KEY_ID" -authenticationKeyIssuerID "$ASC_ISSUER_ID")
fi

VERSION_ARGS=(ENABLE_DEBUG_DYLIB=NO)
if [[ -n "${IOS_BUILD_NUMBER:-}" ]]; then
  [[ "$IOS_BUILD_NUMBER" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || { echo "Invalid IOS_BUILD_NUMBER" >&2; exit 2; }
  VERSION_ARGS+=("CURRENT_PROJECT_VERSION=$IOS_BUILD_NUMBER")
fi
if [[ -n "${IOS_MARKETING_VERSION:-}" ]]; then
  [[ "$IOS_MARKETING_VERSION" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "Invalid IOS_MARKETING_VERSION" >&2; exit 2; }
  VERSION_ARGS+=("MARKETING_VERSION=$IOS_MARKETING_VERSION")
fi

mkdir -p "$RELEASE_DIR"
if [[ "$ACTION" == check ]]; then
  xcodebuild -project "$PROJECT" -scheme UKWSRVisualizer -configuration Release \
    -destination 'generic/platform=iOS' -derivedDataPath "$RELEASE_DIR/DerivedData" \
    CODE_SIGNING_ALLOWED=NO "${VERSION_ARGS[@]}" build
  exit 0
fi

if [[ "$ACTION" == archive || "$ACTION" == archive-unsigned ]]; then
  [[ ! -e "$ARCHIVE_PATH" ]] || { echo "Archive already exists; choose a new IOS_ARCHIVE_PATH" >&2; exit 2; }
  BUILD_ARGS=(-project "$PROJECT" -scheme UKWSRVisualizer -configuration Release
    -destination 'generic/platform=iOS' -archivePath "$ARCHIVE_PATH"
    -derivedDataPath "$RELEASE_DIR/DerivedData")
  if [[ "$ACTION" == archive ]]; then
    BUILD_ARGS+=("${AUTH_ARGS[@]}" "DEVELOPMENT_TEAM=$TEAM_ID" CODE_SIGN_STYLE=Automatic)
  else
    BUILD_ARGS+=(CODE_SIGNING_ALLOWED=NO)
  fi
  xcodebuild "${BUILD_ARGS[@]}" "${VERSION_ARGS[@]}" archive
else
  [[ -f "$ARCHIVE_PATH/Info.plist" ]] || { echo "No archive at $ARCHIVE_PATH" >&2; exit 2; }
  OPTIONS_PATH="$RELEASE_DIR/ExportOptions-$ACTION.plist"
  python3 - "$OPTIONS_PATH" "$ACTION" "$TEAM_ID" <<'PY'
import plistlib, sys
path, action, team = sys.argv[1:]
options = {
    "method": "app-store-connect",
    "destination": "upload" if action == "upload" else "export",
    "teamID": team,
    "signingStyle": "automatic",
    "manageAppVersionAndBuildNumber": False,
    "uploadSymbols": True,
}
with open(path, "wb") as stream:
    plistlib.dump(options, stream)
PY
  xcodebuild -exportArchive -archivePath "$ARCHIVE_PATH" \
    -exportPath "$RELEASE_DIR/$ACTION" -exportOptionsPlist "$OPTIONS_PATH" \
    "${AUTH_ARGS[@]}"
fi

python3 - "$ROOT_DIR" "$ARCHIVE_PATH" "$RELEASE_DIR" "$ACTION" <<'PY'
import datetime, hashlib, json, pathlib, plistlib, subprocess, sys
root, archive, destination, action = map(pathlib.Path, sys.argv[1:])
with (archive / "Info.plist").open("rb") as stream:
    info = plistlib.load(stream)
app_info = info["ApplicationProperties"]
app = archive / "Products" / app_info["ApplicationPath"]
with (app / "Info.plist").open("rb") as stream:
    bundle = plistlib.load(stream)
identity_path = archive / "UKWSRBuildIdentity.json"
if str(action) in {"archive", "archive-unsigned"}:
    files = subprocess.check_output([
        "git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z", "--",
        "ios", "shared/native", "validation/candidate8_parity_fixtures.json",
        "validation/candidate8_all_model_parity.json",
    ]).split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, files))):
        path = root / name.decode()
        if path.is_file():
            digest.update(name + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    identity = {
        "git_commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip()),
        "source_tree_sha256": digest.hexdigest(),
        "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True).strip(),
    }
    identity_path.write_text(json.dumps(identity, indent=2) + "\n")
else:
    identity = json.loads(identity_path.read_text()) if identity_path.is_file() else {}
record = {
    "action": str(action),
    "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "archive": str(archive),
    "bundle_id": bundle["CFBundleIdentifier"],
    "version": bundle["CFBundleShortVersionString"],
    "build": bundle["CFBundleVersion"],
    "signature_verified": subprocess.run(["codesign", "--verify", "--strict", "--deep", str(app)], capture_output=True).returncode == 0,
    "build_identity": identity,
    "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True).strip(),
    "ipa_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (destination / action).glob("*.ipa")},
}
if str(action) == "upload":
    record["testflight_processing_verified"] = False
(destination / f"{action}-result.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
PY
