"""Handoff orchestration tests; these do not authenticate against real providers."""
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import main
import engine.net as net

PROVIDERS = [
    ('outlook', 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize', 'https://outlook.live.com/mail/'),
    ('github', 'https://github.com/login/oauth/authorize', 'https://app.example.test/auth/github/callback'),
    ('auth0', 'https://tenant.eu.auth0.com/authorize', 'https://app.example.test/callback'),
    ('okta', 'https://tenant.okta.com/oauth2/default/v1/authorize', 'https://app.example.test/oidc/callback'),
]

def done(value):
    f = Future(); f.set_result(value); return f

class Executor:
    def __init__(self): self.calls = []
    def submit(self, fn, *args):
        self.calls.append((fn, args))
        return done(fn(*args))


def app_for(handle, previous='https://app.example.test/home'):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._google_auth_handoff_active = True
    app._google_auth_handle = handle
    app._google_auth_return_url = handle['return_url']
    app._google_auth_previous_url = previous
    app._google_auth_source_tab_id = 1
    app._google_auth_success_future = None
    app._google_auth_close_future = None
    app._google_auth_executor = app._executor = Executor()
    app.root = SimpleNamespace(after=Mock())
    app.status_var = SimpleNamespace(set=Mock())
    app.url_var = SimpleNamespace(set=Mock())
    app.tabs = [{'id': 1, 'url': previous}]
    app.active_tab_id = 1
    app._tab_title_for_url = lambda url: url
    app._clear_tab_favicon = Mock()
    app._refresh_tab_strip = Mock()
    app.navigate_to = Mock()
    return app

@pytest.mark.parametrize('name,source,callback', PROVIDERS)
def test_success_closes_then_waits_for_profile_before_resuming(monkeypatch, name, source, callback):
    landing = callback if name == 'outlook' else 'https://app.example.test/dashboard'
    handle = {'profile': 'profile', 'url': source, 'return_url': callback,
              'history_return_visit_baseline': (callback, 100, 1)}
    monkeypatch.setattr(net, '_snapshot_chromium_latest_visit', lambda *_: (landing, 200, 2))
    monkeypatch.setattr(main, 'standalone_google_auth_succeeded', net.standalone_google_auth_succeeded)
    monkeypatch.setattr(main, 'standalone_auth_chromium_running', lambda _: True)
    close = Mock(); monkeypatch.setattr(main, 'close_standalone_auth_chromium', close)
    app = app_for(handle)
    app._poll_google_auth_window()  # submit success probe
    app._poll_google_auth_window()  # consume result and request close
    close.assert_called_once_with(handle, True)
    app.navigate_to.assert_not_called()
    monkeypatch.setattr(main, 'standalone_auth_chromium_running', lambda _: False)
    monkeypatch.setattr(main, 'wait_for_standalone_auth_chromium_release', lambda *_: False)
    app._poll_google_auth_window()
    app._poll_google_auth_profile_release()
    app.navigate_to.assert_not_called()
    assert app._google_auth_handoff_active
    app._google_auth_release_future = done(True)
    app._poll_google_auth_profile_release()
    assert app.root.after.call_args.args == (80, app._finish_google_auth_handoff, True)
    app._finish_google_auth_handoff(True)
    app.navigate_to.assert_called_once_with(landing, add_history=False, reuse_existing=False)
    assert not app._google_auth_handoff_active

@pytest.mark.parametrize('name,source,callback', PROVIDERS)
@pytest.mark.parametrize('suffix', ['?error=access_denied', '#error=login_required'])
def test_error_callback_never_requests_close(monkeypatch, name, source, callback, suffix):
    handle = {'profile': 'profile', 'url': source, 'return_url': callback}
    monkeypatch.setattr(net, '_snapshot_chromium_latest_visit', lambda *_: (callback + suffix, 200, 2))
    assert not net.standalone_google_auth_succeeded(handle)
    assert handle['auth_callback_error']
    monkeypatch.setattr(main, 'standalone_google_auth_succeeded', net.standalone_google_auth_succeeded)
    monkeypatch.setattr(main, 'standalone_auth_chromium_running', lambda _: True)
    close = Mock(); monkeypatch.setattr(main, 'close_standalone_auth_chromium', close)
    app = app_for(handle)
    app._poll_google_auth_window()
    app._poll_google_auth_window()
    close.assert_not_called()
    app.navigate_to.assert_not_called()

@pytest.mark.parametrize('name,source,callback', PROVIDERS)
def test_manual_cancel_restores_initiating_page_without_replaying_callback(name, source, callback):
    app = app_for({'url': source, 'return_url': callback})
    app._finish_google_auth_handoff(True)
    app.navigate_to.assert_called_once_with('https://app.example.test/home', add_history=False, reuse_existing=False)

@pytest.mark.parametrize('name,source,callback', PROVIDERS)
def test_consumed_callback_is_not_replayed(name, source, callback):
    app = app_for({'url': source, 'return_url': callback,
                   'auth_provider_independent_success': True,
                   'auth_return_url_seen': callback + '?code=one-time&state=opaque'})
    app._finish_google_auth_handoff(True)
    app.navigate_to.assert_called_once_with('https://app.example.test/home', add_history=False, reuse_existing=False)
