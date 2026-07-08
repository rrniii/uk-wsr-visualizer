# UK WSR Visualizer Linux App

This folder defines the Linux Qt beta packaging.

The Linux build creates:

```text
UK WSR Visualizer Linux.AppImage
UK WSR Visualizer Linux portable.tar.gz
```

The desktop window is a small Qt WebEngine app using PySide6. It starts the
bundled Python/FastAPI server, waits for `/api/ready`, then loads the local UI
from `127.0.0.1`.

Runtime files are written outside the extracted app:

```text
$XDG_CACHE_HOME/uk-wsr-visualizer/data
~/.cache/uk-wsr-visualizer/data
$XDG_STATE_HOME/uk-wsr-visualizer/uk-wsr-visualizer.log
~/.local/state/uk-wsr-visualizer/uk-wsr-visualizer.log
```

## Build

Run from the repository root on Linux:

```bash
linux/build.sh
```

The build creates:

```text
build/linux-beta/UK WSR Visualizer Linux portable.tar.gz
build/linux-beta/UK WSR Visualizer Linux.AppImage
```

If `appimagetool` is not available, the script still creates the portable
tarball and an AppDir staging tree.

## Self Test

After building, run:

```bash
./build/linux-beta/UK\ WSR\ Visualizer/UK\ WSR\ Visualizer --self-test
```

The self-test starts the bundled server, waits for `/api/ready`, prints
`/api/status`, and shuts the server down without opening a visible app window.

## Beta workflow to test

The expected beta workflow is the same as Mac and Windows:

1. Search by date/date range.
2. Select an available radar, source item, variable, time, and elevation.
3. Plot a georeferenced single-site PPI.
4. Zoom, pan, animate, and click a gate to inspect the readout.
5. Create screenshot, polar PPI, georeferenced map, metadata, or raw-source
   exports from **Export & Provenance**.
