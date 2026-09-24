from pathlib import Path

import main
from browser_features import omnibox_suggestions


def test_release_is_v10548():
    assert main.BROWSER_VERSION == "10.5.80"


def test_local_suggestions_rank_bookmark_prefix_and_dedupe_url():
    items = omnibox_suggestions(
        "sta",
        bookmarks=[{"url": "https://www.startpage.com/", "title": "Startpage"}],
        visits=[{"url": "https://www.startpage.com/", "title": "Startpage Search", "visited": 999}],
        limit=6,
    )
    assert items[0]["kind"] == "bookmark"
    assert items[0]["value"] == "https://www.startpage.com/"
    assert sum(1 for item in items if item["value"] == "https://www.startpage.com/") == 1
    assert items[-1]["kind"] == "search"


def test_privacy_lockdown_still_has_session_and_open_tab_suggestions():
    items = omnibox_suggestions(
        "music",
        visits=[],
        tabs=[{
            "url": "https://music.example/current",
            "title": "Music Studio",
            "history": ["https://music.example/older"],
        }],
        recent_inputs=["music production"],
        limit=6,
    )
    values = {item["value"] for item in items}
    assert "music production" in values
    assert "https://music.example/current" in values
    assert "https://music.example/older" in values


def test_suggestion_matching_understands_host_without_scheme():
    items = omnibox_suggestions(
        "example.com",
        visits=[{"url": "https://www.example.com/path", "title": "Example", "visited": 1}],
        limit=4,
    )
    assert items[0]["value"] == "https://www.example.com/path"


def test_omnibox_popup_keeps_keyboard_focus_on_real_entry():
    source = Path(main.__file__).read_text(encoding="utf-8")
    popup = source[source.index("class _OmniboxSuggestionPopup"):source.index("class BrowserApp", source.index("class _OmniboxSuggestionPopup"))]
    assert "focus_force()" not in popup
    assert 'win.attributes("-topmost", True)' in popup
    assert 'self._inline_linux = sys.platform.startswith("linux")' in popup
    assert 'self.window.place(x=x, y=y, width=width, height=height)' in popup
    assert 'self.address.bind("<Down>"' in source
    assert 'self.address.bind("<Up>"' in source
    assert 'self.address.bind("<Tab>"' in source
    assert 'self.address.bind("<Escape>"' in source


def test_autocomplete_preference_is_local_only_and_enabled_by_default():
    assert main.DEFAULT_PREFERENCES["omnibox_suggestions_enabled"] is True
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "Local suggestions only. Typing stays on this device." in source


def test_linux_omnibox_popup_is_attached_to_browser_root():
    source = Path(main.__file__).read_text(encoding="utf-8")
    popup = source[source.index("class _OmniboxSuggestionPopup"):source.index("class BrowserApp", source.index("class _OmniboxSuggestionPopup"))]
    assert "root_x = int(app.root.winfo_rootx())" in popup
    assert "int(app.address_shell.winfo_rootx()) - root_x" in popup
    assert "win = tk.Frame(" in popup
    assert "self.window.place_configure(y=yy)" in popup
