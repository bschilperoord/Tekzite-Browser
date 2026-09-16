from pathlib import Path

MAIN = Path('main.py').read_text(encoding='utf-8')
NET = Path('engine/net.py').read_text(encoding='utf-8')


def test_v94_version():
    assert 'BROWSER_VERSION = "10.5.0"' in MAIN


def test_browser_level_cdp_is_persistent():
    assert 'def _get_persistent_browser_cdp_channel' in NET
    block = NET[NET.index('def _browser_cdp_call'):NET.index('def create_embedded_chromium_target')]
    assert '_get_persistent_browser_cdp_channel' in block
    assert '/json/version' not in block
    assert 'ws.close()' not in block


def test_hot_navigation_uses_persistent_control_lane():
    block = NET[NET.index('def navigate_embedded_chromium'):NET.index('def _windows_descendant_pids')]
    assert 'purpose="control"' in block
    assert '"Page.enable"' not in block
    assert '_open_devtools_websocket' not in block


def test_bootstrap_skips_unneeded_page_socket_and_default_zoom():
    block = NET[NET.index('def create_embedded_chromium_target'):NET.index('def activate_embedded_chromium_target')]
    assert 'bootstrap_socket_skipped' in block
    assert 'if inherited_zoom != 100' in block
    assert 'target_zoom_bootstrap_skipped_default' in block
