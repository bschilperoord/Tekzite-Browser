from pathlib import Path

MAIN = (Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8")

def test_v97_drag_is_coalesced():
    assert 'BROWSER_VERSION = "10.5.73"' in MAIN
    assert 'self._window_drag_pending_xy' in MAIN
    assert 'self.root.after(8, self._flush_window_drag)' in MAIN
    assert '16 if self._window_drag_active else 1' in MAIN

def test_drag_release_flushes_exact_position():
    assert 'def _end_window_drag' in MAIN
    assert 'self._schedule_dwm_geometry_sync(resize=False, delay=1)' in MAIN

def test_pure_root_move_does_not_resize_chromium():
    block = MAIN.split('def _on_root_configure_native_overlay', 1)[1].split('def ', 1)[0]
    assert '_schedule_dwm_geometry_sync(resize=False' in block

