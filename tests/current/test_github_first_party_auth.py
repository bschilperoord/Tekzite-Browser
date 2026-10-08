"""GitHub first-party login is distinct from an OAuth callback to another site."""
import sqlite3
from unittest.mock import Mock
import pytest
import engine.net as net
import main
from tests.current.test_auth_handoff_lifecycle import app_for


def profile_state(tmp_path, cookie_name='user_session', dashboard_time=200):
    directory = tmp_path / 'Default'
    directory.mkdir()
    with sqlite3.connect(directory / 'Cookies') as con:
        con.execute('CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, expires_utc INTEGER)')
        con.execute('INSERT INTO cookies VALUES (?, ?, ?, ?, ?)',
                    ('.github.com', cookie_name, '', b'opaque-session', 0))
    with sqlite3.connect(directory / 'History') as con:
        con.execute('CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)')
        con.execute('CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)')
        con.execute('INSERT INTO urls VALUES (1, ?)', ('https://github.com/',))
        con.execute('INSERT INTO visits VALUES (1, 1, ?)', (dashboard_time,))
        con.execute('INSERT INTO urls VALUES (2, ?)', ('https://github.com/login',))
        con.execute('INSERT INTO visits VALUES (2, 2, 300)')
    return {'profile': str(tmp_path), 'url': 'https://github.com/login',
            'return_url': 'https://github.com/login', 'auth_cookie_baseline': {},
            'history_visit_baseline': ('https://github.com/login', 100, 0),
            'history_return_launch_visit': ('https://github.com/', dashboard_time, 1)}


def test_completed_login_closes_both_windows_after_settle(tmp_path, monkeypatch):
    handle = profile_state(tmp_path)
    now = [10.0]
    monkeypatch.setattr(net.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(main, 'standalone_google_auth_succeeded', net.standalone_google_auth_succeeded)
    monkeypatch.setattr(main, 'standalone_auth_chromium_running', lambda _: True)
    close = Mock(); monkeypatch.setattr(main, 'close_standalone_auth_chromium', close)
    app = app_for(handle, previous='https://github.com/login')
    app._poll_google_auth_window(); app._poll_google_auth_window()
    close.assert_not_called()
    now[0] += 1.5
    app._poll_google_auth_window(); app._poll_google_auth_window()
    close.assert_called_once_with(handle, True)
    assert handle['auth_return_url_seen'] == 'https://github.com/'
    app._finish_google_auth_handoff(True)
    app.navigate_to.assert_called_once_with('https://github.com/', add_history=False, reuse_existing=False)


@pytest.mark.parametrize('cookie', ['_gh_sess', 'logged_in', 'consent'])
def test_non_session_cookies_do_not_close_login(tmp_path, monkeypatch, cookie):
    handle = profile_state(tmp_path, cookie_name=cookie)
    monkeypatch.setattr(net.time, 'monotonic', lambda: 100.0)
    assert not net.standalone_google_auth_succeeded(handle)
    assert not handle.get('google_auth_success_signal')


def test_old_dashboard_with_new_cookie_is_not_completion(tmp_path):
    handle = profile_state(tmp_path, dashboard_time=50)
    assert not net.standalone_google_auth_succeeded(handle)


def test_unchanged_session_cookie_is_not_new_login(tmp_path, monkeypatch):
    handle = profile_state(tmp_path)
    monkeypatch.setattr(net, '_standalone_auth_window_snapshot', lambda _: [])
    handle['auth_cookie_baseline'] = net._snapshot_auth_cookie_state(str(tmp_path), 'https://github.com/')
    assert not net.standalone_google_auth_succeeded(handle)


@pytest.mark.parametrize('source,target', [
    ('https://github.com/login/oauth/authorize', 'https://app.example.test/callback'),
    ('https://github.com/login?return_to=%2Flogin%2Foauth%2Fauthorize', 'https://github.com/'),
])
def test_oauth_does_not_use_first_party_session_detection(source, target):
    assert not net._github_first_party_auth({'url': source, 'return_url': target})


def test_existing_session_needs_live_dashboard_and_fresh_visit(tmp_path, monkeypatch):
    handle = profile_state(tmp_path)
    handle['auth_cookie_baseline'] = net._snapshot_auth_cookie_state(str(tmp_path), 'https://github.com/')
    monkeypatch.setattr(net, '_standalone_auth_window_snapshot',
                        lambda _: [{'title': 'GitHub - Chromium'}])
    now = [10.0]
    monkeypatch.setattr(net.time, 'monotonic', lambda: now[0])
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 1.5
    assert net.standalone_google_auth_succeeded(handle)


@pytest.mark.parametrize('title,visit_time,succeeds', [
    ('GitHub - Chromium', 200, True),
    ('Sign in to GitHub - Chromium', 200, False),
    ('GitHub - Chromium', 50, False),
])
def test_locked_cookie_db_requires_live_dashboard_and_fresh_history(tmp_path, monkeypatch, title, visit_time, succeeds):
    handle = profile_state(tmp_path, dashboard_time=visit_time)
    monkeypatch.setattr(net, '_snapshot_auth_cookie_state', lambda *_: None)
    monkeypatch.setattr(net, '_standalone_auth_window_snapshot', lambda _: [{'title': title}])
    now = [10.0]
    monkeypatch.setattr(net.time, 'monotonic', lambda: now[0])
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 1.5
    assert net.standalone_google_auth_succeeded(handle) is succeeds
    assert not handle['auth_diagnostics']['cookie_database_readable']
