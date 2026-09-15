from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_version_73():
    assert 'BROWSER_VERSION = "7.3"' in MAIN


def test_variable_segoe_ui_preferred_with_fallback():
    assert 'segoe ui variable text' in MAIN.lower()
    assert 'segoe ui variable display' in MAIN.lower()
    assert 'families.get("segoe ui", "Segoe UI")' in MAIN


def test_bad_text_switches_are_removed():
    assert '"--disable-lcd-text"' in NET
    assert '"--disable-font-subpixel-positioning"' in NET
    assert '"--disable-directwrite-for-ui"' in NET
    assert 'command = [arg for arg in command if str(arg).casefold() not in _bad_typography_switches]' in NET


def test_no_global_web_css_typography_override_added():
    assert 'document.documentElement.style.font' not in NET
    assert 'webkitFontSmoothing' not in NET
    assert 'textRendering' not in NET


def test_typography_debug_fields_present():
    for key in (
        'typography_lcd_text_enabled',
        'typography_subpixel_positioning_enabled',
        'typography_directwrite_ui_enabled',
        'typography_css_override_used',
    ):
        assert key in NET
