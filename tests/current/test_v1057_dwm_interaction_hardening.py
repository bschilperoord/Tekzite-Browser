from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.80"


def test_click_count_progresses_and_resets():
    f = main._next_pointer_click_count
    assert f(0.0, None, 0, 10.0, (100, 100)) == 1
    assert f(10.0, (100, 100), 1, 10.20, (102, 101)) == 2
    assert f(10.20, (102, 101), 2, 10.35, (101, 102)) == 3
    assert f(10.35, (101, 102), 3, 11.00, (101, 102)) == 1
    assert f(10.35, (101, 102), 3, 10.40, (120, 120)) == 1


def test_real_click_count_is_forwarded_but_motion_is_zero():
    press = MAIN[MAIN.index("def _dispatch_chromium_press_xy"):MAIN.index("def _flush_pending_chromium_drag_before_release")]
    release = MAIN[MAIN.index("def _dispatch_chromium_release_xy"):MAIN.index("def _dispatch_chromium_drag_xy")]
    assert "_next_pointer_click_count" in press
    assert 'click_count=0' in press
    assert 'click_count=self._chromium_press_click_count' in press
    assert 'click_count=click_count' in release


def test_drag_is_coalesced_and_final_point_precedes_release():
    drag = MAIN[MAIN.index("def _dispatch_chromium_drag_xy"):MAIN.index("def _schedule_dwm_pointer_bridge")]
    release = MAIN[MAIN.index("def _dispatch_chromium_release_xy"):MAIN.index("def _dispatch_chromium_drag_xy")]
    assert "self._chromium_pending_drag = (x, y)" in drag
    assert "def _flush_chromium_drag_motion" in drag
    assert 'button="left", buttons=1, click_count=0' in drag
    assert release.index("_flush_pending_chromium_drag_before_release()") < release.index('"mouseReleased"')


def test_middle_click_is_bound_on_both_chromium_surfaces():
    assert 'self.edge_host.bind("<ButtonRelease-2>", self._on_chromium_surface_middle_click)' in MAIN
    assert 'self.chromium_surface.bind("<ButtonRelease-2>", self._on_chromium_surface_middle_click)' in MAIN
    block = MAIN[MAIN.index("def _on_chromium_surface_middle_click"):MAIN.index("def _on_chromium_surface_context_menu")]
    assert 'get_embedded_chromium_context' in block
    assert 'self._new_tab(url=href, switch=False, navigate=True)' in block
    assert 'button="middle", buttons=4' in block


def test_right_click_focuses_point_before_context_resolution():
    block = MAIN[MAIN.index("def _on_chromium_surface_context_menu"):MAIN.index("def _cancel_embedded_surface_wakes")]
    assert "focus_embedded_chromium_point" in block
    assert block.index("focus_embedded_chromium_point") < block.index("get_embedded_chromium_context")


def test_shift_wheel_keeps_horizontal_axis_and_modifiers():
    block = MAIN[MAIN.index("def _on_chromium_surface_wheel"):MAIN.index("def _on_root_chromium_key")]
    assert "dx, dy = (delta, 0.0) if shift else (0.0, delta)" in block
    assert "delta_x=delta_x, delta_y=delta_y, modifiers=modifiers" in block
    dispatch = NET[NET.index("def dispatch_embedded_chromium_mouse"):NET.index("def get_embedded_chromium_cursor")]
    assert "modifiers: int = 0" in dispatch
    assert 'params["modifiers"] = int(modifiers)' in dispatch
    assert "click_count: int = 0" in dispatch


def test_altgr_printable_text_uses_insert_text():
    block = MAIN[MAIN.index("def _on_chromium_surface_key"):MAIN.index("def _clipboard_set")]
    assert "altgr_text" in block
    assert "control and alt" in block
    assert 'event_type="insertText"' in block

