from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.80"


def test_closed_target_destruction_is_debounced_away_from_plus_click():
    block = MAIN[MAIN.index("def _queue_closed_target_retirement"):MAIN.index("def _retire_chromium_target(self")]
    assert "queue.add(target_id)" in block
    assert "self.root.after(max(250, int(delay_ms)), drain)" in block


def test_new_tab_pushes_renderer_retirement_out_of_hot_path():
    block = MAIN[MAIN.index("def _new_tab(self"):MAIN.index("def _capture_active_tab_state")]
    assert "self._defer_closed_target_retirement(1800)" in block
    assert "self._cancel_pending_tab_switch()" in block


def test_close_handoff_has_cancelable_interaction_grace():
    block = MAIN[MAIN.index("def _schedule_closed_tab_handoff"):MAIN.index("def _close_tab(self")]
    assert "self.root.after(180, begin_handoff)" in block
    assert "if not current.get(\"chromium_target_id\")" in block
    assert "self._queue_closed_target_retirement(tid, 1800)" in block


def test_dwm_hide_prefers_async_win32_call():
    block = MAIN[MAIN.index("def _hide_dwm_host"):MAIN.index("def _set_chromium_presentation_fast")]
    assert "ShowWindowAsync" in block


def test_last_tab_close_does_not_wait_before_showing_blank_tab():
    block = MAIN[MAIN.index("def _close_tab(self"):MAIN.index("def _close_active_tab")]
    last = block[block.index("if not self.tabs:"):block.index("if was_active:")]
    assert "self._show_native_canvas()" in last
    assert "self._queue_closed_target_retirement(target_id, 1800)" in last
    assert "root.after(250" not in last


def test_homepage_new_tab_paints_before_navigation():
    block = MAIN[MAIN.index("def _new_tab(self"):MAIN.index("def _capture_active_tab_state")]
    assert "open_homepage_if_still_current" in block
    assert "self.root.after(16 if self._motion_enabled() else 1" in block

