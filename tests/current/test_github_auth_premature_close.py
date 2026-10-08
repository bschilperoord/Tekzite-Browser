"""Real History DB regressions for provider visits mistaken for OAuth returns."""
import sqlite3
from unittest.mock import Mock

import engine.net as net
import main
from tests.current.test_auth_handoff_lifecycle import app_for


def test_github_session_page_does_not_close_unfinished_login(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'
    db = profile / 'Default' / 'History'
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)')
        con.execute('CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)')
        for i, url in enumerate([
            'https://github.com/session',
            'https://app.example.test/home',
            'https://github.com/login?return_to=%2Flogin%2Foauth%2Fauthorize',
        ], 1):
            con.execute('INSERT INTO urls VALUES (?, ?)', (i, url))
            con.execute('INSERT INTO visits VALUES (?, ?, ?)', (i, i, i * 100))
    baseline = ('https://app.example.test/home', 200, 2)
    handle = {
        'profile': str(profile),
        'url': 'https://github.com/login/oauth/authorize?client_id=test',
        'return_url': 'https://app.example.test/auth/github/callback',
        'history_return_visit_baseline': baseline,
        'history_return_launch_visit': baseline,
    }
    monkeypatch.setattr(main, 'standalone_google_auth_succeeded', net.standalone_google_auth_succeeded)
    monkeypatch.setattr(main, 'standalone_auth_chromium_running', lambda _: True)
    close = Mock()
    monkeypatch.setattr(main, 'close_standalone_auth_chromium', close)
    app = app_for(handle)
    # Provider login/session history must never become return proof, even when
    # the history writer changes the provider's latest URL during sign-in.
    for i, url in enumerate(['https://github.com/session', 'https://github.com/',
                             'https://github.com/sessions/two-factor'], 4):
        with sqlite3.connect(db) as con:
            con.execute('INSERT INTO urls VALUES (?, ?)', (i, url))
            con.execute('INSERT INTO visits VALUES (?, ?, ?)', (i, i, i * 100))
        app._poll_google_auth_window()
        app._poll_google_auth_window()
        close.assert_not_called()
        assert 'auth_return_url_seen' not in handle
    # A fresh visit on the relying site still completes the handoff.
    with sqlite3.connect(db) as con:
        con.execute('INSERT INTO urls VALUES (7, ?)',
                    ('https://app.example.test/auth/github/callback?code=ok&state=test',))
        con.execute('INSERT INTO visits VALUES (7, 7, 700)')
    app._poll_google_auth_window()
    app._poll_google_auth_window()
    close.assert_called_once_with(handle, True)


def test_launch_url_is_only_a_source_of_nested_callbacks():
    callback = 'https://app.example.test/auth/github/callback'
    source = ('https://github.com/login/oauth/authorize?redirect_uri='
              'https%3A%2F%2Fapp.example.test%2Fauth%2Fgithub%2Fcallback')
    assert net._auth_return_url_candidates({'url': source, 'return_url': callback}) == [callback]
