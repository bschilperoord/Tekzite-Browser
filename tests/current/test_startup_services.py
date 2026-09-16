import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from engine import features
import tekzite_network as proxy
from browser_state import write_json


class StartupServiceTests(unittest.TestCase):
    def test_failure_does_not_abort_chromium_start(self):
        session = {'process': Mock()}
        with patch.object(features, 'configure', side_effect=RuntimeError('not ready')), patch.object(features.net, '_set_adblock_fallback') as fallback:
            self.assertFalse(features.initialize_optional(session))
            fallback.assert_called_once_with(True)
        self.assertFalse(session['feature_services_ready'])
        self.assertIn('not ready', session['feature_services_error'])
        session['process'].terminate.assert_not_called()

    def test_fallback_write_failure_still_does_not_abort_start(self):
        session = {}
        with patch.object(features, 'configure', side_effect=RuntimeError('not ready')), patch.object(features.net, '_set_adblock_fallback', side_effect=OSError('locked')):
            self.assertFalse(features.initialize_optional(session))
        self.assertIn('locked', session['feature_services_error'])

    def test_worker_wakeup_and_missing_entrypoint_repair(self):
        session = {'port': 9222}
        worker = {'type': 'service_worker', 'url': f'chrome-extension://{features.net.TEKZITE_ZOOM_EXTENSION_ID}/background.js', 'id': 'worker', 'webSocketDebuggerUrl': 'ws://127.0.0.1/worker'}
        results = [{}, {}, {'result': {'value': False}}, {'result': {'value': True}}, {'result': {'value': []}}]
        with patch.object(features.net, '_devtools_json', return_value=[worker]), patch.object(features.net, '_open_devtools_websocket', return_value=Mock()), patch.object(features.net, '_cdp_call', side_effect=results) as call:
            self.assertEqual(features.call('downloads', session=session), [])
        self.assertEqual(call.call_args_list[1].args[1], 'Runtime.runIfWaitingForDebugger')
        self.assertIn('async function tekziteFeature', call.call_args_list[3].args[2]['expression'])

    def test_success_disables_proxy_fallback_only_after_confirmation(self):
        session = {'feature_channel': {'ws': Mock(), 'target': 'worker'}}
        with patch.object(features.net, '_cdp_call', return_value={'result': {'value': True}}), patch.object(features.net, '_set_adblock_fallback') as fallback:
            self.assertTrue(features.configure(session))
            fallback.assert_called_once_with(False)
        self.assertTrue(session['feature_services_ready'])

    def test_unconfirmed_configuration_does_not_disable_fallback(self):
        session = {'feature_channel': {'ws': Mock(), 'target': 'worker'}}
        with patch.object(features.net, '_cdp_call', return_value={'result': {}}), patch.object(features.net, '_set_adblock_fallback') as fallback:
            with self.assertRaises(RuntimeError):
                features.configure(session)
            fallback.assert_not_called()

    def test_proxy_policy_live_updates_and_corruption_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'adblock-policy.json'
            with patch.object(proxy, 'ADBLOCK_POLICY', str(path)), patch.object(proxy, 'ADBLOCK_ENABLED', True):
                self.assertTrue(proxy._is_ad_host('securepubads.g.doubleclick.net'))
                write_json(path, {'enabled': False})
                self.assertFalse(proxy._is_ad_host('securepubads.g.doubleclick.net'))
                self.assertTrue(proxy._is_browser_telemetry_host('vortex.data.microsoft.com'))
                write_json(path, {'enabled': True})
                self.assertTrue(proxy._is_ad_host('securepubads.g.doubleclick.net'))
                path.write_text('broken')
                self.assertTrue(proxy._is_ad_host('securepubads.g.doubleclick.net'))
