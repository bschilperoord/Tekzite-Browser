from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')
NET=(ROOT/'engine'/'net.py').read_text(encoding='utf-8')

def test_version(): assert 'BROWSER_VERSION = "6.4"' in MAIN

def test_zoom_still_bootstraps_new_documents():
    assert 'Page.addScriptToEvaluateOnNewDocument' in NET
    assert "root.style.setProperty('zoom', factor, 'important')" in NET

def test_no_mutation_observer_zoom_loop():
    fn=NET[NET.index('def set_embedded_chromium_zoom'):]
    fn=fn[:fn.index('\n\ndef ', 10)]
    source = fn[fn.index('source = f\"\"\"'):fn.index('try:', fn.index('source = f\"\"\"'))]
    assert 'new MutationObserver' not in source

def test_no_youtube_specific_zoom_hack():
    fn=NET[NET.index('def set_embedded_chromium_zoom'):]
    fn=fn[:fn.index('\n\ndef ', 10)]
    assert 'ytd-popup-container' not in fn
    assert 'youtube.com' not in fn

def test_debug_strategy_recorded():
    assert 'document-once-css-zoom' in NET
