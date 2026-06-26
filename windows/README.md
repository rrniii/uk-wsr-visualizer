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

## Self Test

After building, run:

```powershell
.\build\windows-beta\UK WSR Visualizer\UK WSR Visualizer.exe --self-test
```

The self-test starts the bundled server, waits for `/api/ready`, prints
`/api/status`, and shuts the server down without opening a visible app window.
