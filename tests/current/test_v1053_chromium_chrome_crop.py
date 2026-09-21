from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version_1053():
    assert 'BROWSER_VERSION = "10.5.33"' in MAIN


def test_dwm_crop_no_longer_rejects_normal_browser_chrome_above_160px():
    block = NET[NET.index("candidate_chrome_h = previous_chrome_h"):NET.index("session[\"dwm_chrome_candidate\"]")]
    assert "chrome_inset_limit = min(360, max(160, int(height) - 150))" in block
    assert "source_render_y) <= chrome_inset_limit" in block
    assert "shortfall <= chrome_inset_limit" in block
    assert "source_render_y) <= 160" not in block
    assert "shortfall <= 160" not in block


def test_dwm_crop_limit_preserves_minimum_page_surface():
    # At common viewport heights this accepts the 180-220px Chromium UI seen on
    # high-DPI/full-browser layouts, but never grows past the existing 360px
    # live-render sanity ceiling.
    def limit(height):
        return min(360, max(160, int(height) - 150))

    assert limit(714) == 360
    assert 181 <= limit(714)
    assert limit(300) == 160
    assert limit(1080) == 360

