from pathlib import Path
import inspect
from unittest.mock import patch

import main
import engine.net as net

ROOT = Path(__file__).resolve().parents[2]

def test_linux_build_script_exists_and_bundles_helper():
    script = (ROOT / "build_linux.sh").read_text(encoding="utf-8")
    assert "PyInstaller" in script
    assert "tekzite-network" in script
    assert "TekziteBrowser" in script

def test_non_windows_uses_software_presentation():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.preferences = {"chromium_presentation": "native"}
    with patch.object(main.os, "name", "posix"):
        assert app._use_chromium_software_surface_for_url("https://example.com/") is True

def test_network_helper_name_is_platform_specific():
    source = inspect.getsource(net._ensure_network_engine_locked)
    assert '"tekzite-network.exe" if os.name == "nt" else "tekzite-network"' in source
