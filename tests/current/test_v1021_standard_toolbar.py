from pathlib import Path

import main
from engine import net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version_1021():
    assert main.BROWSER_VERSION == "10.5.2"


def test_standard_browser_toolbar_controls_are_present():
    for token in (
        'self.back_button = chrome_button(self.toolbar, self._toolbar_text("back")',
        'self.forward_button = chrome_button(self.toolbar, self._toolbar_text("forward")',
        'self.reload_button = chrome_button(self.toolbar, self._toolbar_text("reload")',
        'self.home_button = chrome_button(self.toolbar, self._toolbar_text("home")',
        'self.bookmark_button = tk.Button(',
        'self.downloads_button = chrome_button(self.toolbar, self._toolbar_text("downloads")',
        'self.main_menu_button = chrome_button(self.toolbar, self._toolbar_text("menu")',
        'self._apply_toolbar_layout()',
    ):
        assert token in MAIN


def test_reload_button_becomes_stop_while_loading():
    assert 'self.reload_button.configure(text=self._toolbar_text("reload", loading=loading))' in MAIN
    assert 'if tab.get("loading"):' in MAIN[MAIN.index('def _reload_or_stop_current'):MAIN.index('def _go_home')]


def test_bookmark_star_is_a_real_toggle():
    block = MAIN[MAIN.index('def _toggle_current_bookmark'):MAIN.index('def _bookmark_current_page')]
    assert 'Bookmark saved' in block
    assert 'Bookmark removed' in block
    assert 'text="★" if bookmarked else "☆"' in MAIN


def test_debug_controls_are_not_packed_into_primary_toolbar():
    block = MAIN[MAIN.index('self.main_menu_button ='):MAIN.index('# v8.0 find-in-page bar')]
    assert 'Copy Full Debug' not in block
    assert 'debug_group.pack' not in block


def test_stop_loading_uses_cdp_page_stop_loading(monkeypatch):
    calls = []
    monkeypatch.setattr(net, '_start_persistent_chromium_session', lambda timeout: {'target_id': 'tab-1'})
    def fake_call(session, method, params, **kwargs):
        calls.append((method, params, kwargs))
        return {}
    monkeypatch.setattr(net, '_persistent_page_cdp_call', fake_call)
    assert net.stop_embedded_chromium_loading(target_id='tab-1', timeout=1.0) is True
    assert calls[0][0] == 'Page.stopLoading'
    assert calls[0][2]['target_id'] == 'tab-1'
