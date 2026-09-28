import inspect

import main


INIT_SOURCE = inspect.getsource(main.BrowserApp.__init__)
TOOLBAR_SOURCE = inspect.getsource(main.BrowserApp._apply_toolbar_layout)
REPACK_SOURCE = inspect.getsource(main.BrowserApp._repack_browser_chrome)
MENU_SOURCE = inspect.getsource(main._AnimatedPopupMenu.__init__)
SETTINGS_SOURCE = inspect.getsource(main.BrowserApp.show_preferences)


def test_current_default_shell_is_tighter_but_readable():
    c = main.DEFAULT_CUSTOMIZATION
    assert c["density"] == "comfortable"
    assert c["spacing_generation"] == 3
    assert (c["app_bar_height"], c["tab_bar_height"], c["toolbar_height"]) == (40, 46, 62)
    assert (c["status_bar_height"], c["find_bar_height"]) == (26, 40)
    assert (c["tab_min_width"], c["tab_max_width"]) == (160, 300)


def test_tabs_and_omnibar_share_a_tight_boundary():
    assert "(self._ui_padding(6), self._ui_padding(2))" in INIT_SOURCE
    assert "adjacent_pad = self._ui_padding(3)" in TOOLBAR_SOURCE
    assert "far_pad = self._ui_padding(8)" in TOOLBAR_SOURCE
    assert "(self._ui_padding(6), self._ui_padding(2))" in REPACK_SOURCE


def test_toolbar_controls_use_compact_common_spacing():
    assert "gap = self._ui_padding(5)" in TOOLBAR_SOURCE
    assert "outer = self._ui_padding(9)" in TOOLBAR_SOURCE
    assert "padx=(self._ui_padding(9), outer)" in TOOLBAR_SOURCE


def test_popup_menus_are_tighter_too():
    assert "self._outer_pad = max(5, app._ui_padding(6))" in MENU_SOURCE
    assert "self._row_h = max(30, app._ui_padding(32))" in MENU_SOURCE
    assert "self._separator_h = max(6, app._ui_padding(7))" in MENU_SOURCE


def test_settings_shell_is_compacted():
    assert 'shell = tk.Frame(win, bg=self.ui["bg"], padx=18, pady=14)' in SETTINGS_SOURCE
    assert 'pady=(9, 4)' in SETTINGS_SOURCE
    assert 'box.pack(fill="x", pady=(0, 4))' in SETTINGS_SOURCE


def test_user_customized_generation_two_layout_stays_custom():
    custom = {
        **main.DEFAULT_CUSTOMIZATION,
        "spacing_generation": 2,
        "density": "spacious",
        "toolbar_height": 68,
        "tab_bar_height": 49,
    }
    normalized = main._normalized_customization(custom)
    assert normalized["spacing_generation"] == 3
    assert normalized["density"] == "spacious"
    assert normalized["toolbar_height"] == 68
    assert normalized["tab_bar_height"] == 49
