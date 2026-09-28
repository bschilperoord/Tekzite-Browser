import inspect

import browser_features
import main


INIT_SOURCE = inspect.getsource(main.BrowserApp.__init__)
PAGE_SOURCE = inspect.getsource(main.BrowserApp._page_state_tick)
PAGE_SCHEDULE = inspect.getsource(main.BrowserApp._schedule_page_state_poll)
ZOOM_SOURCE = inspect.getsource(main.BrowserApp._zoom_watchdog_tick)
ZOOM_SCHEDULE = inspect.getsource(main.BrowserApp._schedule_zoom_watchdog)
POINTER_SOURCE = inspect.getsource(main.BrowserApp._poll_dwm_pointer_bridge)
FEATURE_INIT = inspect.getsource(browser_features.BrowserFeatures._init_features)
CHECKPOINT = inspect.getsource(browser_features.BrowserFeatures._checkpoint_features)


def test_page_state_poll_is_adaptive_instead_of_constant():
    assert "_page_state_active_poll_ms = 550" in INIT_SOURCE
    assert "_page_state_idle_poll_ms = 1800" in INIT_SOURCE
    assert "_page_state_empty_poll_ms = 3000" in INIT_SOURCE
    assert "active_busy = bool(" in PAGE_SOURCE
    assert "background_divisor = 3 if active_busy else 6" in PAGE_SOURCE
    assert "delay_ms=next_delay" in PAGE_SOURCE
    assert "max(100, int(delay_ms))" in PAGE_SCHEDULE


def test_zoom_watchdog_sleeps_when_extension_state_is_healthy():
    assert "_zoom_watchdog_idle_ms = 15000" in INIT_SOURCE
    assert "_zoom_watchdog_recovery_ms = 2500" in INIT_SOURCE
    assert "unstable = False" in ZOOM_SOURCE
    assert "self._zoom_watchdog_recovery_ms" in ZOOM_SOURCE
    assert "self._zoom_watchdog_idle_ms" in ZOOM_SOURCE
    assert "delay_ms=None" in ZOOM_SCHEDULE


def test_dwm_pointer_fallback_avoids_hit_testing_when_pointer_is_away():
    assert "next_delay = 48" in POINTER_SOURCE
    assert "tracking_existing = bool(self._chromium_left_button_down)" in POINTER_SOURCE
    assert "if inside_geometry or tracking_existing:" in POINTER_SOURCE
    assert POINTER_SOURCE.index("if inside_geometry or tracking_existing:") < POINTER_SOURCE.index("GetAsyncKeyState(0x01)")
    assert "if inside_geometry:" in POINTER_SOURCE
    assert POINTER_SOURCE.index("if inside_geometry:") < POINTER_SOURCE.index("WindowFromPoint(pt)")


def test_browser_state_checkpoint_backs_off_when_nothing_changed():
    assert "_checkpoint_dirty_ms = 4000" in FEATURE_INIT
    assert "_checkpoint_idle_ms = 12000" in FEATURE_INIT
    assert "wrote_state = False" in CHECKPOINT
    assert "self._checkpoint_dirty_ms if wrote_state else self._checkpoint_idle_ms" in CHECKPOINT
