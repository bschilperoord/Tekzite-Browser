from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BG = (ROOT / "chromium_zoom_extension" / "background.js").read_text(encoding="utf-8")
BRIDGE = (ROOT / "chromium_zoom_extension" / "bridge.js").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_version_71():
    assert 'BROWSER_VERSION = "7.1"' in MAIN


def test_zoom_mode_is_automatic_in_background_worker():
    assert '{mode: "automatic", scope: "per-tab"}' in BG
    assert '{mode: "manual", scope: "per-tab"}' not in BG


def test_zoom_mode_is_automatic_in_bridge():
    assert '{mode: "automatic", scope: "per-tab"}' in BRIDGE
    assert '{mode: "manual", scope: "per-tab"}' not in BRIDGE


def test_bridge_applies_and_reads_back_native_zoom():
    assert 'chrome.tabs.setZoom(tab.id, zoom)' in BRIDGE
    assert 'chrome.tabs.getZoom(tab.id)' in BRIDGE
    assert 'verified++' in BRIDGE


def test_bridge_reports_verified_tab_count_to_python():
    assert 'native_zoom_bridge_verified_tabs' in NET
    assert 'native_zoom_bridge_eligible_tabs' in NET
    assert 'verified == eligible' in NET


def test_dwm_still_does_not_scale_zoom():
    assert 'dwm_thumbnail_scale_x' in NET
    assert 'dwm_thumbnail_scale_y' in NET
