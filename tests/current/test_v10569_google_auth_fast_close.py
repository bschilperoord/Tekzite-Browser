import inspect
import time

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.128"  # sync_version updates this pin


def test_youtube_title_alone_does_not_complete_auth(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "launched_monotonic": time.monotonic() - 1.0,
    }

    def live_title(_handle):
        _handle["google_auth_return_hwnd"] = 4242
        _handle["google_auth_return_title"] = "YouTube - Chromium"
        return True

    monkeypatch.setattr(net, "_auth_window_title_has_returned", live_title)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert not net.standalone_google_auth_succeeded(handle, 1.35)
    assert handle["google_auth_return_hwnd"] == 4242
    assert handle["google_auth_success_signal"] is None


def test_fresh_return_navigation_without_youtube_session_does_not_complete(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "google_auth_return_visit": ("https://www.youtube.com/", 200, 2),
        "launched_monotonic": time.monotonic() - 1.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: True)

    assert not net.standalone_google_auth_succeeded(handle, 1.35)


def test_authenticated_cookie_change_still_requires_settle(monkeypatch):
    baseline = {(".google.com", "SID"): "old"}
    current = {(".google.com", "SID"): "new"}
    handle = {
        "profile": "profile",
        "return_url": "https://www.google.com/",
        "google_auth_cookie_baseline": baseline,
        "launched_monotonic": time.monotonic() - 1.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: current)
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert not net.standalone_google_auth_succeeded(handle, 1.0)
    handle["google_auth_cookie_change_at"] = time.monotonic() - 1.1
    assert net.standalone_google_auth_succeeded(handle, 1.0)


def test_auth_window_polling_uses_fast_live_hwnd_cadence():
    launch_poll = inspect.getsource(main.BrowserApp._poll_google_auth_launch)
    auth_poll = inspect.getsource(main.BrowserApp._poll_google_auth_window)
    assert "after(70, self._poll_google_auth_window)" in launch_poll
    assert "after(70, self._poll_google_auth_window)" in auth_poll


def test_stable_youtube_title_after_observed_auth_phase_cannot_complete(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "google_auth_auth_phase_seen": True,
        "google_auth_return_hwnd": 4242,
        "google_auth_return_title": "(4) YouTube - Chromium",
        "google_auth_title_return_since": time.monotonic() - 1.0,
        "launched_monotonic": time.monotonic() - 5.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert not net.standalone_google_auth_succeeded(handle, 1.35)


def test_youtube_title_without_observed_auth_phase_still_cannot_complete(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "google_auth_return_hwnd": 4242,
        "google_auth_return_title": "YouTube - Chromium",
        "google_auth_title_return_since": time.monotonic() - 10.0,
        "launched_monotonic": time.monotonic() - 10.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert not net.standalone_google_auth_succeeded(handle, 1.35)


def test_stable_youtube_title_with_existing_login_cookie_does_not_complete(monkeypatch):
    current = {(".youtube.com", "LOGIN_INFO"): "same-auth-cookie"}
    handle = {
        "profile": "profile",
        "url": "https://www.youtube.com/signin",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": dict(current),
        "google_auth_return_hwnd": 4242,
        "google_auth_return_title": "YouTube - Chromium",
        "google_auth_title_return_since": time.monotonic() - 1.3,
        "launched_monotonic": time.monotonic() - 5.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: dict(current))
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert not net.standalone_google_auth_succeeded(handle, 1.35)


def test_accounts_google_launch_requires_youtube_session_proof(monkeypatch):
    handle = {
        "profile": "profile",
        "url": "https://accounts.google.com/ServiceLogin",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "google_auth_return_hwnd": 4242,
        "google_auth_return_title": "YouTube - Chromium",
        "google_auth_title_return_since": time.monotonic() - 1.0,
        "launched_monotonic": time.monotonic() - 5.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert not net.standalone_google_auth_succeeded(handle, 1.35)


def test_cross_host_live_return_checks_persisted_session(monkeypatch):
    from unittest.mock import Mock
    handle = {
        "profile": "profile",
        "url": "https://accounts.google.com/ServiceLogin",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
    }
    cookies = Mock(return_value={})
    history = Mock(return_value=True)
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _: True)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", cookies)
    monkeypatch.setattr(net, "_auth_navigation_has_returned", history)
    assert not net.standalone_google_auth_succeeded(handle, 1.35)
    cookies.assert_called_once_with("profile")
    history.assert_called_once_with(handle)
