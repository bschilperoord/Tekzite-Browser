from types import SimpleNamespace
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value


def _fake_app(*, find_visible=False, find_text=""):
    calls = []
    app = SimpleNamespace(
        _find_bar_visible=find_visible,
        find_var=_Var(find_text),
    )
    methods = {
        "_show_about": "about",
        "_new_tab": "new-tab",
        "_show_find_bar": "find-bar",
        "_focus_address": "address",
        "_reload_current": "reload",
        "_show_site_info": "site-info",
        "_show_downloads": "downloads",
        "_show_privacy_shield": "privacy-shield",
        "_show_file_menu_from_keyboard": "file-menu",
        "_toggle_fullscreen": "fullscreen",
        "inspect_html": "inspect-html",
    }
    for name, label in methods.items():
        setattr(app, name, lambda _label=label: calls.append(_label) or "break")
    app._find_in_page = lambda backwards=False: calls.append("find-prev" if backwards else "find-next")
    return app, calls


def test_all_function_keys_have_browser_actions():
    expected = {
        1: "about",
        2: "new-tab",
        3: "find-bar",
        4: "address",
        5: "reload",
        6: "address",
        7: "site-info",
        8: "downloads",
        9: "privacy-shield",
        10: "file-menu",
        11: "fullscreen",
        12: "inspect-html",
    }
    for number, label in expected.items():
        app, calls = _fake_app()
        result = main.BrowserApp._dispatch_browser_function_key(app, number)
        assert result == "break"
        assert calls == [label]


def test_f3_reuses_find_bar_and_shift_reverses_direction():
    app, calls = _fake_app(find_visible=True, find_text="needle")
    assert main.BrowserApp._dispatch_browser_function_key(app, 3) == "break"
    assert calls == ["find-next"]

    app, calls = _fake_app(find_visible=True, find_text="needle")
    assert main.BrowserApp._dispatch_browser_function_key(app, 3, shift=True) == "break"
    assert calls == ["find-prev"]


def test_modified_os_function_keys_are_not_stolen_but_ctrl_f5_refreshes():
    app, calls = _fake_app()
    assert main.BrowserApp._dispatch_browser_function_key(app, 4, alt=True) is None
    assert calls == []

    app, calls = _fake_app()
    assert main.BrowserApp._dispatch_browser_function_key(app, 5, control=True) == "break"
    assert calls == ["reload"]

    app, calls = _fake_app()
    assert main.BrowserApp._dispatch_browser_function_key(app, 12, control=True) is None
    assert calls == []


def test_root_software_and_dwm_paths_share_function_key_dispatcher():
    assert 'for _fkey in range(1, 13):' in MAIN
    assert 'self._dispatch_browser_function_key(n, event=event)' in MAIN
    assert 'if keysym.startswith("F") and keysym[1:].isdigit():' in MAIN
    assert 'if 0x70 <= vk <= 0x7B:' in MAIN
    assert 'vk - 0x6F, shift=shift, control=control, alt=alt' in MAIN


def test_dwm_held_function_keys_are_one_shot():
    assert 'down[vk] = float("inf") if 0x70 <= vk <= 0x7B else now + 0.42' in MAIN


def test_visible_menus_advertise_core_function_keys():
    for accelerator in (
        '"Ctrl+T / F2"', '"Ctrl+F / F3"', '"Ctrl+R / F5"',
        '"Ctrl+L / F6"', '"F7"', '"Ctrl+J / F8"', '"F9"',
        '"Ctrl+U / F12"', '"F1"',
    ):
        assert accelerator in MAIN



def test_reload_uses_committed_tab_url_not_unsubmitted_omnibox_text():
    calls = []
    app = SimpleNamespace(
        url_var=_Var("https://half-typed.invalid/"),
        _active_tab=lambda: {"url": "https://example.test/current"},
        _homepage_url=lambda: "https://startpage.com/",
        navigate_to=lambda url, **kwargs: calls.append((url, kwargs)),
    )
    main.BrowserApp._reload_current(app)
    assert calls == [(
        "https://example.test/current",
        {"add_history": False, "reuse_existing": False},
    )]
