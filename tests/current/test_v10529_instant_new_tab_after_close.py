from pathlib import Path
from unittest.mock import Mock

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.54"


def test_new_tab_preempts_pending_tab_switch_before_selection():
    block = MAIN[MAIN.index("def _new_tab(self"):MAIN.index("def _capture_active_tab_state")]
    assert "if switch:" in block
    assert "self._cancel_pending_tab_switch()" in block
    assert block.index("self._cancel_pending_tab_switch()") < block.index("self.active_tab_id = tab[\"id\"]")


def test_stale_switch_poll_stops_before_wait_loop():
    block = MAIN[MAIN.index("def _switch_tab(self"):MAIN.index("def _schedule_sleeping_tabs")]
    stale = block.index("if serial != self._tab_switch_serial:")
    wait = block.index("if not future.done():")
    assert stale < wait
    stale_block = block[stale:wait]
    assert "finish_callback_once()" in stale_block
    assert "return" in stale_block


def test_pending_switch_cancel_advances_serial_and_clears_pending():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._tab_switch_serial = 7
    app._tab_switch_pending_id = 42
    future = Mock()
    app._tab_switch_future = future
    assert app._cancel_pending_tab_switch() is True
    assert app._tab_switch_serial == 8
    assert app._tab_switch_pending_id is None
    future.cancel.assert_called_once_with()


def test_no_pending_switch_is_a_noop():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._tab_switch_serial = 7
    app._tab_switch_pending_id = None
    app._tab_switch_future = None
    assert app._cancel_pending_tab_switch() is False
    assert app._tab_switch_serial == 7

