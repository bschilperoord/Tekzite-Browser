$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== Tekzite Browser UltraSpeed Windows build ==" -ForegroundColor Cyan

# Keep source/release trees free of interpreter/test caches.
Get-ChildItem -Path $PSScriptRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -in @("__pycache__", ".pytest_cache") } |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $PSScriptRoot -File -Recurse -Force -Filter "*.pyc" -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue

python -m pip install --only-binary=:all: --require-hashes -r requirements-windows.lock
python -m pip install --only-binary=:all: --require-hashes -r requirements-build-windows.lock

function Invoke-TekziteSign([string]$Path) {
    $thumbprint = [string]$env:TEKZITE_SIGN_CERT_SHA1
    if ([string]::IsNullOrWhiteSpace($thumbprint)) {
        return $false
    }
    $signtool = (Get-Command signtool.exe -ErrorAction Stop).Source
    $timestamp = [string]$env:TEKZITE_SIGN_TIMESTAMP_URL
    if ([string]::IsNullOrWhiteSpace($timestamp)) {
        $timestamp = "http://timestamp.digicert.com"
    }
    & $signtool sign /sha1 $thumbprint /fd SHA256 /tr $timestamp /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed for $Path"
    }
    return $true
}

$helperWork = Join-Path $PSScriptRoot "build\network-work"
$helperDist = Join-Path $PSScriptRoot "build\network-dist"
$helperSpec = Join-Path $PSScriptRoot "build\network-spec"
$browserSpecDir = Join-Path $PSScriptRoot "build\browser-spec"

Remove-Item $helperWork -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $helperDist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $helperSpec -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $browserSpecDir -Recurse -Force -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force -Path $helperSpec | Out-Null
New-Item -ItemType Directory -Force -Path $browserSpecDir | Out-Null

Write-Host "Building low-latency Tekzite network helper..." -ForegroundColor Yellow
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --optimize 1 `
  --name "tekzite-network" `
  --distpath $helperDist `
  --workpath $helperWork `
  --specpath $helperSpec `
  --exclude-module numpy `
  --exclude-module pygame `
  --exclude-module pytest `
  tekzite_network_fast.py

$helperExe = Join-Path $helperDist "tekzite-network.exe"
if (-not (Test-Path $helperExe)) {
    throw "Network helper build completed without expected executable: $helperExe"
}
$helperSigned = Invoke-TekziteSign $helperExe
Copy-Item $helperExe (Join-Path $PSScriptRoot "tekzite-network.exe") -Force

Write-Host "Generating optimized OneFile spec..." -ForegroundColor Yellow
$browserSpec = Join-Path $browserSpecDir "TekziteBrowser-UltraSpeed.spec"

@'
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

# Spec lives in <repo>\build\browser-spec.
project = Path(SPECPATH).resolve().parents[1]

helper = project / "tekzite-network.exe"
if not helper.is_file():
    raise SystemExit("tekzite-network.exe is missing")

extension_dir = project / "chromium_zoom_extension"
datas = []
if extension_dir.is_dir():
    datas.append((str(extension_dir), "chromium_zoom_extension"))

icon_candidate = project / "assets" / "tekzite.ico"
icon_path = str(icon_candidate) if icon_candidate.is_file() else None

version_candidate = project / "tekzite_version_info.txt"
version_path = str(version_candidate) if version_candidate.is_file() else None

manifest_candidate = project / "tekzite_browser.manifest"
manifest_path = str(manifest_candidate) if manifest_candidate.is_file() else None

analysis = Analysis(
    [str(project / "ultraspeed_launcher.py")],
    pathex=[str(project)],
    binaries=[(str(helper), ".")],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "numpy",
        "pygame",
        "matplotlib",
        "pandas",
        "scipy",
        "IPython",
        "psutil",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="TekziteBrowser",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    version=version_path,
    manifest=manifest_path,
)
'@ | Set-Content $browserSpec -Encoding UTF8

Write-Host "Building Tekzite Browser UltraSpeed..." -ForegroundColor Yellow
python -m PyInstaller --noconfirm --clean $browserSpec

$exe = Join-Path $PSScriptRoot "dist\TekziteBrowser.exe"
if (-not (Test-Path $exe)) {
    throw "Build completed without expected executable: $exe"
}
$browserSigned = Invoke-TekziteSign $exe

Write-Host ""
Write-Host "Built successfully:" -ForegroundColor Green
Write-Host $exe
Write-Host ""
Write-Host "UltraSpeed layers:" -ForegroundColor Cyan
Write-Host "  - 1 ms Windows timer request"
Write-Host "  - above-normal browser/UI scheduling"
Write-Host "  - Windows execution-speed throttling disabled where supported"
Write-Host "  - cached proxy policy + hostname classification"
Write-Host "  - coalesced privacy-counter disk writes"
Write-Host "  - unused heavy Python modules excluded from OneFile"
if ($browserSigned) {
    Write-Host "  - Authenticode signed (SHA-256 + RFC3161 timestamp)" -ForegroundColor Green
} else {
    Write-Host "  - UNSIGNED build (set TEKZITE_SIGN_CERT_SHA1 to enable Authenticode)" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Run it with:" -ForegroundColor Cyan
Write-Host '& ".\dist\TekziteBrowser.exe"'
