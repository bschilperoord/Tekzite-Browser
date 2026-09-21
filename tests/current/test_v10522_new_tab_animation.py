from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.38"


def test_new_tab_records_open_animation_after_initial_tab():
    block = MAIN[MAIN.index("def _new_tab"):MAIN.index("def _capture_active_tab_state")]
    assert "had_tabs = bool(self.tabs)" in block
    assert 'self._tab_open_animation_started[tab["id"]] = time.monotonic()' in block
    assert "had_tabs and self._motion_enabled()" in block


def test_soft_tabs_expand_from_animated_width():
    block = MAIN[MAIN.index("def _create_soft_tab"):MAIN.index("def _place_new_tab_button_inline")]
    assert "initial_width, _opening_done = self._tab_open_width" in block
    assert "width=initial_width" in block
    assert "_animate_opening_tab_widget" in block


def test_classic_tabs_expand_from_animated_width():
    block = MAIN[MAIN.index("def _refresh_tab_strip"):MAIN.index("def _decode_favicon_photo")]
    assert "initial_tab_width, _opening_done = self._tab_open_width" in block
    assert "width=initial_tab_width" in block
    assert 'self._animate_opening_tab_widget(tab.get("id"), frame, target_tab_width)' in block


def test_animation_respects_global_motion_setting():
    block = MAIN[MAIN.index("def _animate_opening_tab_widget"):MAIN.index("def _draw_soft_tab")]
    assert "if not self._motion_enabled()" in block
    assert "self.root.after(12, frame)" in block

