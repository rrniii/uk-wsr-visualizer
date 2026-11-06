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
$Version = (python (Join-Path $RepoRoot "tools/project_version.py")).Trim()
$QcRoot = if ($env:UK_WSR_QC_ROOT) { $env:UK_WSR_QC_ROOT } else { Join-Path $RepoRoot "../uk-wsr-qc" }
$ZipPath = Join-Path $OutputRootPath "UK-WSR-Visualizer-$Version-Windows-x86_64-beta.zip"

Set-Location $RepoRoot

python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
python -m pip install "pyinstaller==6.22.0"
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
python -m pip install -e ".[dev,export,video]"
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }

if (-not $SkipTests) {
  python -m unittest tests.test_windows_app tests.test_static_viewer tests.test_remote_cache
  if ($LASTEXITCODE -ne 0) { throw "Packaging tests failed" }
}

python tools/build_frozen_server.py --qc-root $QcRoot
if ($LASTEXITCODE -ne 0) { throw "Server build failed" }

dotnet publish $ShellProject `
  -c $Configuration `
  -r win-x64 `
  --self-contained true `
  -o $ShellPublish `
  /p:Version=$Version `
  /p:AssemblyVersion="$Version.0" `
  /p:PublishSingleFile=true `
  /p:PublishTrimmed=false `
  /p:IncludeNativeLibrariesForSelfExtract=true `
  /p:EnableCompressionInSingleFile=true
if ($LASTEXITCODE -ne 0) { throw "Windows shell build failed" }

if (Test-Path $ReleaseDir) {
  Remove-Item $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseDir "server") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ReleaseDir "resources") | Out-Null

Copy-Item (Join-Path $ShellPublish "UKWSRVisualizer.Windows.exe") (Join-Path $ReleaseDir "UK WSR Visualizer.exe")
Copy-Item (Join-Path $ServerDist "*") (Join-Path $ReleaseDir "server") -Recurse
Copy-Item (Join-Path $RepoRoot "docs/_static/uk-wsr-visualizer-logo.png") (Join-Path $ReleaseDir "resources/UKWSRVisualizer.png")
Copy-Item (Join-Path $ServerDist "build-info.json") (Join-Path $ReleaseDir "build-info.json")
Copy-Item (Join-Path $PSScriptRoot "README-Windows.txt") (Join-Path $ReleaseDir "README-Windows.txt")

if (Test-Path $ZipPath) {
  Remove-Item $ZipPath -Force
}
Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath -Force


$Hash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLower()
"$Hash  $(Split-Path $ZipPath -Leaf)" | Set-Content (Join-Path $OutputRootPath "SHA256SUMS")
Write-Host "Created $ZipPath"
