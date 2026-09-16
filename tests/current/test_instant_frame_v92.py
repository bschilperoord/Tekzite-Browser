from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_native_startup_uses_single_attached_frame_gate():
    block = NET[NET.index("def open_embedded_chromium"):NET.index("def record_embedded_native_recovery")]
    assert "wait_for_first_frame=bool((not attach_native) and (not hot_native_navigation))" in block
    assert "_wait_for_attached_first_frame(session, timeout=2.0)" in block


def test_attached_frame_fast_path_avoids_screenshot_when_semantic_geometry_ready():
    block = NET[NET.index("def _wait_for_attached_first_frame"):NET.index("def navigate_embedded_chromium")]
    assert "elapsed >= 0.10" in block
    assert "Page.captureScreenshot" in block
    assert 'time.sleep(0.006)' in block
    assert 'attached-semantic-geometry' in block


def test_only_critical_input_warms_before_reveal():
    block = NET[NET.index("def open_embedded_chromium"):NET.index("def record_embedded_native_recovery")]
    assert '_get_persistent_page_cdp_channel' not in block or 'frame gate itself opens and retains the critical input lane' in block
    show = MAIN[MAIN.index("def _show_embedded_host"):MAIN.index("def _arm_dwm_input_surface")]
    assert '("scroll", "hover")' in show


def test_navigation_future_poll_is_low_latency():
    poll = MAIN[MAIN.index("def _poll_embedded_navigation"):MAIN.index("def _navigate_embedded")]
    assert "self.root.after(8, self._poll_embedded_navigation" in poll


def test_startup_has_no_fixed_quarter_second_delay():
    assert "self.root.after_idle(lambda: self._feature_startup(lambda: self._restore_startup_tabs(startup_action)))" in MAIN
    assert "250,\n            startup_action" not in MAIN
