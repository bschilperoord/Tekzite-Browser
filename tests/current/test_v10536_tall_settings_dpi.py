from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")

def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]

def test_release_version():
    assert main.BROWSER_VERSION == "10.5.73"

def test_settings_stays_in_tk_coordinate_space():
    block = _settings_block()
    assert "screen_h = max(1, int(win.winfo_screenheight()))" in block
    assert "work = self._monitor_work_area_for_window(self.root)" not in block

def test_settings_animation_waits_for_final_geometry():
    block = _settings_block()
    assert "auto_animate=False" in block
    assert "self._apply_about_style_to_dialog(win)" in block
    assert "self._animate_toplevel_in(win, 155, slide=14)" in block
