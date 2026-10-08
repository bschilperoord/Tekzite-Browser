from unittest.mock import Mock

import pytest

from engine import features


@pytest.fixture
def context(monkeypatch, tmp_path):
    session = {'port': 1234}
    path = tmp_path / 'extension'; path.mkdir()
    calls = []
    inventory = [{'id': 'a' * 32, 'path': str(path), 'location': 'UNPACKED', 'state': 'ENABLED', 'version': '1.0'}]
    response = [{'id': 'a' * 32, 'version': '2.0', 'state': 'ENABLED'}]
    def browser_call(session, method, params, **kwargs):
        calls.append((method, params))
        return {'targetId': 'hidden'}
    def evaluate(ws, method, params, **kwargs):
        if 'getExtensionsInfo' in params['expression']:
            return {'result': {'value': inventory}}
        return {'result': {'value': response[0]}}
    websocket = Mock()
    monkeypatch.setattr(features.net, '_browser_cdp_call', browser_call)
    monkeypatch.setattr(features.net, '_devtools_json', lambda *args, **kwargs: [{'id': 'hidden', 'webSocketDebuggerUrl': 'ws://127.0.0.1/hidden'}])
    monkeypatch.setattr(features.net, '_open_devtools_websocket', lambda *args, **kwargs: websocket)
    monkeypatch.setattr(features.net, '_cdp_call', evaluate)
    return session, path, calls, inventory, response, websocket


def test_reload_confirms_version_and_closes_hidden_target(context):
    session, path, calls, _, _, websocket = context
    with features.extension_reloader(session) as reload:
        assert reload(str(path), '2.0')
    assert calls[0] == ('Target.createTarget', {'url': 'chrome://extensions/', 'background': True, 'hidden': True})
    assert calls[-1] == ('Target.closeTarget', {'targetId': 'hidden'})
    websocket.close.assert_called_once()


@pytest.mark.parametrize('change', [{'version': '1.0'}, {'id': 'different'}, {'state': 'DISABLED'}])
def test_reload_rejects_unconfirmed_runtime(context, change):
    session, path, calls, _, response, _ = context
    response[0].update(change)
    with pytest.raises(RuntimeError, match='expected version'):
        with features.extension_reloader(session) as reload:
            reload(str(path), '2.0')
    assert calls[-1][0] == 'Target.closeTarget'


def test_reload_does_not_match_an_extension_by_name(context):
    session, path, calls, inventory, _, _ = context
    inventory[0]['path'] = str(path.parent / 'other')
    with features.extension_reloader(session) as reload:
        with pytest.raises(RuntimeError, match='configured path'):
            reload(str(path), '2.0')


def test_reload_does_not_enable_a_disabled_extension(context):
    session, path, calls, inventory, _, _ = context
    inventory[0]['state'] = 'DISABLED'
    with features.extension_reloader(session) as reload:
        with pytest.raises(RuntimeError, match='not enabled'):
            reload(str(path), '2.0')
