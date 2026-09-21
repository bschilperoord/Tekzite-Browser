import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import main
from engine import net


def test_release_is_v1011():
    assert main.BROWSER_VERSION == '10.5.42'


def test_chromium_bootstrap_is_serialized():
    source = Path(net.__file__).read_text(encoding='utf-8')
    assert '_EDGE_SESSION_LOCK = threading.RLock()' in source
    assert 'with _EDGE_SESSION_LOCK:' in source
    with patch.object(net, '_start_persistent_chromium_session_unlocked', return_value={'ok': True}) as inner:
        result = net._start_persistent_chromium_session(timeout=3, launch_geometry=(1, 2, 3, 4), launch_url='https://example.test')
    assert result == {'ok': True}
    inner.assert_called_once_with(timeout=3, launch_geometry=(1, 2, 3, 4), launch_url='https://example.test')


def test_network_engine_restart_preserves_chromium_proxy_port():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'tekzite_network.py').write_text('pass', encoding='utf-8')
        state_dir = root / 'state'
        state_dir.mkdir()
        dead = Mock()
        dead.poll.return_value = 7
        stale_log = Mock()
        live = Mock()
        live.poll.return_value = None
        net._NETWORK_ENGINE = {
            'process': dead,
            'host': '127.0.0.1',
            'port': 24681,
            'proxy_url': 'http://127.0.0.1:24681',
        }
        net._NETWORK_OPENER = None
        net._NETWORK_ENGINE_LOG_HANDLE = stale_log
        try:
            with patch.dict(os.environ, {}, clear=False), \
                 patch.object(net, '_network_engine_root', return_value=root), \
                 patch.object(net, '_network_engine_state_dir', return_value=state_dir), \
                 patch.object(net.subprocess, 'Popen', return_value=live) as popen, \
                 patch.object(net, '_wait_tcp_port'), \
                 patch.object(net, 'build_opener', return_value=Mock()):
                recovered = net.ensure_network_engine()
            assert recovered['port'] == 24681
            assert recovered['proxy_url'] == 'http://127.0.0.1:24681'
            assert recovered['recovered_same_port'] is True
            assert '--port' in popen.call_args.args[0]
            port_index = popen.call_args.args[0].index('--port') + 1
            assert popen.call_args.args[0][port_index] == '24681'
            stale_log.close.assert_called_once()
        finally:
            try:
                handle = net._NETWORK_ENGINE_LOG_HANDLE
                if handle is not None:
                    handle.close()
            except Exception:
                pass
            net._NETWORK_ENGINE = None
            net._NETWORK_OPENER = None
            net._NETWORK_ENGINE_LOG_HANDLE = None


def test_shutdown_cancels_queued_tk_jobs_before_native_teardown():
    source = Path(main.__file__).read_text(encoding='utf-8')
    close_block = source[source.index('    def on_close(self):'):source.index('    def run(self):')]
    assert 'if getattr(self, "_closing", False):' in close_block
    assert 'self._cancel_all_tk_after_jobs()' in close_block
    assert close_block.index('self._cancel_all_tk_after_jobs()') < close_block.index('close_embedded_chromium(')


def test_navigation_replaces_stale_target_after_chromium_restart():
    session = {'target_id': 'different', 'navigation_generation': 0}
    with patch.object(net, '_start_persistent_chromium_session', return_value=session), \
         patch.object(net, 'activate_embedded_chromium_target', return_value=False) as activate, \
         patch.object(net, 'create_embedded_chromium_target', return_value='replacement') as create, \
         patch.object(net, '_persistent_page_cdp_call', return_value={}) as cdp:
        result = net.navigate_embedded_chromium('https://example.test', target_id='stale-target')
    assert result is session
    activate.assert_called_once_with('stale-target')
    create.assert_called_once_with('about:blank')
    assert session['recovered_stale_target_id'] == 'stale-target'
    assert session['recovered_target_id'] == 'replacement'
    assert session['target_id'] == 'replacement'
    assert cdp.call_args.kwargs['target_id'] == 'replacement'


def test_failed_tab_activation_reloads_instead_of_leaving_dead_tab():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._navigation_generation = 3
    app.active_tab_id = 1
    app.history = ['https://old.test']
    app.history_index = 0
    app.tabs = []
    app.url_var = Mock()
    app.status_var = Mock()
    app._capture_active_tab_state = Mock()
    app.update_history_buttons = Mock()
    app._refresh_tab_strip = Mock()
    app.navigate_to = Mock()
    app._show_native_canvas = Mock()
    app._focus_address = Mock()
    target = {
        'id': 2, 'url': 'https://recover.test', 'history': ['https://recover.test'],
        'history_index': 0, 'chromium_target_id': 'dead-target', 'loaded': True,
        'loading': True, 'ready_state': 'complete',
    }
    assert app._recover_failed_tab_activation(target) is True
    assert app.active_tab_id == 2
    assert target['chromium_target_id'] is None
    assert target['loaded'] is False
    assert target['loading'] is False
    app.navigate_to.assert_called_once_with('https://recover.test', add_history=False, reuse_existing=False)


def test_windows_and_extension_version_metadata_match_release():
    root = Path(main.__file__).resolve().parent
    assert 'version="10.5.42.0"' in (root / 'tekzite_browser.manifest').read_text(encoding='utf-8')
    import json
    extension = json.loads((root / 'chromium_zoom_extension' / 'manifest.json').read_text(encoding='utf-8'))
    assert extension['version'] == '10.5.42'
    info = (root / 'tekzite_version_info.txt').read_text(encoding='utf-8')
    assert 'filevers=(10, 5, 42, 0)' in info
    assert "u'ProductVersion', u'10.5.42'" in info

