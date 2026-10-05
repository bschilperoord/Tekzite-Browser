$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# A transparent directory layout: neither process self-extracts to a temp tree.
# Preserve the existing one-file builder for comparison and existing releases.
function Invoke-BuildPython([string[]]$Arguments) {
    & python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python build command failed: $LASTEXITCODE" }
}
Invoke-BuildPython @("-m", "pip", "install", "--only-binary=:all:", "--require-hashes", "-r", "requirements-windows.lock")
Invoke-BuildPython @("-m", "pip", "install", "--only-binary=:all:", "--require-hashes", "-r", "requirements-build-windows.lock")

$helperDist = Join-Path $PSScriptRoot "build/network-folder-dist"
$helperWork = Join-Path $PSScriptRoot "build/network-folder-work"
$specDir = Join-Path $PSScriptRoot "build/directory-spec"
Remove-Item $helperDist, $helperWork, $specDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "dist-folder/TekziteBrowser" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $specDir | Out-Null

Invoke-BuildPython @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noupx", "--optimize", "1",
    "--name", "tekzite-network", "--distpath", $helperDist, "--workpath", $helperWork,
    "--specpath", $specDir, "--exclude-module", "numpy", "--exclude-module", "pygame",
    "--exclude-module", "pytest", "tekzite_network_fast.py"
)
$helperFolder = Join-Path $helperDist "tekzite-network"
$extensionFolder = Join-Path $PSScriptRoot "chromium_zoom_extension"
$assetsFolder = Join-Path $PSScriptRoot "assets"
if (-not (Test-Path (Join-Path $helperFolder "tekzite-network.exe"))) { throw "Directory helper missing" }

Invoke-BuildPython @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noupx", "--windowed", "--optimize", "1",
    "--name", "TekziteBrowser", "--distpath", "dist-folder", "--workpath", "build/browser-folder-work",
    "--specpath", $specDir, "--add-data", "$helperFolder;network-helper",
    "--add-data", "$extensionFolder;chromium_zoom_extension", "--add-data", "$assetsFolder;assets",
    "--icon", "assets/tekzite.ico", "--version-file", "tekzite_version_info.txt",
    "--manifest", "tekzite_browser.manifest",
    "--hidden-import", "tkinter.ttk", "--hidden-import", "tkinter.font",
    "--hidden-import", "tkinter.colorchooser", "--hidden-import", "tkinter.filedialog",
    "--hidden-import", "tkinter.messagebox", "--hidden-import", "tkinter.simpledialog",
    "--exclude-module", "pytest", "--exclude-module", "numpy", "--exclude-module", "pygame",
    "--exclude-module", "matplotlib", "--exclude-module", "pandas", "--exclude-module", "scipy",
    "--exclude-module", "IPython", "--exclude-module", "psutil", "ultraspeed_launcher.py"
)
$folder = Join-Path $PSScriptRoot "dist-folder/TekziteBrowser"
$exe = Join-Path $folder "TekziteBrowser.exe"
if (-not (Test-Path $exe)) { throw "Directory browser missing" }
if (-not (Test-Path (Join-Path $folder "_internal/network-helper/tekzite-network.exe"))) { throw "Bundled directory helper missing" }

# No certificate is configured for these previews; do not claim signed output.
"Extract the whole ZIP into a folder. Run TekziteBrowser.exe and keep _internal beside it." |
    Set-Content (Join-Path $folder "README.txt") -Encoding utf8
Write-Host "Built directory preview: $folder (unsigned)"
