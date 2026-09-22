from pathlib import Path

import main


ROOT = Path(main.__file__).resolve().parent
SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_is_v10547():
    assert main.BROWSER_VERSION == "10.5.54"


def test_dwm_keyboard_poll_is_foreground_only_and_hook_free():
    start = SOURCE.index("def _poll_dwm_keyboard")
    end = SOURCE.index("def _ensure_dwm_keyboard_sink", start)
    block = SOURCE[start:end]
    assert "GetForegroundWindow" in block
    assert "GetWindowThreadProcessId" in block
    assert "GetAsyncKeyState" in block
    assert "os.getpid()" in block
    assert "SetWindowsHookEx" not in block
    assert "SetWindowLongPtrW" not in block


def test_dwm_keyboard_translation_uses_windows_layout_and_insert_text():
    start = SOURCE.index("def _dwm_vk_to_text")
    end = SOURCE.index("def _poll_dwm_keyboard", start)
    block = SOURCE[start:end]
    assert "GetKeyboardLayout" in block
    assert "MapVirtualKeyExW" in block
    assert "ToUnicodeEx" in block
    assert 'event_type="insertText"' in block


def test_page_click_starts_native_keyboard_poll():
    start = SOURCE.index("def _dispatch_chromium_press_xy")
    end = SOURCE.index("def _flush_pending_chromium_drag_before_release", start)
    block = SOURCE[start:end]
    assert "self._focus_dwm_keyboard_sink()" in block
    assert "self._schedule_dwm_keyboard_poll(0)" in block


def test_omnibox_and_shutdown_stop_native_poll():
    assert SOURCE.count("self._stop_dwm_keyboard_poll()") >= 3
