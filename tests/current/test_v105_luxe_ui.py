from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_is_v1050():
    assert main.BROWSER_VERSION == "10.5.80"


def test_luxe_defaults_enable_soft_tabs_and_traffic_lights():
    custom = main._normalized_customization({})
    assert custom["preset"] == "Aurora Glass"
    assert custom["tab_style"] == "soft"
    assert custom["window_control_style"] == "traffic_lights"
    assert custom["colors"]["bg"] == main.CUSTOMIZATION_PRESETS["Aurora Glass"]["bg"]


def test_luxe_presets_exist():
    assert "Aurora Glass" in main.CUSTOMIZATION_PRESETS
    assert "OLED Neon" in main.CUSTOMIZATION_PRESETS


def test_soft_tabs_are_canvas_rendered_and_rounded():
    for token in (
        "def _rounded_canvas_rect",
        "def _draw_soft_tab",
        "def _create_soft_tab",
        'if self._custom("tab_style", "soft") == "soft":',
        'smooth=True, splinesteps=24',
    ):
        assert token in MAIN


def test_traffic_light_window_controls_are_real_drawn_controls():
    for token in (
        '"close": "#ff5f57"',
        '"minimize": "#febc2e"',
        '"maximize": "#28c840"',
        '("close", "minimize", "maximize")',
        'window_control_style_var',
    ):
        assert token in MAIN


def test_luxe_styles_normalize_safely():
    custom = main._normalized_customization({"window_control_style": "bad", "tab_style": "bad"})
    assert custom["window_control_style"] == "traffic_lights"
    assert custom["tab_style"] == "soft"

