$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== Tekzite Browser Windows build ==" -ForegroundColor Cyan

python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

$helperWork = Join-Path $PSScriptRoot "build\network-work"
$helperDist = Join-Path $PSScriptRoot "build\network-dist"
$helperSpec = Join-Path $PSScriptRoot "build\network-spec"

Remove-Item $helperWork -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $helperDist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $helperSpec -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $helperSpec | Out-Null

Write-Host "Building Tekzite network helper..." -ForegroundColor Yellow
python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name "tekzite-network" `
  --distpath $helperDist `
  --workpath $helperWork `
  --specpath $helperSpec `
  tekzite_network.py

Copy-Item (Join-Path $helperDist "tekzite-network.exe") (Join-Path $PSScriptRoot "tekzite-network.exe") -Force

Write-Host "Building Tekzite Browser..." -ForegroundColor Yellow
python -m PyInstaller --noconfirm --clean TekziteBrowser.spec

$exe = Join-Path $PSScriptRoot "dist\Tekzite Browser\Tekzite Browser.exe"
if (-not (Test-Path $exe)) {
    throw "Build completed without expected executable: $exe"
}

Write-Host "" 
Write-Host "Built successfully:" -ForegroundColor Green
Write-Host $exe
Write-Host ""
Write-Host "Run it with:" -ForegroundColor Cyan
Write-Host '& ".\dist\Tekzite Browser\Tekzite Browser.exe"'
