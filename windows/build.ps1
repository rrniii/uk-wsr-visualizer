param(
  [string]$Configuration = "Release",
  [string]$OutputRoot = "build/windows-beta",
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$OutputRootPath = Join-Path $RepoRoot $OutputRoot
$ReleaseDir = Join-Path $OutputRootPath "UK WSR Visualizer"
$ServerDist = Join-Path $RepoRoot "dist/uk-wsr-visualizer-server"
$ShellProject = Join-Path $PSScriptRoot "UKWSRVisualizer.Windows/UKWSRVisualizer.Windows.csproj"
$ShellPublish = Join-Path $RepoRoot "build/windows-shell-publish"
$ZipPath = Join-Path $OutputRootPath "UK WSR Visualizer Windows Beta.zip"

Set-Location $RepoRoot

python -m pip install --upgrade pip
python -m pip install --upgrade pyinstaller
python -m pip install -e ".[dev,video]"

if (-not $SkipTests) {
  python -m unittest tests.test_windows_app tests.test_static_viewer tests.test_remote_cache
}

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --name uk-wsr-visualizer-server `
  --collect-data uk_wsr_visualizer `
  --hidden-import h5py `
  --hidden-import imageio_ffmpeg `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import PIL._tkinter_finder `
  windows/pyinstaller/uk_wsr_visualizer_server.py

dotnet publish $ShellProject `
  -c $Configuration `
  -r win-x64 `
  --self-contained true `
  -o $ShellPublish `
  /p:PublishSingleFile=true `
  /p:PublishTrimmed=false `
  /p:IncludeNativeLibrariesForSelfExtract=true `
  /p:EnableCompressionInSingleFile=true

if (Test-Path $ReleaseDir) {
  Remove-Item $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseDir "server") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseDir "resources") | Out-Null

Copy-Item (Join-Path $ShellPublish "UKWSRVisualizer.Windows.exe") (Join-Path $ReleaseDir "UK WSR Visualizer.exe")
Copy-Item (Join-Path $ServerDist "*") (Join-Path $ReleaseDir "server") -Recurse
Copy-Item (Join-Path $RepoRoot "docs/_static/uk-wsr-visualizer-logo.png") (Join-Path $ReleaseDir "resources/UKWSRVisualizer.png")
Copy-Item (Join-Path $PSScriptRoot "README-Windows.txt") (Join-Path $ReleaseDir "README-Windows.txt")

if (Test-Path $ZipPath) {
  Remove-Item $ZipPath -Force
}
Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath -Force

Write-Host "Created $ZipPath"
