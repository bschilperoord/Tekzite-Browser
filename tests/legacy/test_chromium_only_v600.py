from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
ENGINE_FILES = {p.name for p in (ROOT / 'engine').glob('*.py')}


def test_version_v600():
    assert 'BROWSER_VERSION = "6.0"' in MAIN


def test_only_chromium_backend_remains():
    assert ENGINE_FILES == {'__init__.py', 'net.py'}


def test_no_custom_renderer_imports():
    banned = [
        'engine.html_parser', 'engine.layout', 'engine.painter', 'engine.tinyjs',
        'engine.css_parser', 'engine.style', 'engine.webfonts', 'engine.document'
    ]
    for name in banned:
        assert name not in MAIN


def test_navigation_is_chromium_only():
    start = MAIN.index('    def navigate_to(')
    tail = MAIN[start:]
    next_def = tail.index('\n    def ', len('    def navigate_to('))
    block = tail[:next_def]
    assert 'self._navigate_embedded(url, add_history, generation)' in block
    assert 'prepare_navigation' not in block
    assert 'layout_document' not in block


def test_preferences_cannot_select_native_renderer():
    assert '"renderer": "chromium"' in MAIN
    assert 'combo(renderer, ["chromium"])' in MAIN
    assert 'combo(renderer, ["auto", "native", "chromium"])' not in MAIN


def test_debug_is_chromium_only():
    assert 'web_engine: Chromium only' in MAIN
    assert 'CHROMIUM / DWM DEBUG' in MAIN
