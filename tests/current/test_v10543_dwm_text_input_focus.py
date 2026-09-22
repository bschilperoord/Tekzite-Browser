from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _press_block():
    start = MAIN.index("    def _dispatch_chromium_press_xy")
    end = MAIN.index("    def _flush_pending_chromium_drag_before_release", start)
    return MAIN[start:end]


def test_release_is_v10543():
    assert 'BROWSER_VERSION = "10.5.54"' in MAIN


def test_dwm_page_click_reclaims_keyboard_focus():
    block = _press_block()
    assert "if self._chromium_dwm_mode:" in block
    assert "self._focus_dwm_keyboard_sink()" in block
    assert "self.root.focus_force()" in block  # fallback if the safe sink cannot focus
    assert "self.edge_host.focus_set()" in block
    assert block.index("self._chromium_page_keyboard_active = True") < block.index("self._focus_dwm_keyboard_sink()")


def test_dwm_page_click_focuses_editable_on_ordered_input_lane():
    block = _press_block()
    mouse_press = block.index('dispatch_embedded_chromium_mouse, "mousePressed"')
    point_focus = block.index("focus_embedded_chromium_point, x, y")
    assert mouse_press < point_focus
    assert "target_id=self._chromium_frame_target_id, timeout=2" in block
