from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _settings_block():
    return MAIN[MAIN.index("def show_preferences"):MAIN.index("def _raise_toplevel_above_dwm")]


def test_linux_settings_uses_wm_managed_window_for_keyboard_focus():
    block = _settings_block()
    assert 'branded=(os.name == "nt")' in block
    assert "win.overrideredirect(False)" in block
    assert "win.after(80, lambda: win.winfo_exists() and entry.focus_set())" in block


def test_settings_footer_is_reserved_before_scroll_body():
    block = _settings_block()
    assert 'buttons.pack(fill="x", side="bottom", pady=(14, 0), before=scroll_host)' in block


def test_linux_settings_does_not_apply_windows_frameless_header():
    block = _settings_block()
    marker = 'if os.name == "nt":\n                    self._apply_about_style_to_dialog(win)'
    assert marker in block
