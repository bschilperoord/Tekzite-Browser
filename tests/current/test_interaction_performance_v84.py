from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_version_84():
    assert 'BROWSER_VERSION = "10.5.32"' in MAIN


def test_hover_has_separate_executor():
    assert 'thread_name_prefix="tekzite-cdp-hover"' in MAIN
    cursor = MAIN[MAIN.index('def _request_chromium_cursor_probe'):MAIN.index('def _poll_chromium_cursor_probe')]
    assert '_chromium_cursor_executor.submit' in cursor


def test_motion_is_latest_value_only():
    block = MAIN[MAIN.index('def _flush_chromium_surface_motion'):MAIN.index('def _tk_cursor_for_css')]
    assert '_chromium_motion_future' in block
    assert '_chromium_hover_executor.submit' in block
    assert '_submit_chromium_input' not in block


def test_dwm_geometry_uses_low_latency_coalescing():
    assert 'def _schedule_dwm_geometry_sync(self, resize=False, delay=8)' in MAIN
    assert '_schedule_dwm_geometry_sync(resize=True, delay=8)' in MAIN
    assert '_schedule_dwm_geometry_sync(resize=False, delay=8)' in MAIN


def test_rich_tab_context_menu_present():
    for text in ('Duplicate Tab', 'Reopen Closed Tab', 'Close Other Tabs', 'Close Tabs to the Right', 'Copy Tab URL'):
        assert text in MAIN


def test_selected_text_search_present():
    assert 'Search Selected Text' in MAIN
