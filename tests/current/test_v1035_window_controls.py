from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version_1035():
    assert main.BROWSER_VERSION == "10.5.33"


def test_window_controls_are_custom_canvases_with_roles():
    for token in (
        'self._make_window_control(self.window_controls, "minimize", self._minimize_window)',
        'self._make_window_control(self.window_controls, "maximize", self._toggle_maximize)',
        'self._make_window_control(self.window_controls, "close", self.on_close, close=True)',
        'button = tk.Canvas(',
        'button._tekzite_role = str(role)',
        'def _draw_window_control_icon',
        'def _redraw_window_control',
    ):
        assert token in MAIN


def test_maximize_toggle_refreshes_window_control_icon_state():
    block = MAIN[MAIN.index('def _toggle_maximize'):MAIN.index('def _minimize_window')]
    assert 'self._refresh_window_controls()' in block
    assert 'if self._window_maximized:' in block

