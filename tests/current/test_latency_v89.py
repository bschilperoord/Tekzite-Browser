from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_release_is_v89():
    assert 'BROWSER_VERSION = "10.5.32"' in MAIN


def test_devtools_sockets_disable_nagle():
    assert 'socket.TCP_NODELAY' in NET
    assert 'socket.IPPROTO_TCP' in NET


def test_cursor_has_independent_lane_and_worker():
    assert '_chromium_cursor_executor = ThreadPoolExecutor' in MAIN
    cursor = NET[NET.index('def get_embedded_chromium_cursor'):NET.index('def get_embedded_chromium_context')]
    assert 'purpose="cursor"' in cursor
    assert '_chromium_cursor_executor.submit' in MAIN


def test_click_release_has_no_redundant_focus_probe():
    block = MAIN[MAIN.index('def _on_chromium_surface_release'):MAIN.index('def _on_chromium_surface_drag')]
    assert 'focus_embedded_chromium_point' not in block
    assert 'mouseReleased' in block
