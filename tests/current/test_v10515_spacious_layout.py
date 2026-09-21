from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.38"


def test_spacious_defaults_are_the_new_baseline():
    c = main.DEFAULT_CUSTOMIZATION
    assert c["density"] == "spacious"
    assert c["font_size"] == 11
    assert c["tab_font_size"] == 10
    assert c["toolbar_font_size"] == 11
    assert c["tab_min_width"] == 175
    assert c["tab_max_width"] == 330
    assert c["app_bar_height"] == 44
    assert c["tab_bar_height"] == 52
    assert c["toolbar_height"] == 72
    assert c["status_bar_height"] == 30
    assert c["find_bar_height"] == 46


def test_untouched_previous_layout_migrates_to_spacious():
    old = {
        "font_size": 10, "tab_font_size": 9, "toolbar_font_size": 10,
        "ui_scale": 1.0, "density": "comfortable", "tab_title_chars": 24,
        "tab_min_width": 150, "tab_max_width": 290,
        "window_corner_radius": 22, "content_corner_radius": 16, "control_corner_radius": 14,
        "app_bar_height": 38, "tab_bar_height": 44, "toolbar_height": 62,
        "status_bar_height": 26, "find_bar_height": 40,
        "window_width": 1360, "window_height": 860,
        "window_min_width": 900, "window_min_height": 600,
    }
    migrated = main._normalized_customization(old)
    assert migrated["spacing_generation"] == 2
    assert migrated["density"] == "spacious"
    assert migrated["toolbar_height"] == 72
    assert migrated["tab_min_width"] == 175


def test_user_adjusted_layout_is_not_forced_to_new_spacing():
    old = {
        "font_size": 10, "tab_font_size": 9, "toolbar_font_size": 10,
        "ui_scale": 1.0, "density": "comfortable", "tab_title_chars": 24,
        "tab_min_width": 190, "tab_max_width": 290,
        "window_corner_radius": 22, "content_corner_radius": 16, "control_corner_radius": 14,
        "app_bar_height": 38, "tab_bar_height": 44, "toolbar_height": 62,
        "status_bar_height": 26, "find_bar_height": 40,
        "window_width": 1360, "window_height": 860,
        "window_min_width": 900, "window_min_height": 600,
    }
    normalized = main._normalized_customization(old)
    assert normalized["tab_min_width"] == 190
    assert normalized["density"] == "comfortable"


def test_spacious_padding_is_used_across_primary_chrome():
    assert 'gap = self._ui_padding(7)' in MAIN
    assert 'outer = self._ui_padding(12)' in MAIN
    assert 'padx=(self._ui_padding(16), self._ui_padding(10))' in MAIN
    assert 'padx=self._ui_padding(14), pady=self._ui_padding(9)' in MAIN

