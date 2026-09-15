from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_version_72():
    assert 'BROWSER_VERSION = "7.2"' in MAIN


def test_dwm_input_uses_native_zoom_factor():
    assert 'get_embedded_chromium_input_zoom_factor' in MAIN
    assert 'x /= zoom' in MAIN
    assert 'y /= zoom' in MAIN


def test_zoom_factor_only_active_after_native_zoom_verified():
    assert 'if not bool(session.get("native_zoom_extension_loaded"))' in NET
    assert 'return 1.0' in NET
    assert 'default_page_zoom_percent' in NET


def test_all_page_pointer_paths_share_surface_transform():
    # These handlers must continue to source their coordinates from _surface_xy.
    for name in (
        '_on_chromium_surface_press',
        '_on_chromium_surface_release',
        '_on_chromium_surface_motion',
        '_on_chromium_surface_wheel',
    ):
        pos = MAIN.find(f'def {name}')
        assert pos >= 0
        block = MAIN[pos:pos+1800]
        assert '_surface_xy(event)' in block
    # Context menu also goes through the same transform.
    assert MAIN.count('_surface_xy(event)') >= 5


def test_debug_exposes_input_zoom_mapping():
    assert 'dwm_input_zoom_factor' in NET
    assert 'dwm_input_zoom_active' in NET
