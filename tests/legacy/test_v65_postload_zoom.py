from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT/'main.py').read_text(encoding='utf-8')
NET = (ROOT/'engine'/'net.py').read_text(encoding='utf-8')

def test_version():
    assert 'BROWSER_VERSION = "6.5"' in MAIN

def test_no_pre_navigation_zoom_apply():
    assert 'session["preferences_zoom_pre_navigation_applied"] = False' in NET
    block = NET[NET.index('def open_embedded_chromium'):]
    pre = block.index('session["preferences_zoom_pre_navigation_applied"] = False')
    nav = block.index('navigate_embedded_chromium(')
    assert pre < nav

def test_no_new_document_zoom_script():
    zoom = NET[NET.index('def set_embedded_chromium_zoom'):NET.index('def _software_viewport_state')]
    assert 'Page.addScriptToEvaluateOnNewDocument' not in zoom
    assert 'Page.removeScriptToEvaluateOnNewDocument' not in zoom

def test_zoom_defers_while_loading():
    zoom = NET[NET.index('def set_embedded_chromium_zoom'):NET.index('def _software_viewport_state')]
    assert "if (state === 'loading') return {{applied:false, state}};" in zoom
    assert 'page_zoom_deferred_while_loading' in zoom

def test_retry_window_waits_for_heavy_spa():
    assert 'for delay in (120, 350, 900, 1800, 3500, 6000):' in MAIN
