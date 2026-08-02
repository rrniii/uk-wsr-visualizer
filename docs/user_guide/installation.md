# Installation

UK WSR Visualizer is currently distributed as beta desktop packages and as
source. There is not yet a stable GitHub release or archived software DOI.

## Before installing a beta package

Use the package shared by the maintainer for your platform and verify it
against the accompanying SHA-256 checksum file. Keep the extracted package
together on Windows and Linux; do not move only the launcher executable.

Packaged desktop applications include the local Python server. Users do not
need a JASMIN account or a separate Python installation.

## macOS

1. Extract the macOS zip.
2. Move **UK WSR Visualizer.app** to **Applications**.
3. Open the app. If macOS blocks an unsigned beta, control-click the app,
   choose **Open**, and confirm that you trust the package source.
4. Leave the app open during its first setup. The logo remains visible until
   the private local server is ready.

Runtime files and the log are stored under:

~~~text
~/Library/Application Support/UK WSR Visualizer/
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
~~~

The supported developer build is Xcode-managed:

~~~bash
macos/build-xcode-macos.sh
~~~

Its archive is written below `build/xcode-macos/`.

## Windows 10 or 11, x64

1. Extract the entire portable zip.
2. Double-click **UK WSR Visualizer.exe**.
3. If Windows SmartScreen warns about the unsigned beta, check the package
   checksum and use **More info > Run anyway** only when it matches the trusted
   distribution.
4. Install the Microsoft Edge Evergreen WebView2 Runtime if the launcher says
   it is missing.

Runtime files and the log are stored under:

~~~text
%LOCALAPPDATA%\UK WSR Visualizer\
%LOCALAPPDATA%\UK WSR Visualizer\uk-wsr-visualizer.log
~~~

The Windows executable must be built on Windows. From macOS or Linux, a
maintainer can dispatch the tested GitHub Actions build from a pushed commit:

~~~bash
windows/build-via-github.sh --ref master
~~~

## Linux

The beta targets Ubuntu 22.04, Ubuntu 24.04, and Debian 12. Use either the
AppImage or the portable tarball.

AppImage:

~~~bash
chmod +x "UK WSR Visualizer Linux.AppImage"
./UK\ WSR\ Visualizer\ Linux.AppImage
~~~

Portable tarball:

~~~bash
tar -xzf "UK WSR Visualizer Linux portable.tar.gz"
cd "UK WSR Visualizer"
./UK\ WSR\ Visualizer
~~~

Runtime files follow XDG conventions:

~~~text
~/.cache/uk-wsr-visualizer/data/
~/.local/state/uk-wsr-visualizer/uk-wsr-visualizer.log
~~~

On a Rocky/RHEL, virtual-machine, NVIDIA, or Wayland system with a blank Qt
window, try:

~~~bash
./UK\ WSR\ Visualizer --software-rendering
~~~

See [Linux Install and Use](../linux_install_and_use.md) for self-test and
build details.

## Install from source

Python 3.11 or newer is required. The scientific cleanup implementation is a
separate package, so clone both repositories side by side. This route currently
requires collaborator access to `uk-wsr-qc`; packaged desktop users do not need
that repository access.

~~~bash
git clone git@github.com:rrniii/uk-wsr-qc.git
git clone git@github.com:rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ../uk-wsr-qc
python -m pip install -e ".[dev,export,video]"
uk-wsr-visualizer api --host 127.0.0.1 --port 8000
~~~

Open `http://127.0.0.1:8000`. This source route uses a browser window; the
packaged apps use their own native desktop windows.

Additional extras are:

| Extra | Purpose |
|---|---|
| `docs` | Sphinx documentation build |
| `object-store` | S3/JASMIN publication tools |
| `linux` | Qt and PyInstaller packaging |

## Build the documentation

~~~bash
python -m pip install -e ".[docs]"
python -m sphinx -W --keep-going -b html docs docs/_build/html
python -m http.server --directory docs/_build/html 8080
~~~

Open `http://127.0.0.1:8080`.
