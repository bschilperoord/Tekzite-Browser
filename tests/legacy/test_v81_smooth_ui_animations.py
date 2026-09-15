from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_version_81():
    assert 'BROWSER_VERSION = "8.1"' in MAIN


def test_nonblocking_animation_helpers_exist():
    assert 'def _animate_widget_color' in MAIN
    assert 'def _animate_widget_height' in MAIN
    assert 'self.root.after(interval' in MAIN
    assert 'time.sleep(' not in MAIN[MAIN.index('def _animate_widget_color'):MAIN.index('def _active_tab')]


def test_find_bar_is_animated():
    block = MAIN[MAIN.index('def _show_find_bar'):MAIN.index('def _find_in_page')]
    assert '_animate_widget_height(self.find_bar, 0, 40' in block
    assert '_animate_widget_height(self.find_bar, current, 0' in block


def test_hover_animations_are_coalesced():
    assert 'self._ui_animation_jobs[key] = token' in MAIN
    assert 'if self._ui_animation_jobs.get(key) != token' in MAIN
    assert '_animate_widget_color(self.new_tab_button' in MAIN


def test_loading_spinner_stays_in_tk_shell():
    assert 'def _animate_loading_icon' in MAIN
    assert 'self._loading_spinner_frames' in MAIN
    block = MAIN[MAIN.index('def _animate_loading_icon'):MAIN.index('def _active_tab')]
    assert 'Input.dispatchMouseEvent' not in block
    assert 'Dwm' not in block


def test_preferences_fade_in_exists():
    assert 'def _animate_toplevel_in' in MAIN
    assert 'self._animate_toplevel_in(win, 145)' in MAIN
