import inspect
import time

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.80"


def test_live_youtube_window_title_is_completion_signal(monkeypatch):
    handle = {
        "return_url": "https://www.youtube.com/",
        "launched_monotonic": 0.0,
    }
    monkeypatch.setattr(
        net,
        "_standalone_auth_window_snapshot",
        lambda _handle: [{
            "hwnd": 4242,
            "pid": 99,
            "class": "Chrome_WidgetWin_1",
            "title": "YouTube - Chromium",
        }],
    )
    assert net._auth_window_title_has_returned(handle)
    assert handle["google_auth_return_hwnd"] == 4242
    assert handle["google_auth_return_title"] == "YouTube - Chromium"


def test_google_accounts_title_is_not_youtube_completion(monkeypatch):
    handle = {
        "return_url": "https://www.youtube.com/",
        "launched_monotonic": 0.0,
    }
    monkeypatch.setattr(
        net,
        "_standalone_auth_window_snapshot",
        lambda _handle: [{
            "hwnd": 4242,
            "pid": 99,
            "class": "Chrome_WidgetWin_1",
            "title": "Sign in - Google Accounts - Chromium",
        }],
    )
    assert not net._auth_window_title_has_returned(handle)


def test_success_detector_prefers_live_window_over_disk_lag(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "google_auth_return_hwnd": 4242,
        "google_auth_return_title": "YouTube - Chromium",
    }
    def disk_should_not_be_touched(_value):
        raise AssertionError("live HWND completion must bypass disk snapshots")

    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", disk_should_not_be_touched)
    monkeypatch.setattr(net, "_auth_navigation_has_returned", disk_should_not_be_touched)
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)

    signal = ("window", 4242, "YouTube - Chromium")
    handle["google_auth_success_signal"] = signal
    handle["google_auth_cookie_change_at"] = time.monotonic() - 2.0
    assert net.standalone_google_auth_succeeded(handle, 1.0)


def test_close_targets_exact_auth_hwnd_and_initial_close_is_synchronous():
    close_source = inspect.getsource(net.close_standalone_auth_chromium)
    poll_source = inspect.getsource(main.BrowserApp._poll_google_auth_window)
    launch_source = inspect.getsource(net.start_standalone_auth_chromium)

    assert "_standalone_auth_window_snapshot(handle)" in close_source
    assert "_request_windows_hwnd_close" in close_source
    assert '"auth_hwnds"' in launch_source
    assert "close_standalone_auth_chromium, handle, True" in poll_source
    assert "subprocess.run" not in close_source
