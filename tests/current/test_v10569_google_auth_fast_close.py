import inspect
import time

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.80"  # sync_version updates this pin


def test_live_youtube_hwnd_succeeds_on_first_observation(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "launched_monotonic": time.monotonic() - 1.0,
    }
    monkeypatch.setattr(net, "_auth_window_title_has_returned", lambda _handle: True)
    handle["google_auth_return_hwnd"] = 4242
    handle["google_auth_return_title"] = "YouTube - Chromium"

    def disk_should_not_be_touched(_value):
        raise AssertionError("first live-HWND success must not wait on disk fallbacks")

    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", disk_should_not_be_touched)
    monkeypatch.setattr(net, "_auth_navigation_has_returned", disk_should_not_be_touched)

    assert net.standalone_google_auth_succeeded(handle, 1.35)
    assert handle["google_auth_success_signal"] == ("window", 4242, "YouTube - Chromium")


def test_live_return_startup_guard_is_short(monkeypatch):
    handle = {
        "return_url": "https://www.youtube.com/",
        "launched_monotonic": time.monotonic() - 0.2,
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


def test_auth_window_polling_uses_fast_live_hwnd_cadence():
    launch_poll = inspect.getsource(main.BrowserApp._poll_google_auth_launch)
    auth_poll = inspect.getsource(main.BrowserApp._poll_google_auth_window)
    assert "after(70, self._poll_google_auth_window)" in launch_poll
    assert "after(70, self._poll_google_auth_window)" in auth_poll


def test_live_return_that_happens_during_disk_fallback_closes_same_cycle(monkeypatch):
    handle = {
        "profile": "profile",
        "return_url": "https://www.youtube.com/",
        "google_auth_cookie_baseline": {},
        "launched_monotonic": time.monotonic() - 1.0,
    }
    calls = {"live": 0}

    def live_return(_handle):
        calls["live"] += 1
        if calls["live"] >= 2:
            _handle["google_auth_return_hwnd"] = 4343
            _handle["google_auth_return_title"] = "YouTube - Chromium"
            return True
        return False

    monkeypatch.setattr(net, "_auth_window_title_has_returned", live_return)
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: {})
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: False)

    assert net.standalone_google_auth_succeeded(handle, 1.35)
    assert calls["live"] == 2
    assert handle["google_auth_success_signal"] == ("window", 4343, "YouTube - Chromium")
