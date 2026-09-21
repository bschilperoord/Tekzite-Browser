from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_modern_corner_defaults_and_bounds_exist():
    custom = main._normalized_customization({})
    assert custom["window_corner_radius"] == 24
    assert custom["content_corner_radius"] == 18
    assert custom["control_corner_radius"] == 16
    limited = main._normalized_customization({
        "window_corner_radius": 999,
        "content_corner_radius": -10,
        "control_corner_radius": 999,
    })
    assert limited["window_corner_radius"] == 48
    assert limited["content_corner_radius"] == 0
    assert limited["control_corner_radius"] == 28


def test_frameless_window_uses_safe_native_windows_rounding():
    block = MAIN[MAIN.index("def _apply_window_rounding"):MAIN.index("def _apply_dwm_host_rounding")]
    assert "DWMWA_WINDOW_CORNER_PREFERENCE = 33" in block
    assert "DwmSetWindowAttribute" in block
    assert "not (self._window_maximized or self._fullscreen)" in block
    # The Tk root must never receive a shaped rounded region. It caused large
    # transparent holes in the browser chrome on scaled Windows desktops.
    assert "CreateRoundRectRgn" not in block
    assert "SetWindowRgn(wintypes.HWND(hwnd), None, True)" in block


def test_live_dwm_content_is_rounded_without_changing_input_path():
    helper = MAIN[MAIN.index("def _apply_dwm_host_rounding"):MAIN.index("def _apply_frameless_app_style")]
    assert 'self._ui_metric("content_corner_radius", 18)' in helper
    sync = MAIN[MAIN.index("def _sync_dwm_host_geometry"):MAIN.index("def _cancel_dwm_host_reveal")]
    assert "self._apply_dwm_host_rounding(hwnd, w, h)" in sync


def test_primary_toolbar_and_new_tab_use_rounded_canvas_controls():
    assert "class _RoundedChromeButton(tk.Canvas):" in MAIN
    toolbar = MAIN[MAIN.index("def chrome_button"):MAIN.index("self.back_button = chrome_button")]
    assert "return _RoundedChromeButton(" in toolbar
    tabs = MAIN[MAIN.index("# ── Browser tab strip"):MAIN.index("# ── Tekzite browser chrome")]
    assert "self.new_tab_button = _RoundedChromeButton(" in tabs


def test_omnibox_is_a_rounded_focus_surface():
    build = MAIN[MAIN.index("self.url_var = tk.StringVar"):MAIN.index("self.downloads_button = chrome_button")]
    assert "self.address_backdrop = tk.Canvas(" in build
    assert "self.address_inner = tk.Frame(" in build
    assert "self._set_address_shell_focus(True)" in build
    redraw = MAIN[MAIN.index("def _redraw_address_shell"):MAIN.index("def _rounded_canvas_rect")]
    assert 'self._ui_metric("control_corner_radius", 16)' in redraw
    assert 'self.ui["border_focus"] if self._address_focused' in redraw


def test_corner_radius_controls_are_exposed_in_customize_dialog():
    assert 'window_radius_var = tk.StringVar(value=str(draft.get("window_corner_radius", 24)))' in MAIN
    assert 'content_radius_var = tk.StringVar(value=str(draft.get("content_corner_radius", 18)))' in MAIN
    assert 'control_radius_var = tk.StringVar(value=str(draft.get("control_corner_radius", 16)))' in MAIN
    assert 'custom["window_corner_radius"] = int_value(window_radius_var, 24)' in MAIN
    assert 'custom["content_corner_radius"] = int_value(content_radius_var, 18)' in MAIN
    assert 'custom["control_corner_radius"] = int_value(control_radius_var, 16)' in MAIN

