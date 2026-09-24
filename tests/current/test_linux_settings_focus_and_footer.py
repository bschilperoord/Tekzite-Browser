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


def test_linux_settings_uses_cooperative_focus_without_delayed_force():
    block = _settings_block()
    assert "entry.focus_set()" in block
    assert "entry.focus_force()" not in block
    assert "win.after(60, focus_linux_settings)" not in block
    assert 'if os.name == "nt":\n                try:\n                    win.focus_force()' in block


def test_settings_footer_is_reserved_before_scroll_body():
    block = _settings_block()
    assert 'buttons.pack(fill="x", side="bottom", pady=(14, 0), before=scroll_host)' in block


def test_settings_custom_close_uses_cancel_path():
    block = _settings_block()
    assert 'close_button.configure(command=cancel_preferences)' in block


def test_settings_is_modeless_and_restores_browser_keyboard_input():
    block = _settings_block()
    assert "win.grab_set()" not in block
    assert "def _force_browser_keyboard_target(target):" in block
    assert "target.focus_set()" in block
    assert "if self.root.focus_get() is not target:" in block
    assert "target.focus_force()" in block
    assert "def restore_browser_input_after_settings():" in block
    assert "_force_browser_keyboard_target(self.address)" in block
    assert "self._chromium_page_keyboard_active = True" in block
    assert "_force_browser_keyboard_target(target)" in block
    assert "restore_browser_input_after_settings()\n            win.destroy()" in block
    assert "schedule_browser_input_restore()" in block
    assert 'if sys.platform.startswith("linux"):\n                return' in block
    assert "self.root.after(150, restore_browser_input_after_settings)" in block


def test_linux_omnibox_click_reclaims_native_keyboard_focus():
    start = MAIN.index("def _on_address_pointer_down")
    end = MAIN.index("def _on_address_focus_in", start)
    block = MAIN[start:end]
    assert "self.root.focus_force()" in block
    assert "self.address.focus_force()" in block
    assert 'self.root.tk.call("focus", "-force", self.address._w)' in block


def test_linux_page_click_reclaims_native_keyboard_focus():
    start = MAIN.index("def _dispatch_chromium_press_xy")
    end = MAIN.index("def _flush_pending_chromium_drag_before_release", start)
    block = MAIN[start:end]
    assert 'if sys.platform.startswith("linux"):' in block
    assert "self.root.focus_force()" in block
    assert "self.chromium_surface.focus_force()" in block
    assert 'self.root.tk.call("focus", "-force", self.chromium_surface._w)' in block


def test_linux_background_native_wake_never_forces_focus():
    start = MAIN.index("def _focus_embedded_surface")
    end = MAIN.index("def _show_embedded_host", start)
    block = MAIN[start:end]
    assert 'if sys.platform.startswith("linux"):' in block
    assert "Native HWND wake/activation is a Windows workaround" in block
    schedule = MAIN[MAIN.index("def _schedule_embedded_surface_wake", start):end]
    assert 'if sys.platform.startswith("linux"):' in schedule
    assert "Never schedule background focus/activation retries on Linux" in schedule


def test_linux_dialog_z_order_path_is_compositor_neutral():
    start = MAIN.index("def _raise_toplevel_above_dwm")
    end = MAIN.index("def _show_about", start)
    block = MAIN[start:end]
    linux = block[block.index('if os.name != "nt":'):block.index("try:", block.index('if os.name != "nt":') + 1)]
    assert "focus_force()" not in linux
    assert '"-topmost"' not in linux
