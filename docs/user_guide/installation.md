# Installation

UK WSR Visualizer requires Python 3.11 or newer.

## Developer installation

Create an isolated environment and install the project in editable mode:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store]"
```

The extras enable the common development and operational workflows:

- `dev`: test dependencies.
- `export`: GeoTIFF, CF NetCDF, and Shapefile export dependencies.
- `object-store`: JASMIN/S3 publication dependencies.
- `docs`: Sphinx, PyData Sphinx Theme, and documentation extensions.

For documentation work, install:

```bash
pip install -e ".[docs]"
```

or combine it with the development extras:

```bash
pip install -e ".[dev,export,object-store,docs]"
```

## macOS app bundle

The repository includes a lightweight local app bundle:

```text
macos/UK WSR Visualizer.app
```

On first launch, the app creates a Python virtual environment and installs the bundled checkout into:

```text
~/Library/Application Support/UK WSR Visualizer/
```

Application logs are written to:

```text
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
```

The app starts the local API and opens the browser UI at:

```text
http://127.0.0.1:8765
```

The packaged app opens this UI in its own native macOS window rather than the
default browser.

### Xcode-built macOS beta

The newer Mac packaging path is Xcode-managed. Developers can build it with:

```bash
macos/build-xcode-macos.sh
```

The output zip is written to:

```text
build/xcode-macos/UK WSR Visualizer macOS Xcode Beta.zip
```

This app uses the same Python/FastAPI viewer and object-store-backed cache as
the legacy bundle, but Xcode manages the native window, splash screen, app
menus, version metadata, and future signing/notarization workflow.

## Windows beta zip

The Windows beta is distributed as a portable zip from the GitHub Actions
Windows artifact or a tagged release artifact when available. After extracting
the zip, double-click:

```text
UK WSR Visualizer.exe
```

The Windows app opens its own WebView2 window and starts a bundled local Python
server. It does not require a system Python installation.

Runtime files are written under:

```text
%LOCALAPPDATA%\UK WSR Visualizer\
%LOCALAPPDATA%\UK WSR Visualizer\data\
%LOCALAPPDATA%\UK WSR Visualizer\uk-wsr-visualizer.log
```

If the app reports that WebView2 is missing, install the Microsoft Edge
Evergreen WebView2 Runtime and start the app again.

### Creating the Windows beta zip from macOS

The Windows zip should be built on a Windows runner. From macOS or Linux, use
the GitHub Actions helper after committing and pushing the desired ref:

```bash
windows/build-via-github.sh --ref master
```

The helper dispatches the Windows workflow, waits for the packaged self-test,
and downloads the artifact into:

```text
build/windows-beta-artifacts/
```

This avoids pretending to cross-compile the Windows executable locally.

## Linux Qt beta

The Linux beta is distributed as an AppImage plus a portable tarball. It targets
Ubuntu 22.04, Ubuntu 24.04, and Debian 12. The app opens its own Qt window,
starts the bundled local server, and uses the same public PVOL catalog as the
Mac and Windows apps.

AppImage:

```bash
chmod +x "UK WSR Visualizer Linux.AppImage"
./UK\ WSR\ Visualizer\ Linux.AppImage
```

Portable tarball:

```bash
tar -xzf "UK WSR Visualizer Linux portable.tar.gz"
cd "UK WSR Visualizer"
./UK\ WSR\ Visualizer
```

Runtime cache and logs follow the XDG conventions:

```text
~/.cache/uk-wsr-visualizer/data
~/.local/state/uk-wsr-visualizer/uk-wsr-visualizer.log
```

More detail is in [Linux Install And Use](../linux_install_and_use.md).

## Build the documentation locally

```bash
pip install -e ".[docs]"
sphinx-build -b html docs docs/_build/html
python -m http.server --directory docs/_build/html 8080
```

Open `http://127.0.0.1:8080` in a browser.
