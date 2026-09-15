from pathlib import Path

MAIN = Path(__file__).resolve().parents[2].joinpath("main.py").read_text(encoding="utf-8")

def test_v98_native_drag_fastpath_is_prewarmed():
    assert 'self.root.after(40, self._prewarm_native_window_drag)' in MAIN
    assert 'def _native_move_window_drag(self, x, y):' in MAIN
    assert 'user32.SetWindowPos(' in MAIN

def test_live_drag_moves_dwm_with_top_level_and_suppresses_configure_chase():
    assert 'self._native_drag_dwm_offset' in MAIN
    assert 'if self._window_drag_active and self._native_drag_dwm_offset is not None:' in MAIN
    assert 'if not self._native_move_window_drag(x, y):' in MAIN
