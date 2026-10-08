from concurrent.futures import Future
from unittest.mock import Mock

import pytest

import main
import engine.net as net


@pytest.fixture
def flow(monkeypatch):
    now = [100.0]
    cookies = [{}]
    returned = [False]
    title = [True]
    handle = {
        "profile": "profile",
        "url": "https://accounts.google.com/ServiceLogin",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "google_auth_auth_phase_seen": True,
        "google_auth_title_return_since": 1.0,
        "google_auth_return_hwnd": 42,
        "google_auth_return_title": "YouTube - Chromium",
        "google_auth_return_visit": ("https://www.youtube.com/", 200, 2),
    }
    monkeypatch.setattr(net.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _: cookies[0])
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _: returned[0])
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _: title[0])
    return handle, now, cookies, returned, title


@pytest.mark.parametrize("current", [{}, None, {(".google.com", "SID"): "new-google-cookie"}, {(".youtube.com", "LOGIN_INFO"): "old-youtube-cookie"}])
def test_passkey_cannot_close_on_title_history_or_google_cookies(flow, current):
    handle, now, cookies, returned, _ = flow
    handle["google_auth_cookie_baseline"] = {(".youtube.com", "LOGIN_INFO"): "old-youtube-cookie"}
    cookies[0] = current
    returned[0] = True
    assert not net.standalone_google_auth_succeeded(handle)
    assert handle["google_auth_success_signal"] is None
    now[0] += 20
    assert not net.standalone_google_auth_succeeded(handle)


def test_youtube_session_waits_for_return_and_stable_persistence(flow):
    handle, now, cookies, returned, _ = flow
    cookies[0] = {(".youtube.com", "LOGIN_INFO"): "new-youtube-session"}
    assert not net.standalone_google_auth_succeeded(handle)
    returned[0] = True
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 1.0
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 0.4
    assert net.standalone_google_auth_succeeded(handle)


def test_cookie_change_or_failed_probe_restarts_settle(flow):
    handle, now, cookies, returned, _ = flow
    returned[0] = True
    cookies[0] = {(".youtube.com", "LOGIN_INFO"): "first"}
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 1.0
    cookies[0] = None
    assert not net.standalone_google_auth_succeeded(handle)
    cookies[0] = {(".youtube.com", "LOGIN_INFO"): "second"}
    now[0] += 1.0
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 1.4
    assert net.standalone_google_auth_succeeded(handle)


def test_passkey_window_alongside_youtube_is_not_a_return(monkeypatch):
    handle = {"return_url": "https://www.youtube.com/"}
    for windows in [
        [{"hwnd": 1, "title": "YouTube - Chromium"}, {"hwnd": 2, "title": "Use your passkey - Chromium"}],
        [{"hwnd": 2, "title": "Use your passkey - Chromium"}, {"hwnd": 1, "title": "YouTube - Chromium"}],
    ]:
        monkeypatch.setattr(net, "_standalone_auth_window_snapshot", lambda _: windows)
        assert not net._auth_window_title_has_returned(handle)


def test_unfinished_passkey_never_requests_window_close(monkeypatch, flow):
    handle, _, _, returned, _ = flow
    returned[0] = True
    app = Mock()
    app._google_auth_handoff_active = True
    app._google_auth_handle = handle
    app._google_auth_close_future = None
    future = Future()
    future.set_result(net.standalone_google_auth_succeeded(handle))
    app._google_auth_success_future = future
    monkeypatch.setattr(main, "standalone_auth_chromium_running", lambda _: True)
    main.BrowserApp._poll_google_auth_window(app)
    app._google_auth_executor.submit.assert_not_called()
    assert not handle.get("auto_close_requested")


def test_unreadable_launch_baseline_cannot_treat_old_cookie_as_new(flow):
    handle, _, cookies, returned, _ = flow
    handle["google_auth_cookie_baseline_readable"] = False
    cookies[0] = {(".youtube.com", "LOGIN_INFO"): "existing-session"}
    returned[0] = True
    assert not net.standalone_google_auth_succeeded(handle)


def test_cross_host_youtube_signin_url_is_not_a_completed_return(monkeypatch):
    handle = {"profile": "profile", "url": "https://accounts.google.com/ServiceLogin", "return_url": "https://www.youtube.com/"}
    monkeypatch.setattr(net, "_snapshot_chromium_latest_visit", lambda *args: ("https://www.youtube.com/signin", 200, 2))
    assert not net._auth_navigation_has_returned(handle)


def test_completed_youtube_session_requests_cooperative_close(monkeypatch, flow):
    handle, now, cookies, returned, _ = flow
    cookies[0] = {(".youtube.com", "LOGIN_INFO"): "new-youtube-session"}
    returned[0] = True
    assert not net.standalone_google_auth_succeeded(handle)
    now[0] += 1.4
    assert net.standalone_google_auth_succeeded(handle)
    app = Mock()
    app._google_auth_handoff_active = True
    app._google_auth_handle = handle
    app._google_auth_close_future = None
    future = Future()
    future.set_result(True)
    app._google_auth_success_future = future
    monkeypatch.setattr(main, "standalone_auth_chromium_running", lambda _: True)
    main.BrowserApp._poll_google_auth_window(app)
    app._google_auth_executor.submit.assert_called_once_with(main.close_standalone_auth_chromium, handle, True)
