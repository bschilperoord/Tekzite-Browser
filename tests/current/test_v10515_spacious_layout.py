from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.132"


def test_comfortable_defaults_are_the_new_baseline():
    c = main.DEFAULT_CUSTOMIZATION
    assert c["density"] == "comfortable"
    assert c["font_size"] == 11
    assert c["tab_font_size"] == 10
    assert c["toolbar_font_size"] == 11
    assert c["tab_min_width"] == 160
    assert c["tab_max_width"] == 300
    assert c["app_bar_height"] == 50
    assert c["tab_bar_height"] == 58
    assert c["toolbar_height"] == 78
    assert c["status_bar_height"] == 36
    assert c["find_bar_height"] == 50


def test_untouched_previous_layout_migrates_to_current_spacing():
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
    assert migrated["spacing_generation"] == 5
    assert migrated["density"] == "comfortable"
    assert migrated["toolbar_height"] == 78
    assert migrated["tab_min_width"] == 160


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


def test_compact_padding_is_used_across_primary_chrome():
    assert 'gap = self._ui_padding(5)' in MAIN
    assert 'outer = self._ui_padding(9)' in MAIN
    assert 'padx=(self._ui_padding(12), self._ui_padding(8))' in MAIN
    assert 'padx=self._ui_padding(10), pady=self._ui_padding(6)' in MAIN



def test_saved_generation_three_default_layout_is_enlarged_once():
    old = {**main.DEFAULT_CUSTOMIZATION,
           "spacing_generation": 3, "font_size": 11, "menu_font_size": 10,
           "tab_font_size": 10, "toolbar_font_size": 11,
           "app_bar_height": 40, "tab_bar_height": 46, "toolbar_height": 62,
           "status_bar_height": 26, "find_bar_height": 40}
    migrated = main._normalized_customization(old)
    assert migrated["menu_font_size"] == 10
    assert migrated["status_bar_height"] == 36
    assert main._normalized_customization(migrated) == migrated
    old["menu_font_size"] = 15
    customized = main._normalized_customization(old)
    assert customized["menu_font_size"] == 15
    assert customized["status_bar_height"] == 26


def test_large_layout_keeps_its_space_with_smaller_text():
    old = {**main.DEFAULT_CUSTOMIZATION, "spacing_generation": 4,
           "font_size": 13, "menu_font_size": 12,
           "tab_font_size": 12, "toolbar_font_size": 13}
    migrated = main._normalized_customization(old)
    assert migrated["menu_font_size"] == 10
    for key in ("app_bar_height", "tab_bar_height", "toolbar_height", "status_bar_height"):
        assert migrated[key] == old[key]
    assert main._normalized_customization(migrated) == migrated
