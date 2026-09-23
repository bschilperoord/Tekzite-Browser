#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "== Tekzite Browser Linux Preview build =="

find . -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f -name '*.pyc' -delete 2>/dev/null || true

python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt

rm -rf build/linux-network-work build/linux-network-dist build/linux-network-spec \
       build/linux-browser-work build/linux-browser-dist build/linux-browser-spec dist-linux
mkdir -p build/linux-network-spec build/linux-browser-spec dist-linux

echo "Building Tekzite Network helper..."
python -m PyInstaller \
  --noconfirm --clean --onefile --optimize 1 \
  --name tekzite-network \
  --distpath build/linux-network-dist \
  --workpath build/linux-network-work \
  --specpath build/linux-network-spec \
  --exclude-module numpy --exclude-module pygame --exclude-module pytest \
  tekzite_network_fast.py

helper="$(pwd)/build/linux-network-dist/tekzite-network"
[[ -x "$helper" ]] || { echo "Missing network helper: $helper" >&2; exit 1; }
cp "$helper" ./tekzite-network
chmod +x ./tekzite-network

cat > build/linux-browser-spec/TekziteBrowser-Linux.spec <<'PYISPEC'
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
project = Path(SPECPATH).resolve().parents[1]
helper = project / "tekzite-network"
if not helper.is_file():
    raise SystemExit("tekzite-network is missing")
datas = []
for folder in ("chromium_zoom_extension", "assets"):
    candidate = project / folder
    if candidate.is_dir():
        datas.append((str(candidate), folder))
a = Analysis(
    [str(project / "ultraspeed_launcher.py")],
    pathex=[str(project)],
    binaries=[(str(helper), ".")],
    datas=datas,
    hiddenimports=["tkinter", "PIL.ImageTk", "PIL._tkinter_finder"], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "numpy", "pygame", "matplotlib", "pandas", "scipy", "IPython", "psutil"],
    noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="TekziteBrowser", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
PYISPEC

echo "Building Tekzite Browser..."
python -m PyInstaller \
  --noconfirm --clean \
  --distpath dist-linux \
  --workpath build/linux-browser-work \
  build/linux-browser-spec/TekziteBrowser-Linux.spec

[[ -x dist-linux/TekziteBrowser ]] || { echo "Linux executable was not produced" >&2; exit 1; }

rm -f ./tekzite-network

echo
echo "Built: $(pwd)/dist-linux/TekziteBrowser"
echo "Runtime requirement: a Chromium-family executable in PATH (chromium/chromium-browser/google-chrome)."
