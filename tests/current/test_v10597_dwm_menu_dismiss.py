import inspect

import main


class _FakePopup:
    def __init__(self, posted=True):
        self.posted = posted
        self.dismissed = False
        self.include_parent = None

    def is_posted(self):
        return self.posted

    def dismiss(self, include_parent=False):
        self.dismissed = True
        self.include_parent = include_parent


def test_page_click_dismisses_active_popup_menu(monkeypatch):
    monkeypatch.setattr(main, "_AnimatedPopupMenu", _FakePopup)
    app = main.BrowserApp.__new__(main.BrowserApp)
    popup = _FakePopup(posted=True)
    app._active_popup_menu = popup

    assert app._dismiss_active_popup_menu_for_page_click() is True
    assert popup.dismissed is True
    assert popup.include_parent is False


def test_page_click_ignores_unposted_popup(monkeypatch):
    monkeypatch.setattr(main, "_AnimatedPopupMenu", _FakePopup)
    app = main.BrowserApp.__new__(main.BrowserApp)
    popup = _FakePopup(posted=False)
    app._active_popup_menu = popup

    assert app._dismiss_active_popup_menu_for_page_click() is False
    assert popup.dismissed is False


def test_dwm_and_tk_page_press_share_menu_dismiss_path():
    source = inspect.getsource(main.BrowserApp._dispatch_chromium_press_xy)
    dismiss_at = source.index("self._dismiss_active_popup_menu_for_page_click()")
    dedupe_at = source.index("if self._chromium_left_button_down:")
    cdp_at = source.index('dispatch_embedded_chromium_mouse, "mousePressed"')

    assert dismiss_at < dedupe_at < cdp_at


def test_native_dwm_pointer_bridge_enters_shared_press_dispatch():
    source = inspect.getsource(main.BrowserApp._poll_dwm_pointer_bridge)
    assert "self._dispatch_chromium_press_xy(x, y)" in source
