from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_cursor_probe_function_exists():
    assert 'def get_embedded_chromium_cursor' in NET
    assert 'getComputedStyle(el).cursor' in NET
    assert "return 'pointer'" in NET
    assert "return 'text'" in NET


def test_dwm_input_plane_binds_leave_reset():
    assert 'self.edge_host.bind("<Leave>", self._on_chromium_surface_leave)' in MAIN
    assert 'self._apply_chromium_cursor("default")' in MAIN


def test_cursor_probe_is_single_flight_and_coalesced():
    assert 'self._chromium_cursor_future is not None and not self._chromium_cursor_future.done()' in MAIN
    assert 'self._chromium_cursor_point = (x, y)' in MAIN
    assert 'self._request_chromium_cursor_probe()' in MAIN


def test_cursor_mapping_contains_browser_basics():
    assert '"pointer": "hand2"' in MAIN
    assert '"text": "xterm"' in MAIN
    assert '"move": "fleur"' in MAIN
    assert '"ew-resize": "sb_h_double_arrow"' in MAIN
    assert '"ns-resize": "sb_v_double_arrow"' in MAIN


def test_cursor_probe_uses_same_page_coordinates_as_hover():
    assert 'get_embedded_chromium_cursor, x, y' in MAIN
    assert 'dispatch_embedded_chromium_mouse, "mouseMoved", x, y' in MAIN
