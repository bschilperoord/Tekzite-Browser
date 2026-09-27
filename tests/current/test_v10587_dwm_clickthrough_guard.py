from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_native_pointer_hit_accepts_only_page_surface_or_child():
    helper = main._native_pointer_hit_is_page_surface
    assert helper(100, 100, 200) is True
    assert helper(200, 100, 200) is True
    assert helper(301, 100, 200, is_child=lambda parent, child: (parent, child) == (100, 301)) is True
    assert helper(999, 100, 200, is_child=lambda _parent, _child: False) is False
    assert helper(0, 100, 200) is False


def test_dwm_pointer_watchdog_checks_real_top_window_before_new_press():
    poll = MAIN[MAIN.index("def _poll_dwm_pointer_bridge"):MAIN.index("def _submit_chromium_input")]
    assert "WindowFromPoint" in poll
    assert "_native_pointer_hit_is_page_surface" in poll
    assert "inside = bool(inside_geometry and page_hit)" in poll
    assert "physical_left_down and not self._chromium_left_button_down and inside" in poll


def test_existing_page_drag_can_release_even_after_surface_is_covered():
    poll = MAIN[MAIN.index("def _poll_dwm_pointer_bridge"):MAIN.index("def _submit_chromium_input")]
    assert "tracking = bool(inside or self._chromium_left_button_down)" in poll
    assert "(not physical_left_down) and self._chromium_left_button_down" in poll
