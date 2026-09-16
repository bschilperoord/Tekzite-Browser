import ast
import inspect
import unittest
from unittest.mock import Mock, patch
from engine import net, features
from browser_features import BrowserFeatures


class EmbedOwnerRecoveryTests(unittest.TestCase):
    def session(self):
        process = Mock()
        process.poll.return_value = None
        return {'target_id': 'page-1', 'process': process}

    def test_healthy_owner_has_no_delay_or_activation(self):
        session = self.session()
        with patch.object(net, '_validate_embed_owner_before_reparent', return_value=42), patch.object(net, '_browser_cdp_call') as activate, patch.object(net.time, 'sleep') as sleep:
            self.assertEqual(net._wait_for_live_embed_owner(session, 42, 1280, 720), 42)
        activate.assert_not_called()
        sleep.assert_not_called()

    def test_transient_owner_loss_recovers_only_validated_owner(self):
        session = self.session()
        session['pre_attach_owner_error'] = 'stale'
        with patch.object(net, '_validate_embed_owner_before_reparent', side_effect=[0, 0, 84]) as validate, patch.object(net, '_browser_cdp_call') as activate, patch.object(net.time, 'sleep'):
            self.assertEqual(net._wait_for_live_embed_owner(session, 42, 1280, 720), 84)
        self.assertEqual(validate.call_count, 3)
        activate.assert_called_once_with(session, 'Target.activateTarget', {'targetId': 'page-1'}, timeout=1)
        self.assertNotIn('pre_attach_owner_error', session)

    def test_permanent_loss_never_returns_stale_owner(self):
        session = self.session()
        with patch.object(net, '_validate_embed_owner_before_reparent', return_value=0) as validate, patch.object(net, '_browser_cdp_call'), patch.object(net.time, 'sleep'):
            self.assertEqual(net._wait_for_live_embed_owner(session, 42, 1280, 720), 0)
        self.assertEqual(validate.call_count, 4)

    def test_dead_process_stops_retries(self):
        session = self.session()
        session['process'].poll.return_value = 1
        with patch.object(net, '_validate_embed_owner_before_reparent', return_value=0) as validate, patch.object(net, '_browser_cdp_call'), patch.object(net.time, 'sleep') as sleep:
            self.assertEqual(net._wait_for_live_embed_owner(session, 42, 1280, 720), 0)
        self.assertEqual(validate.call_count, 1)
        sleep.assert_not_called()

    def test_activation_error_still_allows_validation_retry(self):
        session = self.session()
        with patch.object(net, '_validate_embed_owner_before_reparent', side_effect=[0, 84]), patch.object(net, '_browser_cdp_call', side_effect=RuntimeError('busy')), patch.object(net.time, 'sleep'):
            self.assertEqual(net._wait_for_live_embed_owner(session, 42, 1280, 720), 84)
        self.assertEqual(session['embed_owner_activation_error'], 'busy')

    def test_services_schedule_once_only_for_current_session(self):
        app = BrowserFeatures()
        app._closing = False
        app._executor = Mock()
        session = {'process': Mock()}
        with patch.object(net, '_EDGE_SESSION', session):
            app._start_optional_services({'process': Mock()})
            app._executor.submit.assert_not_called()
            app._start_optional_services(session)
            app._start_optional_services(session)
        app._executor.submit.assert_called_once_with(features.initialize_optional, session)

    def test_shutdown_does_not_schedule_services(self):
        app = BrowserFeatures()
        app._closing = True
        app._executor = Mock()
        session = {'process': Mock()}
        with patch.object(net, '_EDGE_SESSION', session):
            app._start_optional_services(session)
        app._executor.submit.assert_not_called()

    def test_launch_path_preserves_requested_url_and_has_no_service_gate(self):
        tree = ast.parse(inspect.getsource(net._start_persistent_chromium_session))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                self.assertFalse(any(isinstance(t, ast.Name) and t.id == 'launch_url' for t in node.targets))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, ('configure', 'initialize_optional'))
