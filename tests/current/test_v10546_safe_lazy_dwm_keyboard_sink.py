from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import main


def _source():
    return Path(main.__file__).read_text(encoding="utf-8")


def test_release_is_v10546():
    assert main.BROWSER_VERSION == "10.5.54"


def test_keyboard_sink_is_tk_owned_not_raw_subclass():
    source = _source()
    start = source.index("def _ensure_dwm_keyboard_sink")
    end = source.index("def _focus_dwm_keyboard_sink", start)
    block = source[start:end]
    assert "tk.Entry(" in block
    assert "CreateWindowExW" not in block
    assert "SetWindowLongPtrW" not in block
    assert "WINFUNCTYPE" not in block
    assert "CallWindowProcW" not in block


def test_sink_is_lazy_and_not_created_by_bootstrap_arm():
    source = _source()
    start = source.index("def _arm_dwm_input_surface")
    end = source.index("def _on_edge_host_configure", start)
    block = source[start:end]
    assert "_ensure_dwm_keyboard_sink" not in block
    assert "_focus_dwm_keyboard_sink" not in block
    assert "_dwm_keyboard_sink_widget" not in block


def test_page_click_activates_safe_sink():
    source = _source()
    start = source.index("def _dispatch_chromium_press_xy")
    end = source.index("def _flush_pending_chromium_drag_before_release", start)
    block = source[start:end]
    assert "self._focus_dwm_keyboard_sink()" in block
    assert block.index("self._chromium_page_keyboard_active = True") < block.index("self._focus_dwm_keyboard_sink()")


def test_sink_key_handler_reuses_ordered_chromium_key_lane():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._dwm_keyboard_sink_messages = 0
    app._dwm_keyboard_sink_chars = 0
    app._dwm_keyboard_sink_last = None
    app._on_chromium_surface_key = Mock(return_value="break")
    event = SimpleNamespace(char="a", keysym="a", state=0)
    assert app._on_dwm_keyboard_sink_key(event) == "break"
    assert app._dwm_keyboard_sink_messages == 1
    assert app._dwm_keyboard_sink_chars == 1
    assert app._dwm_keyboard_sink_last == ("a", "a", 0)
    app._on_chromium_surface_key.assert_called_once_with(event)


def test_unsafe_v10544_raw_sink_proc_does_not_return():
    source = _source()
    assert "_dwm_keyboard_sink_wndproc" not in source
    assert "def _handle_dwm_keyboard_message" not in source
    # The DWM host itself still has its established WNDPROC. Scope the safety
    # assertion specifically to the keyboard-sink implementation.
    start = source.index("def _ensure_dwm_keyboard_sink")
    end = source.index("def _ensure_dwm_host", start)
    sink_block = source[start:end]
    assert "SetWindowLongPtrW" not in sink_block
    assert "CallWindowProcW" not in sink_block


def test_sink_cleanup_is_tk_owned():
    source = _source()
    close = source[source.index("def on_close(self):"):source.index("def run(self):")]
    assert 'sink.destroy()' in close
    assert 'DestroyWindow(wintypes.HWND(int(self._dwm_keyboard_sink' not in close
