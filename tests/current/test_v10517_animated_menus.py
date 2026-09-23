from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.80"


def test_animated_popup_menu_replaces_native_popup_primitive():
    block = MAIN[MAIN.index("class _AnimatedPopupMenu"):MAIN.index("class BrowserApp")]
    assert "tk.Toplevel" in block
    assert "overrideredirect(True)" in block
    assert 'attributes("-alpha"' in block
    assert "_animate_open" in block


def test_menu_rows_have_press_and_delayed_click_feedback():
    block = MAIN[MAIN.index("class _AnimatedPopupMenu"):MAIN.index("class BrowserApp")]
    assert "def _on_press" in block
    assert "def _on_release" in block
    assert "self.app.root.after(45" in block
    assert "self._pressed_index" in block


def test_cascades_and_keyboard_navigation_are_supported():
    block = MAIN[MAIN.index("class _AnimatedPopupMenu"):MAIN.index("class BrowserApp")]
    assert "def _open_cascade" in block
    assert "self.app.root.after(140" in block
    assert 'key == "Escape"' in block
    assert 'key in {"Down", "Up"}' in block
    assert 'key in {"Return", "space"}' in block


def test_menu_bar_buttons_have_pressed_and_selected_feedback():
    rounded = MAIN[MAIN.index("class _RoundedChromeButton"):MAIN.index("class _AnimatedPopupMenu")]
    assert "self._selected = False" in rounded
    assert "press_inset = 2" in rounded
    assert "def set_selected" in rounded

    popup = MAIN[MAIN.index("def _popup_menu_below"):MAIN.index("def _show_address_context_menu")]
    assert "button.set_selected(True)" in popup
    assert "menu._anchor_button = button" in popup

