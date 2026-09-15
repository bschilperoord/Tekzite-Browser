from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_version_77():
    assert 'BROWSER_VERSION = "7.7"' in MAIN


def test_b1_motion_bound_on_both_surfaces():
    assert 'self.edge_host.bind("<B1-Motion>", self._on_chromium_surface_drag)' in MAIN
    assert 'self.chromium_surface.bind("<B1-Motion>", self._on_chromium_surface_drag)' in MAIN


def test_drag_sends_held_left_mousemove():
    block = MAIN[MAIN.index('def _on_chromium_surface_drag'):MAIN.index('def _on_chromium_surface_motion')]
    assert '"mouseMoved"' in block
    assert 'button="left", buttons=1' in block
    assert '_surface_xy(event)' in block


def test_press_and_release_track_buttons():
    press = MAIN[MAIN.index('def _on_chromium_surface_press'):MAIN.index('def _on_chromium_surface_release')]
    release = MAIN[MAIN.index('def _on_chromium_surface_release'):MAIN.index('def _on_chromium_surface_drag')]
    assert 'buttons=1' in press
    assert 'buttons=0' in release
    assert 'if not was_drag:' in release
    assert 'focus_embedded_chromium_point' in release


def test_cdp_dispatch_supports_buttons_bitfield():
    block = NET[NET.index('def dispatch_embedded_chromium_mouse'):NET.index('def get_embedded_chromium_cursor')]
    assert 'buttons: int = None' in block
    assert 'params["buttons"] = int(buttons)' in block
