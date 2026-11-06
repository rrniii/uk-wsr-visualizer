#!/usr/bin/env bash
set -euo pipefail

OUTPUT_ROOT="build/linux-beta"
SKIP_TESTS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_ROOT_PATH="$REPO_ROOT/$OUTPUT_ROOT"
RELEASE_DIR="$OUTPUT_ROOT_PATH/UK WSR Visualizer"
SERVER_DIST="$REPO_ROOT/dist/uk-wsr-visualizer-server"
SHELL_DIST="$REPO_ROOT/dist/UK WSR Visualizer"
VERSION="$(python "$REPO_ROOT/tools/project_version.py")"
QC_ROOT="${UK_WSR_QC_ROOT:-$REPO_ROOT/../uk-wsr-qc}"
PACKAGE_PLATFORM="${PACKAGE_PLATFORM:-Linux-x86_64}"
TARBALL_PATH="$OUTPUT_ROOT_PATH/UK-WSR-Visualizer-$VERSION-$PACKAGE_PLATFORM-portable.tar.gz"
APPDIR="$OUTPUT_ROOT_PATH/UKWSRVisualizer.AppDir"
APPIMAGE_PATH="$OUTPUT_ROOT_PATH/UK-WSR-Visualizer-$VERSION-$PACKAGE_PLATFORM.AppImage"

cd "$REPO_ROOT"

python -m pip install --upgrade pip
python -m pip install "pyinstaller==6.22.0"
python -m pip install -e ".[dev,export,video,linux]"

if [ "$SKIP_TESTS" -eq 0 ]; then
  python -m unittest tests.test_linux_app tests.test_static_viewer tests.test_remote_cache
fi

python tools/build_frozen_server.py --qc-root "$QC_ROOT"

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name "UK WSR Visualizer" \
  --collect-all PySide6 \
  --hidden-import PySide6.QtWebEngineWidgets \
  linux/UKWSRVisualizer.Qt/uk_wsr_visualizer_qt.py

rm -rf "$RELEASE_DIR" "$APPDIR"
mkdir -p "$RELEASE_DIR/server" "$RELEASE_DIR/resources"
cp -R "$SHELL_DIST"/. "$RELEASE_DIR"/
cp -R "$SERVER_DIST"/. "$RELEASE_DIR/server"/
cp "$REPO_ROOT/docs/_static/uk-wsr-visualizer-logo.png" "$RELEASE_DIR/resources/UKWSRVisualizer.png"
cp "$SERVER_DIST/build-info.json" "$RELEASE_DIR/build-info.json"
cp "$REPO_ROOT/linux/README-Linux.txt" "$RELEASE_DIR/README-Linux.txt"

rm -f "$TARBALL_PATH"
mkdir -p "$OUTPUT_ROOT_PATH"
tar -C "$OUTPUT_ROOT_PATH" -czf "$TARBALL_PATH" "UK WSR Visualizer"

mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -R "$RELEASE_DIR"/. "$APPDIR/usr/bin"/
cp "$REPO_ROOT/docs/_static/uk-wsr-visualizer-logo.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/uk-wsr-visualizer.png"
cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/UK WSR Visualizer" "$@"
EOF
chmod +x "$APPDIR/AppRun"
cat > "$APPDIR/usr/share/applications/uk-wsr-visualizer.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=UK WSR Visualizer
Exec=UK WSR Visualizer
Icon=uk-wsr-visualizer
Categories=Science;Education;
Comment=Quick-look viewer for UK weather surveillance radar data
EOF
cp "$APPDIR/usr/share/applications/uk-wsr-visualizer.desktop" "$APPDIR/uk-wsr-visualizer.desktop"
cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/uk-wsr-visualizer.png" "$APPDIR/uk-wsr-visualizer.png"

APPIMAGETOOL_BIN="${APPIMAGETOOL:-}"
if [ -z "$APPIMAGETOOL_BIN" ] && command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL_BIN="$(command -v appimagetool)"
fi
if [ -n "$APPIMAGETOOL_BIN" ] && [ -x "$APPIMAGETOOL_BIN" ]; then
  rm -f "$APPIMAGE_PATH"
  ARCH=x86_64 "$APPIMAGETOOL_BIN" "$APPDIR" "$APPIMAGE_PATH"
  echo "Created $APPIMAGE_PATH"
else
  echo "appimagetool not found; created AppDir but skipped AppImage." >&2
fi

(cd "$OUTPUT_ROOT_PATH" && sha256sum "$(basename "$TARBALL_PATH")" > SHA256SUMS)
if [[ -f "$APPIMAGE_PATH" ]]; then
  (cd "$OUTPUT_ROOT_PATH" && sha256sum "$(basename "$APPIMAGE_PATH")" >> SHA256SUMS)
fi
echo "Created $TARBALL_PATH"
