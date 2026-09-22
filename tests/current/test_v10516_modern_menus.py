from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.47"


def test_modern_menu_factory_is_shared():
    block = MAIN[MAIN.index("def _make_modern_menu"):MAIN.index("def _show_address_context_menu")]
    assert "_AnimatedPopupMenu" in block
    assert "animated rounded popup menu" in block


def test_top_menu_buttons_are_rounded_chrome_buttons():
    block = MAIN[MAIN.index("def _build_browser_menus"):MAIN.index("def _prewarm_native_window_drag")]
    assert "button = _RoundedChromeButton(" in block
    assert "self._popup_menu_below" in block
    assert "menu_icons =" in block
    assert "tk.Menubutton(" not in block


def test_hamburger_and_context_menus_use_shared_styling():
    main_menu = MAIN[MAIN.index("def _show_main_menu"):MAIN.index("def _edit_shortcut")]
    context = MAIN[MAIN.index("def _context_menu_base"):MAIN.index("def _finish_page_context_menu")]
    assert "self._make_modern_menu" in main_menu
    assert "self._menu_item_text" in main_menu
    assert "self._make_modern_menu" in context


def test_theme_refresh_keeps_menu_palette_modern():
    assert 'browser_menu.configure(' in MAIN
    assert 'activebackground=self.ui["field_focus"]' in MAIN
    assert 'button.set_palette(' in MAIN

