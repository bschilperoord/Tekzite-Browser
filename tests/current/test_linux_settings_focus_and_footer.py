from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]


def test_linux_settings_is_frameless_and_uses_tekzite_header():
    block = _settings_block()
    assert 'branded=True' in block
    assert "win.overrideredirect(False)" not in block
    assert "self._apply_about_style_to_dialog(win)" in block


def test_linux_settings_forces_keyboard_focus_after_frameless_map():
    block = _settings_block()
    assert "win.focus_force()" in block
    assert "entry.focus_force()" in block
    assert "win.after(60, focus_linux_settings)" in block
    assert "win.after(220, focus_linux_settings)" in block


def test_settings_footer_is_reserved_before_scroll_body():
    block = _settings_block()
    assert 'buttons.pack(fill="x", side="bottom", pady=(14, 0), before=scroll_host)' in block


def test_settings_custom_close_uses_cancel_path():
    block = _settings_block()
    assert 'close_button.configure(command=cancel_preferences)' in block
