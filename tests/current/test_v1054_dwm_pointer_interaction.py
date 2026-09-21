from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_dwm_destination_stays_hit_transparent():
    host = MAIN[MAIN.index("def _ensure_dwm_host"):MAIN.index("def _sync_dwm_host_geometry")]
    assert "WM_NCHITTEST" in host
    assert "HTTRANSPARENT" in host


def test_dwm_pointer_watchdog_is_armed_on_reveal():
    show = MAIN[MAIN.index("def _show_embedded_host"):MAIN.index("def _arm_dwm_input_surface")]
    assert "self._schedule_dwm_pointer_bridge(delay=1)" in show
    assert "def _poll_dwm_pointer_bridge" in MAIN
    assert "GetCursorPos" in MAIN
    assert "GetAsyncKeyState" in MAIN


def test_dwm_pointer_watchdog_is_fallback_not_duplicate_input():
    poll = MAIN[MAIN.index("def _poll_dwm_pointer_bridge"):MAIN.index("def _submit_chromium_input")]
    assert "physical_left_down and not self._chromium_left_button_down" in poll
    assert "(not physical_left_down) and self._chromium_left_button_down" in poll
    assert "tk_quiet_for >= 0.018" in poll


def test_tk_and_native_fallback_share_one_coordinate_transform():
    mapping = MAIN[MAIN.index("def _dwm_local_to_chromium_xy"):MAIN.index("def _surface_xy")]
    surface = MAIN[MAIN.index("def _surface_xy"):MAIN.index("def _note_dwm_tk_pointer_delivery")]
    poll = MAIN[MAIN.index("def _poll_dwm_pointer_bridge"):MAIN.index("def _submit_chromium_input")]
    assert "get_embedded_chromium_dwm_input_offset" in mapping
    assert "get_embedded_chromium_input_scale" in mapping
    assert "return self._dwm_local_to_chromium_xy(x, y)" in surface
    assert "self._dwm_local_to_chromium_xy(lx, ly)" in poll


def test_click_places_pointer_before_button_transition():
    press = MAIN[MAIN.index("def _dispatch_chromium_press_xy"):MAIN.index("def _dispatch_chromium_release_xy")]
    assert press.index('"mouseMoved"') < press.index('"mousePressed"')
    assert 'buttons=1' in press


def test_hover_updates_dom_cursor_and_element_hover_state():
    queue = MAIN[MAIN.index("def _queue_chromium_hover_xy"):MAIN.index("def _dispatch_chromium_press_xy")]
    flush = MAIN[MAIN.index("def _flush_chromium_surface_motion"):MAIN.index("def _tk_cursor_for_css")]
    assert "_chromium_pending_motion" in queue
    assert 'dispatch_embedded_chromium_mouse, "mouseMoved"' in flush
    assert "self._request_chromium_cursor_probe()" in flush
