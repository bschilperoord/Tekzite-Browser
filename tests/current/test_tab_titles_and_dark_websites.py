"""Regression coverage for overflowing tab titles and Chromium dark websites."""

from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


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
