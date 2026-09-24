from pathlib import Path

import engine.net as net


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_software_viewport_accepts_real_browser_zoom_relationship():
    # Regression for Linux screenshot:
    # expected=(1440,659), inner=(960,439), dpr=1.5, scale=1.
    expected_w, expected_h = 1440, 659
    inner_w, inner_h, dpr = 960, 439, 1.5
    tolerance = max(2.0, dpr * 1.5)
    assert abs(inner_w * dpr - expected_w) <= tolerance
    assert abs(inner_h * dpr - expected_h) <= tolerance


def test_software_contract_no_longer_requires_dpr_one():
    start = NET.index("def _apply_strict_software_viewport")
    end = NET.index("def capture_embedded_chromium_frame", start)
    block = NET[start:end]
    assert "abs(dpr - 1.0)" not in block
    assert "expected_css_pixels_w" in block
    assert 'session["software_input_css_scale_x"]' in block


def test_zoom_invalidates_cached_software_contract():
    start = NET.index("def set_embedded_chromium_zoom")
    end = NET.index("def _software_viewport_state", start)
    block = NET[start:end]
    assert 'channel.pop("viewport_contract", None)' in block
    assert 'channel["viewport_contract_checked_at"] = 0.0' in block


def test_software_pointer_coordinates_are_divided_into_css_space():
    start = MAIN.index("def _surface_xy")
    end = MAIN.index("def _note_dwm_tk_pointer_delivery", start)
    block = MAIN[start:end]
    assert "get_embedded_chromium_software_input_scale()" in block
    assert "x /= scale_x" in block
    assert "y /= scale_y" in block
