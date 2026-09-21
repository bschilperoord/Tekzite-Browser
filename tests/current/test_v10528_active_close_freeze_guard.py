from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_active_close_keeps_dwm_mounted_during_immediate_ui_selection():
    block = MAIN[MAIN.index("def _close_tab(self"):MAIN.index("def _close_active_tab")]
    active = block[block.index("if was_active:"):]
    assert "self._show_native_canvas()" not in active
    assert "self._select_replacement_tab_chrome(replacement)" in active
    assert "self._schedule_closed_tab_handoff(replacement, target_id)" in active


def test_switch_has_bounded_watchdog():
    block = MAIN[MAIN.index("def _switch_tab(self"):MAIN.index("def _schedule_sleeping_tabs")]
    assert "switch_started = time.monotonic()" in block
    assert "time.monotonic() - switch_started >= 4.0" in block
    assert "future.cancel()" in block


def test_activation_hot_path_has_no_synchronous_dwm_barriers_or_shared_cdp():
    block = NET[NET.index("def activate_embedded_chromium_target"):NET.index("def close_embedded_chromium_target")]
    assert "DwmFlush()" not in block
    assert "UpdateWindow(" not in block
    assert "RDW_INVALIDATE | RDW_ALLCHILDREN" in block
    assert "_browser_cdp_call(" not in block
    assert '_devtools_target_http_command(session, "activate"' in block


def test_activation_budget_is_short_and_bounded():
    block = NET[NET.index("def activate_embedded_chromium_target"):NET.index("def close_embedded_chromium_target")]
    assert "_start_persistent_chromium_session(timeout=3.0)" in block
    assert "timeout=0.35" in block
    assert "timeout=0.45" in block

