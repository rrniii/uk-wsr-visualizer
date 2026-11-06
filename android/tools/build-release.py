#!/usr/bin/env python3
"""Build and verify UK WSR APK/AAB artifacts without exposing signing secrets."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def run(*args: str, cwd: Path | None = None, env: dict | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, env=env, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signing-config", type=Path, required=True)
    parser.add_argument("--version-code", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    android = Path(__file__).resolve().parents[1]
    repo = android.parent
    if run("git", "status", "--porcelain", cwd=repo):
        raise SystemExit("Commit the complete release source before building signed artifacts.")
    revision = run("git", "rev-parse", "HEAD", cwd=repo)
    config = json.loads(args.signing_config.read_text())
    env = dict(os.environ)
    for key, suffix in [("store_file", "KEYSTORE"), ("store_password", "STORE_PASSWORD"),
                        ("key_alias", "KEY_ALIAS"), ("key_password", "KEY_PASSWORD")]:
        env["UKWSR_ANDROID_" + suffix] = str(config[key])
    env["UKWSR_GIT_SHA"] = revision
    env["UKWSR_ANDROID_VERSION_CODE"] = str(args.version_code)
    subprocess.run([str(android / "gradlew"), "lintRelease", "testReleaseUnitTest", "assembleRelease", "bundleRelease"], cwd=android, env=env, check=True)
    sdk_path = env.get("ANDROID_HOME") or env.get("ANDROID_SDK_ROOT")
    local_properties = android / "local.properties"
    if not sdk_path and local_properties.exists():
        sdk_path = next((line.split("=", 1)[1].strip()
                         for line in local_properties.read_text().splitlines()
                         if line.startswith("sdk.dir=")), None)
    if not sdk_path:
        raise SystemExit("Set ANDROID_HOME or sdk.dir in android/local.properties.")
    sdk = Path(sdk_path).expanduser()
    tools = sdk / "build-tools" / "36.0.0"
    apk = android / "app/build/outputs/apk/release/app-release.apk"
    aab = android / "app/build/outputs/bundle/release/app-release.aab"
    verify = run(str(tools / "apksigner"), "verify", "--verbose", "--print-certs", str(apk))
    alignment = run(str(tools / "zipalign"), "-c", "-P", "16", "-v", "4", str(apk))
    bundle_verify = run("jarsigner", "-verify", str(aab))
    if "jar verified." not in bundle_verify:
        raise SystemExit("The app bundle signature was not verified.")
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for source in [apk, aab]:
        target = output / f"UK-WSR-Visualizer-Android-0.1.0-{args.version_code}{source.suffix}"
        shutil.copy2(source, target)
        artifacts.append({"file": target.name, "bytes": target.stat().st_size,
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    metadata = {"version": "0.1.0", "version_code": args.version_code, "git_sha": revision,
                "package": "com.rrniii.ukwsrvisualizer", "abis": ["arm64-v8a", "x86_64"],
                "min_sdk": 29, "target_sdk": 36, "artifacts": artifacts,
                "apk_verification": verify, "zip_alignment": alignment,
                "bundle_verification": bundle_verify, "play_delivery": "not_uploaded"}
    (output / "android-build-manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "ANDROID-SHA256SUMS.txt").write_text("".join(f"{a['sha256']}  {a['file']}\n" for a in artifacts))
    print(json.dumps({"output": str(output), "git_sha": revision, "artifacts": artifacts}, indent=2))


if __name__ == "__main__":
    main()
