from pathlib import Path
from unittest.mock import Mock

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.33"


def test_active_close_does_not_call_switch_inline():
    close = MAIN[MAIN.index("def _close_tab(self"):MAIN.index("def _close_active_tab")]
    active = close[close.index("if was_active:"):]
    assert "self._select_replacement_tab_chrome(replacement)" in active
    assert "self._schedule_closed_tab_handoff(replacement, target_id)" in active
    assert "self._switch_tab(" not in active


def test_handoff_has_interaction_grace_before_target_activation():
    block = MAIN[MAIN.index("def _schedule_closed_tab_handoff"):MAIN.index("def _close_tab(self")]
    assert "self.root.after(180, begin_handoff)" in block
    assert "force_activate=True" in block
    assert "ui_already_selected=True" in block


def test_presentation_fast_path_has_no_cdp_io():
    block = NET[NET.index("def set_embedded_chromium_presentation"):NET.index("def _png_dimensions")]
    fast = block[block.index("if defer_io:"):block.index("session = _EDGE_SESSION or _start_persistent_chromium_session()") ]
    assert "_start_persistent_chromium_session" not in fast
    assert "_clear_embedded_chromium_device_metrics" not in fast
    assert 'session["presentation_mode"] = mode' in fast


def test_gui_presentation_helper_defers_native_cdp_housekeeping_to_executor():
    block = MAIN[MAIN.index("def _set_chromium_presentation_fast"):MAIN.index("def _show_native_canvas")]
    assert "defer_io=True" in block
    assert "executor.submit(set_embedded_chromium_presentation" in block


def test_closed_target_retirement_waits_while_target_is_visible():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._embedded_mode = True
    app._chromium_software_mode = False
    app._chromium_frame_target_id = "old-target"
    app._retire_chromium_target = Mock()
    app.root = Mock()
    app._retire_chromium_target_when_detached("old-target")
    app._retire_chromium_target.assert_not_called()
    app.root.after.assert_called_once()


def test_native_canvas_marks_presentation_target_detached():
    block = MAIN[MAIN.index("def _show_native_canvas"):MAIN.index("def _use_chromium_software_surface_for_url")]
    assert "self._chromium_frame_target_id = None" in block

