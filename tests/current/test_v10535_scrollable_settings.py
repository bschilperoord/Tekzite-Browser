from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.73"


def test_settings_body_has_vertical_scrollbar_and_canvas():
    block = _settings_block()
    assert "settings_canvas = tk.Canvas(" in block
    assert "settings_scrollbar = tk.Scrollbar(" in block
    assert 'orient="vertical"' in block
    assert "command=settings_canvas.yview" in block
    assert "yscrollcommand=settings_scrollbar.set" in block
    assert 'settings_canvas.create_window((0, 0), window=outer, anchor="nw")' in block


def test_settings_supports_mouse_wheel_scrolling():
    block = _settings_block()
    assert 'win.bind("<MouseWheel>", scroll_settings' in block
    assert 'settings_canvas.yview_scroll(units * 3, "units")' in block


def test_settings_footer_stays_outside_scrollable_body():
    block = _settings_block()
    assert 'buttons = tk.Frame(shell, bg=self.ui["bg"])' in block
    assert 'buttons = tk.Frame(outer' not in block


def test_settings_prefers_taller_dialog():
    block = _settings_block()
    assert "requested_h = min(1120, max(720, int(round(screen_h * 0.88))))" in block
    assert "dialog_h = min(requested_h, max(620, screen_h - 64))" in block
    assert "win = self._new_animated_toplevel(self.root, auto_animate=False)" in block
    assert "self._apply_about_style_to_dialog(win)" in block
