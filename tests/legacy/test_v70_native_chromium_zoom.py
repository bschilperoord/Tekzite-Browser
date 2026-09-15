from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')
NET=(ROOT/'engine'/'net.py').read_text(encoding='utf-8')
BG=(ROOT/'chromium_zoom_extension'/'background.js').read_text(encoding='utf-8')
MAN=(ROOT/'chromium_zoom_extension'/'manifest.json').read_text(encoding='utf-8')

def test_version_v70():
    assert 'BROWSER_VERSION = "7.0"' in MAIN

def test_no_css_zoom_mutation_in_runtime_zoom_path():
    block=NET[NET.index('def check_embedded_chromium_zoom'):NET.index('def _software_viewport_state')]
    assert "root.style.setProperty('zoom'" not in block
    assert 'document.documentElement.style.zoom =' not in block

def test_local_extension_is_loaded_exclusively():
    assert '--disable-extensions-except=' in NET
    assert '--load-extension=' in NET
    assert '"--disable-extensions"' not in NET

def test_extension_uses_real_chromium_zoom_api():
    assert 'chrome.tabs.setZoom(' in BG
    assert 'chrome.tabs.setZoomSettings' in BG
    assert 'chrome.tabs.onZoomChange.addListener' in BG

def test_zoom_watchdog_reapplies_after_navigation_and_zoom_change():
    assert 'chrome.tabs.onUpdated.addListener' in BG
    assert 'chrome.tabs.onCreated.addListener' in BG
    assert 'setTimeout(() => applyZoom(info.tabId)' in BG

def test_manifest_is_local_minimal_mv3():
    assert '"manifest_version": 3' in MAN
    assert '"permissions": ["tabs", "storage"]' in MAN
    assert 'host_permissions' not in MAN

def test_dwm_stays_one_to_one():
    assert 'dwm_thumbnail_scale_x' in NET
    assert 'dwm_thumbnail_scale_y' in NET
