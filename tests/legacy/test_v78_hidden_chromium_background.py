from pathlib import Path

NET = Path('engine/net.py').read_text(encoding='utf-8')
MAIN = Path('main.py').read_text(encoding='utf-8')

def test_version_78():
    assert 'BROWSER_VERSION = "7.8"' in MAIN

def test_initial_chromium_launch_is_offscreen():
    block = NET[NET.index('def _initial_chromium_launch_geometry'):NET.index('def open_embedded_chromium')]
    assert 'return (-32000, -32000,' in block

def test_dwm_source_moves_before_show():
    block = NET[NET.index('SW_SHOWNA = 8'):NET.index('resized_rect = wintypes.RECT()', NET.index('SW_SHOWNA = 8'))]
    assert block.index('user32.SetWindowPos(') < block.index('user32.ShowWindow(')
    assert 'dwm_source_prepositioned_before_show' in block

def test_aux_presenters_are_hidden():
    block = NET[NET.index('def _park_chromium_top_level_presenters'):NET.index('def _position_native_chromium_overlay')]
    assert 'if hwnd_i != source_hwnd:' in block
    assert 'user32.ShowWindow(hwnd, 0)' in block

def test_dwm_source_still_mapped_for_thumbnail():
    block = NET[NET.index('def _position_native_chromium_overlay'):NET.index('def attach_embedded_chromium')]
    assert 'user32.ShowWindow(_as_hwnd(source), SW_SHOWNA)' in block
    assert 'DwmRegisterThumbnail' in block
