# UK WSR Visualizer Windows App

This folder defines the Windows beta packaging.

The Windows build is a portable zip. It contains:

```text
UK WSR Visualizer.exe
server/uk-wsr-visualizer-server.exe
resources/UKWSRVisualizer.png
README-Windows.txt
```

The desktop window is a small .NET WinForms app using Microsoft WebView2. It
starts the bundled Python/FastAPI server, waits for `/api/ready`, then loads the
local UI from `127.0.0.1`.

Runtime files are written outside the extracted zip:

```text
%LOCALAPPDATA%\UK WSR Visualizer\
%LOCALAPPDATA%\UK WSR Visualizer\data\
%LOCALAPPDATA%\UK WSR Visualizer\uk-wsr-visualizer.log
```

## Build

Run from the repository root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File windows\build.ps1
```

The build creates:

```text
build\windows-beta\UK WSR Visualizer Windows Beta.zip
```

Use `-SkipTests` only when iterating on local packaging:

```powershell
powershell -ExecutionPolicy Bypass -File windows\build.ps1 -SkipTests
```

## Build from macOS or Linux

Use GitHub Actions to create the Windows zip from a non-Windows machine:

```bash
windows/build-via-github.sh --ref master
```

The helper dispatches `.github/workflows/windows-beta.yml`, waits for the
Windows runner to finish, then downloads:

```text
build/windows-beta-artifacts/UK WSR Visualizer Windows Beta.zip
```

This is the supported route from macOS because PyInstaller does not
cross-compile Windows executables from macOS/Linux, and the WebView2 shell must
be built and self-tested on Windows. Commit and push your changes before running
the helper; GitHub Actions builds the pushed ref, not uncommitted local files.

## Self Test

After building, run:

```powershell
.\build\windows-beta\UK WSR Visualizer\UK WSR Visualizer.exe --self-test
```

The self-test starts the bundled server, waits for `/api/ready`, prints
`/api/status`, and shuts the server down without opening a visible app window.

## Beta workflow to test

The expected beta workflow is:

1. Search by date/date range.
2. Select an available radar, source item, variable, time, and elevation.
3. Plot a georeferenced single-site PPI.
4. Zoom, pan, and click a gate to inspect value and beam-height readout.
5. Create a PNG or metadata export from **Export & Provenance** and inspect the
   manifest.

Report bugs with the radar, date, variable, time, elevation, and the log file
from `%LOCALAPPDATA%\UK WSR Visualizer\uk-wsr-visualizer.log`.
