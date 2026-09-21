from pathlib import Path
from unittest.mock import Mock

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_active_close_is_two_phase_and_schedules_handoff():
    block = MAIN[MAIN.index("def _close_tab(self"):MAIN.index("def _close_active_tab")]
    assert "self._select_replacement_tab_chrome(replacement)" in block
    assert "self._schedule_closed_tab_handoff(replacement, target_id)" in block


def test_target_retirement_is_executor_backed():
    block = MAIN[MAIN.index("def _retire_chromium_target"):MAIN.index("def _select_replacement_tab_chrome")]
    assert "executor.submit(retire)" in block


def test_closed_pending_tab_invalidates_stale_activation():
    block = MAIN[MAIN.index("def _close_tab(self"):MAIN.index("def _close_active_tab")]
    assert "if self._tab_switch_pending_id == tab_id:" in block
    assert "self._tab_switch_serial += 1" in block
    assert "self._tab_switch_pending_id = None" in block


def test_switch_callback_runs_after_successful_commit():
    block = MAIN[MAIN.index("def _switch_tab"):MAIN.index("def _schedule_sleeping_tabs")]
    commit = "self._commit_tab_switch(current_target, ui_already_selected=ui_already_selected)"
    assert block.index(commit) < block.index("finish_callback_once()", block.index(commit))


class DeferredRoot:
    def __init__(self):
        self.idle = []
        self.timers = []
    def after_idle(self, fn):
        self.idle.append(fn)
        return len(self.idle)
    def after(self, delay, fn):
        self.timers.append((delay, fn))
        return len(self.timers)


def _close_test_app(tabs, active_id):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.tabs = tabs
    app.active_tab_id = active_id
    app._next_tab_id = max([t.get("id", 0) for t in tabs] + [0]) + 1
    app._tab_open_animation_started = {}
    app._closed_tabs = []
    app._tab_switch_pending_id = None
    app._tab_switch_serial = 0
    app._navigation_generation = 0
    app._current_document = None
    app.history = []
    app.history_index = -1
    app.root = DeferredRoot()
    app.url_var = Mock()
    app.status_var = Mock()
    app._refresh_tab_strip = Mock()
    app.update_history_buttons = Mock()
    app._show_native_canvas = Mock()
    app._focus_address = Mock()
    return app


def test_active_close_does_not_start_chromium_switch_synchronously():
    first = {"id": 1, "url": "https://first.test", "loaded": True, "chromium_target_id": "target-1", "history": [], "history_index": -1}
    second = {"id": 2, "url": "https://second.test", "loaded": True, "chromium_target_id": "target-2", "history": [], "history_index": -1}
    app = _close_test_app([first, second], 1)
    app._switch_tab = Mock(return_value=True)
    app._retire_chromium_target_when_detached = Mock()

    app._close_tab(1)

    assert app.active_tab_id == 2
    app._switch_tab.assert_not_called()
    assert app.root.timers
    assert app.root.timers[0][0] == 180


def test_last_tab_creates_blank_selection_before_deferred_surface_work():
    first = {"id": 1, "url": "https://first.test", "loaded": True, "chromium_target_id": "target-1", "history": [], "history_index": -1}
    app = _close_test_app([first], 1)
    app._retire_chromium_target_when_detached = Mock()

    app._close_tab(1)

    assert len(app.tabs) == 1
    assert app.tabs[0]["url"] == ""
    assert app.active_tab_id == app.tabs[0]["id"]
    app._show_native_canvas.assert_called_once()
    assert app.root.timers
    assert any(delay == 1800 for delay, _fn in app.root.timers)

