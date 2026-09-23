import inspect

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.73"


def test_auth_handoff_cleanly_closes_embedded_chromium():
    helper = inspect.getsource(net._close_embedded_chromium_cleanly_for_auth_unlocked)
    launcher = inspect.getsource(net.start_standalone_auth_chromium)

    assert '"Browser.close"' in helper
    assert '_request_windows_window_close' in helper
    assert '_terminate_profile_chromium_processes' not in helper
    assert '_close_embedded_chromium_cleanly_for_auth_unlocked' in launcher

    # The auth handoff must fail rather than dirty the shared profile if the
    # embedded browser refuses to release it cleanly.
    auth_block = launcher[
        launcher.index('_close_embedded_chromium_cleanly_for_auth_unlocked'):
        launcher.index('_clear_devtools_active_port')
    ]
    assert '_terminate_profile_chromium_processes' not in auth_block
    assert 'did not release the Tekzite profile cleanly' in auth_block


def test_auth_popup_escalation_remains_cooperative():
    close_source = inspect.getsource(net.close_standalone_auth_chromium)
    native_close = inspect.getsource(net._request_windows_window_close)
    poll_source = inspect.getsource(main.BrowserApp._poll_google_auth_window)

    assert 'WM_CLOSE' in native_close
    assert 'WM_SYSCOMMAND' in native_close
    assert 'SC_CLOSE' in native_close
    assert 'SendMessageTimeoutW' in native_close
    assert '_terminate_profile_chromium_processes' not in close_source
    assert 'cooperative_escalation = elapsed >= 3.8' in poll_source
    assert 'close_standalone_auth_chromium, handle, cooperative_escalation' in poll_source


def test_auth_popup_still_refreshes_return_page():
    finish_source = inspect.getsource(main.BrowserApp._finish_google_auth_handoff)
    refresh_source = inspect.getsource(main.BrowserApp._refresh_after_google_auth)
    assert 'self._google_auth_refresh_pending_url = return_url' in finish_source
    assert 'self.navigate_to(expected_url, add_history=False, reuse_existing=False)' in refresh_source
