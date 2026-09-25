import inspect
import time

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.80"


def test_live_youtube_return_needs_authenticated_cookie(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "launched_monotonic": time.monotonic() - 1.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})

    assert net.standalone_google_auth_succeeded(handle, 1.35) is False


def test_new_authenticated_cookie_can_complete_after_return(monkeypatch):
    baseline = {}
    current = {(".google.com", "SID"): "new-cookie"}
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": baseline,
        "launched_monotonic": time.monotonic() - 1.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: dict(current))

    assert net.standalone_google_auth_succeeded(handle, 1.35) is False
    assert net.standalone_google_auth_succeeded(handle, 1.35) is True
    assert handle["google_auth_success_signal"][0] == "authenticated-cookie"


def test_initial_youtube_title_does_not_arm_completion(monkeypatch):
    handle = {
        "return_url": "https://www.youtube.com/",
        "google_auth_window_left_return_site": False,
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
    assert net._auth_window_title_has_returned(handle) is False
    assert handle.get("google_auth_window_left_return_site") is not True


def test_auth_window_polling_uses_fast_live_hwnd_cadence():
    launch_poll = inspect.getsource(main.BrowserApp._poll_google_auth_launch)
    auth_poll = inspect.getsource(main.BrowserApp._poll_google_auth_window)
    assert "after(70, self._poll_google_auth_window)" in launch_poll
    assert "after(70, self._poll_google_auth_window)" in auth_poll


def test_strong_auth_cookie_set_excludes_account_chooser_only_cookie():
    assert "__Host-GAPS" in net._GOOGLE_AUTH_COOKIE_NAMES
    assert "__Host-GAPS" not in net._GOOGLE_STRONG_AUTH_COOKIE_NAMES
    assert "SID" in net._GOOGLE_STRONG_AUTH_COOKIE_NAMES
