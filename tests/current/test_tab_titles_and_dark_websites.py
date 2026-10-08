"""Regression coverage for overflowing tab titles and Chromium dark websites."""

from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_full_title_uses_available_pixels_without_character_cap(monkeypatch):
    class FakeFont:
        @staticmethod
        def measure(value):
            return sum(4 if ch == "i" else 8 for ch in value)

    monkeypatch.setattr(main.tkfont, "Font", lambda **kwargs: FakeFont())
    app = object.__new__(main.BrowserApp)
    app.root = None
    app._ui_font_family = "Test"
    app._custom = lambda name, default=None: {
        "tab_title_chars": 6, "tab_font_size": 10,
        "tab_min_width": 160, "tab_max_width": 300, "ui_scale": 1.0,
    }.get(name, default)
    title = "Kea Router Dashboard"
    assert app._tab_title_character_budget(title, 200, 10) == len(title)
    assert app._tab_pixel_width(title) == 8 * len(title) + 92
    assert app._tab_pixel_width("W" * 200) == 300
    assert app._tab_pixel_width("Pinned", pinned=True) == 48


def test_pixel_budget_uses_real_widths_not_widest_character():
    # Wide/W and narrow/i are visually different, so a worst-case 'WWW…'
    # measurement must not waste space when a title actually fits.
    def measure(value):
        return sum({"W": 14, "i": 3, "…": 9}.get(ch, 8) for ch in value)

    title = "iiiiiiWWWiiiiii"
    assert main._tab_title_pixel_budget(title, measure(title), measure) == len(title)
    assert main._tab_title_pixel_budget("i" * 24, 85, measure) == 24
    for candidate in (title, "WWWWiiWWWiii", "Router Dashboard"):
        for pixels in (20, 35, 50, 85):
            count = main._tab_title_pixel_budget(candidate, pixels, measure)
            assert 1 <= count <= len(candidate)
            if count == len(candidate):
                assert measure(candidate) <= pixels
            else:
                for offset in range(len(candidate) - count + 1):
                    excerpt = candidate[offset:offset + count]
                    visible = main._decorate_tab_title_slice(
                        excerpt, offset, len(candidate), count
                    )
                    # When even one ellipsis cannot fit, the single-character
                    # fallback is the smallest possible representation.
                    assert measure(visible) <= pixels or count == 1


def test_customization_shows_width_controls_instead_of_character_cap():
    assert 'label(row, "Max width")' in MAIN
    assert 'label(row, "Tab title chars")' not in MAIN
    assert 'tab_chars_var' not in MAIN


def test_short_tab_titles_never_scroll():
    assert main._tab_title_window("Tekzite", 20, 990.0) == "Tekzite"
    assert main._tab_title_window("", 20, 990.0) == ""


def test_long_tab_title_reaches_both_ends_and_reverses():
    title = "ABCDEFGHIJ"
    assert main._tab_title_window(title, 4, 0.0) == "ABCD"
    assert main._tab_title_window(title, 4, 0.7) == "ABCD"
    assert main._tab_title_window(title, 4, 1.1) == "BCDE"
    assert main._tab_title_window(title, 4, 2.3) == "GHIJ"
    assert main._tab_title_window(title, 4, 3.0) == "GHIJ"
    assert main._tab_title_window(title, 4, 3.6) == "EFGH"
    assert main._tab_title_window(title, 4, 4.5) == "ABCD"


def test_clipped_titles_show_ellipsis_on_hidden_edges():
    title = "Kea Router Dashboard"
    assert main._decorate_tab_title_slice(title[:14], 0, len(title), 14) == "Kea Router Da…"

    first = main._tab_title_window_state("ABCDEFGHIJ", 4, 0.0)
    middle = main._tab_title_window_state("ABCDEFGHIJ", 4, 1.1)
    last = main._tab_title_window_state("ABCDEFGHIJ", 4, 2.3)
    reverse = main._tab_title_window_state("ABCDEFGHIJ", 4, 3.6)
    assert main._decorate_tab_title_slice(*first) == "ABC…"
    assert main._decorate_tab_title_slice(*middle) == "…CD…"
    assert main._decorate_tab_title_slice(*last) == "…HIJ"
    assert main._decorate_tab_title_slice(*reverse) == "…FG…"


def test_clipped_titles_are_bounded_and_narrow_tabs_stay_clear():
    for limit in range(1, 12):
        for elapsed in (0.0, 1.1, 2.3, 3.6, 4.5):
            state = main._tab_title_window_state("ABCDEFGHIJ", limit, elapsed)
            text = main._decorate_tab_title_slice(*state)
            assert len(text) <= limit
            if len("ABCDEFGHIJ") > limit:
                assert "…" in text
    assert main._decorate_tab_title_slice("Hello", 0, 5, 5) == "Hello"
    assert main._decorate_tab_title_slice("AB", 1, 10, 2) == "…"


def test_quiet_mode_keeps_a_static_ellipsis():
    class QuietApp:
        _tab_marquee_starts = {}

        @staticmethod
        def _motion_enabled():
            return False

    text = main.BrowserApp._tab_title_display(
        QuietApp(), {"id": "tab-a"}, "Kea Router Dashboard", 14
    )
    assert text == "Kea Router Da…"


def test_narrow_tabs_keep_a_one_character_view():
    assert len(main._tab_title_window("long title", 0, 0)) == 1


def test_marquee_is_text_only_and_respects_quiet_mode():
    section = MAIN[MAIN.index("    def _tick_tab_marquee"):MAIN.index("    def _draw_soft_tab")]
    assert "self._motion_enabled()" in section
    assert "itemconfigure(" in section and "widget.configure(text=" in section
    assert "_refresh_tab_strip()" not in section
    assert "_tab_marquee_targets = {}" in MAIN
    assert "if not tab.get(\"pinned\")" in MAIN


def test_website_dark_mode_is_default_with_user_override():
    assert main.DEFAULT_PREFERENCES["force_dark_websites"] is True
    assert 'prefs["force_dark_websites"] = bool(' in MAIN
    assert 'Always use dark mode for websites (restart required)' in MAIN
    assert '"TEKZITE_DARK_WEBSITES"' in MAIN


def test_embedded_chromium_dark_features_respect_setting():
    assert "WebContentsForceDark" in ENGINE
    assert '"--force-dark-mode"' in ENGINE
    assert 'os.environ.get("TEKZITE_DARK_WEBSITES", "1") == "1"' in ENGINE
    assert 'AllowLegacyMV2Extensions' in ENGINE


def test_auth_window_uses_dark_theme_without_forcing_form_recolor():
    launch = ENGINE[ENGINE.index("def start_standalone_auth_chromium"):ENGINE.index("def ", ENGINE.index("def start_standalone_auth_chromium") + 4)]
    assert 'command.insert(-1, "--force-dark-mode")' in launch
    assert "WebContentsForceDark" not in launch
