from unittest.mock import Mock
import json
import main


def test_auth_debug_excludes_urls_tokens_cookie_fingerprints_and_error_text():
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._google_auth_handoff_active = True
    app._google_auth_handle = {
        'url': 'https://github.com/login?code=secret',
        'return_url': 'https://example.test/callback?state=secret',
        'google_auth_success_signal': ('secret-cookie-fingerprint',),
        'google_auth_last_probe_error': 'secret-url-in-exception',
        'auth_hwnds': [1, 2],
        'auth_diagnostics': {'detector': 'github-first-party',
                             'stage': 'waiting-for-dashboard-history',
                             'cookie_database_readable': True,
                             'github_session_present': True,
                             'url': 'secret', 'cookies': 'secret'},
    }
    app._copy_debug_report = Mock()
    app.copy_auth_debug()
    text, label = app._copy_debug_report.call_args.args
    assert 'secret' not in text
    report = json.loads(text)
    assert report['completion_detected']
    assert not report['close_requested']
    assert report['visible_window_count'] == 2
    assert report['stage'] == 'waiting-for-dashboard-history'
    assert label == 'auth debug'
