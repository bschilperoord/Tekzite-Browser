from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.80"


def test_wider_tab_defaults():
    assert main.DEFAULT_CUSTOMIZATION["tab_min_width"] == 175
    assert main.DEFAULT_CUSTOMIZATION["tab_max_width"] == 330


def test_soft_and_classic_tabs_share_width_contract():
    assert "def _tab_pixel_width" in MAIN
    soft = MAIN[MAIN.index("def _create_soft_tab"):MAIN.index("def _place_new_tab_button_inline")]
    classic = MAIN[MAIN.index("def _refresh_tab_strip"):MAIN.index("def _decode_favicon_photo")]
    assert "self._tab_pixel_width(title" in soft
    assert "target_tab_width = self._tab_pixel_width" in classic
    assert "frame.pack_propagate(False)" in classic


def test_tab_width_customization_is_exposed_and_normalized():
    assert '("tab_min_width", 90, 420)' in MAIN
    assert '("tab_max_width", 120, 600)' in MAIN
    assert 'label(row, "Min width")' in MAIN
    assert 'label(row, "Max width")' in MAIN
    normalized = main._normalized_customization({"tab_min_width": 260, "tab_max_width": 180})
    assert normalized["tab_min_width"] == 260
    assert normalized["tab_max_width"] == 260

