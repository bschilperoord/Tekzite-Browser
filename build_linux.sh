#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== Tekzite Browser UltraSpeed Linux build =="

find . -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f -name '*.pyc' -delete 2>/dev/null || true

python -m pip install --only-binary=:all: -r requirements.txt
python -m pip install --only-binary=:all: -r requirements-build.txt

rm -rf build/network-work build/network-dist build/network-spec build/browser-spec dist
mkdir -p build/network-spec build/browser-spec

echo "Building Linux Tekzite network helper..."
python -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --optimize 1 \
  --name tekzite-network \
  --distpath build/network-dist \
  --workpath build/network-work \
  --specpath build/network-spec \
  --exclude-module numpy \
  --exclude-module pygame \
  --exclude-module pytest \
  tekzite_network_fast.py

helper="$(pwd)/build/network-dist/tekzite-network"
[[ -x "$helper" ]] || { echo "Missing network helper: $helper" >&2; exit 1; }
cp "$helper" ./tekzite-network
chmod +x ./tekzite-network

spec="build/browser-spec/TekziteBrowser-UltraSpeed-Linux.spec"
cat > "$spec" <<'PYEOF'
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project = Path(SPECPATH).resolve().parents[1]
helper = project / "tekzite-network"
if not helper.is_file():
    raise SystemExit("tekzite-network is missing")

extension_dir = project / "chromium_zoom_extension"
assets_dir = project / "assets"
datas = []
if extension_dir.is_dir():
    datas.append((str(extension_dir), "chromium_zoom_extension"))
if assets_dir.is_dir():
    datas.append((str(assets_dir), "assets"))

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
        "pytest", "numpy", "pygame", "matplotlib", "pandas", "scipy",
        "IPython", "psutil",
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
)
PYEOF

echo "Building Tekzite Browser Linux x86_64..."
python -m PyInstaller --noconfirm --clean "$spec"

binary="dist/TekziteBrowser"
[[ -x "$binary" ]] || { echo "Missing browser binary: $binary" >&2; exit 1; }

echo "Built successfully: $binary"
