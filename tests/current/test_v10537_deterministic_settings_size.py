from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")

def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]

def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"

def test_settings_has_one_stable_screen_relative_geometry():
    block = _settings_block()
    assert "requested_h = min(1120, max(720, int(round(screen_h * 0.88))))" in block
    assert 'final_geometry = f"{dialog_w}x{dialog_h}+{x}+{y}"' in block
    assert "def enforce_final_geometry():" in block
    assert "win.after(190, enforce_final_geometry)" in block
    assert "win.after(360, enforce_final_geometry)" in block
    assert "win.maxsize(dialog_w, dialog_h)" not in block
