import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import main
from browser_features import BrowserFeatures, download_progress, record_visit, site_host
from browser_state import load_session, write_json
from engine import features


class BrowserFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = main.BrowserApp.__new__(main.BrowserApp)
        self.app._state_directory = Path(self.temp.name)
        self.app.preferences = {'restore_tabs': True, 'adblock_enabled': True, 'adblock_sites': []}
        self.app.root = Mock()
        self.app.status_var = Mock()
        self.app._init_features()
        self.app.tabs = [{'id': 1, 'url': 'https://example.test', 'title': 'Example', 'ready_state': 'complete'}]
        self.app.active_tab_id = 1

    def test_crash_checkpoint_restores_pin_and_active_tab(self):
        self.app.tabs[0]['pinned'] = True
        self.app._checkpoint_features()
        result = load_session(self.app._state_directory / 'session.json')
        self.assertFalse(result['clean_exit'])
        self.assertTrue(result['tabs'][0]['pinned'])
        self.assertEqual(result['active'], 0)
        # No redundant disk write when state is unchanged.
        with patch('browser_features.write_json') as write:
            self.app._checkpoint_features()
            write.assert_not_called()

    def test_close_snapshot_is_clean(self):
        self.app._save_session()
        self.assertTrue(load_session(self.app._state_directory / 'session.json')['clean_exit'])

    def test_checkpoint_error_keeps_timer_alive(self):
        with patch('browser_features.write_json', side_effect=OSError('disk full')):
            self.app._checkpoint_features()
        self.app.root.after.assert_called_with(2000, self.app._checkpoint_features)
        self.app.status_var.set.assert_called()

    def test_history_records_page_once_and_updates_title(self):
        tab = self.app.tabs[0]
        self.app._record_page_visit(tab)
        original_time = self.app.visits[0]['visited']
        tab['title'] = 'Updated'
        self.app._record_page_visit(tab)
        self.assertEqual(len(self.app.visits), 1)
        self.assertEqual(self.app.visits[0]['title'], 'Updated')
        self.assertEqual(self.app.visits[0]['visited'], original_time)
        tab['url'] = 'https://example.test/next'
        self.app._record_page_visit(tab)
        self.assertEqual(len(self.app.visits), 2)

    def test_history_skips_loading_page_and_bounds_storage(self):
        self.app.tabs[0]['ready_state'] = 'loading'
        self.app._record_page_visit(self.app.tabs[0])
        self.assertEqual(self.app.visits, [])
        rows = [{'url': f'https://example.test/{i}'} for i in range(5001)]
        self.assertEqual(len(record_visit(rows, 'https://new.test', 'New')), 5000)

    def test_pin_order_and_bulk_close_protection(self):
        self.app.tabs += [{'id': 2, 'url': ''}, {'id': 3, 'url': ''}]
        self.app._refresh_tab_strip = Mock()
        self.app._toggle_pin(3)
        self.assertEqual([t['id'] for t in self.app.tabs], [3, 1, 2])
        self.app._close_tab = Mock()
        self.app._switch_tab = Mock()
        self.app._close_other_tabs(1)
        self.app._close_tab.assert_called_once_with(2)

    def test_quiet_mode_hides_controls_and_restores_preference(self):
        self.app._ui_animation_jobs = {'x': 1}
        self.app.debug_group = Mock()
        self.app.status_bar = Mock()
        self.app._refresh_tab_strip = Mock()
        self.app.preferences['quiet_mode'] = True
        self.app._apply_quiet_mode()
        self.app.debug_group.pack_forget.assert_called_once()
        self.app.status_bar.pack_forget.assert_called_once()
        self.assertEqual(self.app._ui_animation_jobs, {})
        self.app.preferences['quiet_mode'] = False
        self.app.preferences['show_status_bar'] = False
        self.app._apply_quiet_mode()
        self.app.status_bar.pack.assert_not_called()

    def test_site_identity_and_download_progress(self):
        self.assertEqual(site_host('https://WWW.Example.com:443/test'), 'www.example.com')
        self.assertEqual(site_host('file:///tmp/file'), '')
        self.assertEqual(site_host('https://example.com.evil.test'), 'example.com.evil.test')
        self.assertIn('50%', download_progress({'bytesReceived': 512, 'totalBytes': 1024}))
        self.assertIn('unknown', download_progress({'bytesReceived': 512, 'totalBytes': -1}))

    def test_site_exception_does_not_modify_unrelated_domain(self):
        self.app.preferences['adblock_sites'] = ['unrelated.test']
        self.app._reload_current = Mock()
        self.app._persist_preferences = Mock()
        def run(job, success, parent=None):
            success(job())
        self.app._feature_async = run
        with patch('browser_features.features.call', return_value=True) as call:
            self.app._toggle_site_adblock()
        self.assertEqual(self.app.preferences['adblock_sites'], ['example.test', 'unrelated.test'])
        call.assert_called_once_with('configure', {'enabled': True, 'sites': ['example.test', 'unrelated.test']})

    def test_extension_error_is_not_reported_as_success(self):
        session = {'feature_channel': {'ws': Mock(), 'target': 'helper'}}
        with patch('engine.features.net._cdp_call', return_value={'exceptionDetails': {'text': 'denied'}}):
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                features.call('cancel', {'id': 1}, session)

    def test_bridge_serializes_payload_without_code_interpolation(self):
        session = {'feature_channel': {'ws': Mock(), 'target': 'helper'}}
        payload = {'sites': ['a\";throw Error(1);//'], 'enabled': True}
        with patch('engine.features.net._cdp_call', return_value={'result': {'value': True}}) as call:
            self.assertTrue(features.call('configure', payload, session))
        expression = call.call_args.args[2]['expression']
        self.assertIn('a\\\";throw Error(1);//', expression)

    def test_services_attach_to_worker_without_creating_window(self):
        session = {'port': 9222}
        worker = {'type': 'service_worker', 'url': f'chrome-extension://{features.net.TEKZITE_ZOOM_EXTENSION_ID}/background.js', 'id': 'worker', 'webSocketDebuggerUrl': 'ws://127.0.0.1/worker'}
        with patch('engine.features.net._devtools_json', return_value=[worker]), patch('engine.features.net._open_devtools_websocket', return_value=Mock()), patch('engine.features.net._cdp_call', side_effect=[{}, {}, {'result': {'value': True}}, {'result': {'value': []}}]), patch('engine.features.net._browser_cdp_call') as browser_call:
            self.assertEqual(features.call('downloads', session=session), [])
            browser_call.assert_not_called()
            self.assertEqual(session['feature_channel']['target'], 'worker')
