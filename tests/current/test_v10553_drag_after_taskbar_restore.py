from pathlib import Path

import main


SOURCE = Path(main.__file__).read_text(encoding="utf-8")


def test_release_version_is_10553():
    assert main.BROWSER_VERSION == "10.5.73"


def test_minimize_invalidates_cached_native_drag_hwnd():
    start = SOURCE.index("    def _minimize_window(")
    end = SOURCE.index("    def _restore_frameless_after_minimize(", start)
    block = SOURCE[start:end]
    assert "self._invalidate_native_window_drag_target()" in block
    assert block.index("self._invalidate_native_window_drag_target()") < block.index("self.root.overrideredirect(False)")


def test_restore_refreshes_current_native_root_before_dwm_restore():
    start = SOURCE.index("    def _restore_frameless_after_minimize(")
    end = SOURCE.index("    def _toggle_fullscreen(", start)
    block = SOURCE[start:end]
    assert "self._invalidate_native_window_drag_target()" in block
    assert "self._prewarm_native_window_drag()" in block
    assert block.index("self._prewarm_native_window_drag()") < block.index("self._restore_dwm_host_after_taskbar()")


def test_every_custom_titlebar_drag_refreshes_native_root_hwnd():
    start = SOURCE.index("    def _start_window_drag(")
    end = SOURCE.index("    def _flush_window_drag(", start)
    block = SOURCE[start:end]
    assert "self._prewarm_native_window_drag()" in block


def test_native_move_revalidates_cached_hwnd_and_fails_closed():
    start = SOURCE.index("    def _native_move_window_drag(")
    end = SOURCE.index("    def _start_window_drag(", start)
    block = SOURCE[start:end]
    assert "live_hwnd = self._current_native_root_hwnd()" in block
    assert "int(self._native_drag_hwnd) != int(live_hwnd)" in block
    assert "if not root_moved:" in block
    assert "self._invalidate_native_window_drag_target()" in block
    assert block.index("if not root_moved:") < block.index("if has_dwm:", block.index("root_moved = bool"))
