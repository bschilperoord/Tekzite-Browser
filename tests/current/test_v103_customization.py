import json
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_is_v1030():
    assert main.BROWSER_VERSION == "10.5.38"


def test_customization_defaults_cover_every_palette_role():
    custom = main._normalized_customization({})
    assert set(custom["colors"]) == set(main.UI_COLOR_DEFAULTS)
    assert custom["toolbar_order"] == list(main.TOOLBAR_ITEM_IDS)
    assert all(custom["toolbar_visible"].values())
    assert custom["tab_position"] == "above_toolbar"


def test_customization_normalization_clamps_and_deduplicates():
    custom = main._normalized_customization({
        "colors": {"accent": "not-a-color", "bg": "#ABCDEF"},
        "font_size": 999,
        "ui_scale": 9,
        "toolbar_order": ["menu", "menu", "bogus", "back"],
        "toolbar_visible": {"home": False},
        "tab_position": "sideways",
    })
    assert custom["colors"]["accent"] == main.UI_COLOR_DEFAULTS["accent"]
    assert custom["colors"]["bg"] == "#abcdef"
    assert custom["font_size"] == 22
    assert custom["ui_scale"] == 1.6
    assert custom["toolbar_order"][:2] == ["menu", "back"]
    assert set(custom["toolbar_order"]) == set(main.TOOLBAR_ITEM_IDS)
    assert custom["toolbar_visible"]["home"] is False
    assert custom["tab_position"] == "above_toolbar"


def test_customization_center_and_recovery_shortcut_are_wired():
    assert "def _show_customize_browser" in MAIN
    assert 'Customize Tekzite…' in MAIN
    assert '<Control-Shift-comma>' in MAIN
    assert '<Control-Shift-Alt-R>' in MAIN
    assert 'Ctrl+L remains an escape hatch' in MAIN


def test_toolbar_is_orderable_and_individually_visible():
    assert '"toolbar_order": list(TOOLBAR_ITEM_IDS)' in MAIN
    assert '"toolbar_visible": {item: True for item in TOOLBAR_ITEM_IDS}' in MAIN
    assert 'def _apply_toolbar_layout' in MAIN
    assert 'for item in order:' in MAIN


def test_tabs_and_chrome_visibility_are_customizable():
    for token in (
        '"show_app_bar": True', '"show_menu_bar": True', '"show_window_controls": True',
        '"show_tab_bar": True', '"show_tab_favicons": True', '"show_tab_close_buttons": True',
        '"show_tab_group_chips": True', '"show_tab_active_indicator": True', '"show_scrollbar": True',
        '"show_chrome_separator": True', '"show_status_version": True',
    ):
        assert token in MAIN


def test_search_url_template_drives_omnibox_search():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.preferences = {
        **main.DEFAULT_PREFERENCES,
        "search_url_template": "https://search.example/?q={query}",
    }
    assert app.normalize_url("two words") == "https://search.example/?q=two+words"
    assert app.normalize_url("hello") == "https://search.example/?q=hello"


def test_preset_export_format_is_versioned_json():
    assert '"format": "tekzite-customization"' in MAIN
    assert '"version": 1' in MAIN
    assert 'def import_preset()' in MAIN
    assert 'def export_preset()' in MAIN

