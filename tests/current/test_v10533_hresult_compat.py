from pathlib import Path
import ctypes

import main
import engine.net as net

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.47"


def test_hresult_compat_type_is_always_32_bit():
    assert ctypes.sizeof(net.HRESULT) == 4


def test_no_direct_wintypes_hresult_dependency_remains():
    assert "wintypes.HRESULT" not in NET


def test_dwm_calls_use_compat_hresult_alias():
    assert "DwmRegisterThumbnail.restype = HRESULT" in NET
    assert "DwmUpdateThumbnailProperties.restype = HRESULT" in NET
    assert "DwmUnregisterThumbnail.restype = HRESULT" in NET
    assert "DwmFlush.restype = HRESULT" in NET
