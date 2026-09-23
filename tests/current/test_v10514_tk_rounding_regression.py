from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.73"


def test_outer_window_does_not_create_a_tk_round_rect_region():
    block = MAIN[MAIN.index("def _apply_window_rounding"):MAIN.index("def _apply_dwm_host_rounding")]
    assert "CreateRoundRectRgn" not in block
    assert "DwmSetWindowAttribute" in block
    assert "GA_ROOT = 2" in block


def test_outer_window_clears_any_legacy_region_before_native_rounding():
    block = MAIN[MAIN.index("def _apply_window_rounding"):MAIN.index("def _apply_dwm_host_rounding")]
    assert "SetWindowRgn(wintypes.HWND(hwnd), None, True)" in block


def test_dwm_page_surface_can_still_have_independent_rounded_region():
    block = MAIN[MAIN.index("def _apply_dwm_host_rounding"):MAIN.index("def _apply_frameless_app_style")]
    assert "CreateRoundRectRgn" in block
    assert "SetWindowRgn" in block

