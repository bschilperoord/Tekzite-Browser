from unittest.mock import Mock

import main


class _DoneFuture:
    def __init__(self, value):
        self._value = value

    def done(self):
        return True

    def result(self):
        return self._value


class _Root:
    def __init__(self):
        self.callbacks = []

    def after(self, _delay, fn, *args):
        self.callbacks.append((fn, args))
        return len(self.callbacks)


class _Var:
    def __init__(self, value=None):
        self.value = value

    def set(self, value):
        self.value = value


class _SubmitRecorder:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))
        return _DoneFuture(True)


def _nav_app(tabs, active_id, generation):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.tabs = tabs
    app.active_tab_id = active_id
    app._navigation_generation = generation
    app._canonical_tab_url = lambda value: str(value or "").rstrip("/")
    app._tab_title_for_url = lambda value: f"title:{value}"
    app._refresh_tab_strip = Mock()
    app._queue_closed_target_retirement = Mock()
    app._tab_switch_executor = _SubmitRecorder()
    app._show_native_canvas = Mock()
    app.root = _Root()
    return app


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.94"


def test_completed_navigation_stays_bound_to_origin_tab_after_switch():
    origin = {
        "id": 1,
        "url": "https://www.youtube.com/",
        "page_state_epoch": 7,
        "chromium_target_id": None,
        "history": [],
        "history_index": -1,
    }
    active = {
        "id": 2,
        "url": "https://www.startpage.com/",
        "page_state_epoch": 3,
        "chromium_target_id": "startpage-target",
        "history": ["https://www.startpage.com/"],
        "history_index": 0,
    }
    app = _nav_app([origin, active], active_id=2, generation=12)

    app._poll_embedded_navigation(
        11,
        _DoneFuture({"target_id": "youtube-target", "hot_navigation_reused_native_surface": False}),
        "https://www.youtube.com/",
        True,
        1,
        7,
    )

    assert origin["chromium_target_id"] == "youtube-target"
    assert origin["url"] == "https://www.youtube.com/"
    assert active["url"] == "https://www.startpage.com/"
    assert active["chromium_target_id"] == "startpage-target"
    assert app.active_tab_id == 2
    assert app._tab_switch_executor.calls
    _, args, _ = app._tab_switch_executor.calls[-1]
    assert args == ("startpage-target",)
    app._queue_closed_target_retirement.assert_not_called()


def test_superseded_navigation_cannot_overwrite_newer_document():
    active = {
        "id": 1,
        "url": "https://new.example/",
        "page_state_epoch": 9,
        "chromium_target_id": "new-target",
        "history": ["https://new.example/"],
        "history_index": 0,
    }
    app = _nav_app([active], active_id=1, generation=22)

    app._poll_embedded_navigation(
        21,
        _DoneFuture({"target_id": "orphan-old-target", "hot_navigation_reused_native_surface": False}),
        "https://old.example/",
        True,
        1,
        8,
    )

    assert active["url"] == "https://new.example/"
    assert active["chromium_target_id"] == "new-target"
    app._queue_closed_target_retirement.assert_called_once_with("orphan-old-target", 250)
    _, args, _ = app._tab_switch_executor.calls[-1]
    assert args == ("new-target",)


def test_google_auth_return_updates_source_tab_not_current_tab():
    source = {
        "id": 1,
        "url": "https://accounts.google.com/",
        "title": "Google",
        "page_state_epoch": 2,
        "chromium_target_id": None,
        "favicon_url": "",
        "favicon_photo": None,
        "favicon_page_url": "",
        "favicon_photo_url": "",
    }
    active = {
        "id": 2,
        "url": "https://www.startpage.com/",
        "title": "Startpage",
        "page_state_epoch": 4,
        "chromium_target_id": None,
    }
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.tabs = [source, active]
    app.active_tab_id = 2
    app._google_auth_handoff_active = True
    app._google_auth_return_url = "https://www.youtube.com/"
    app._google_auth_source_url = "https://accounts.google.com/"
    app._google_auth_source_tab_id = 1
    app._google_auth_handle = {}
    app._google_auth_launch_future = None
    app._google_auth_release_future = None
    app._google_auth_success_future = None
    app._google_auth_close_future = None
    app._google_auth_refresh_pending_url = None
    app._tab_title_for_url = lambda value: f"title:{value}"
    app._clear_tab_favicon = main.BrowserApp._clear_tab_favicon
    app._refresh_tab_strip = Mock()
    app.navigate_to = Mock()
    app.url_var = _Var("https://www.startpage.com/")
    app.status_var = _Var()

    app._finish_google_auth_handoff(True)

    assert source["url"] == "https://www.youtube.com/"
    assert source["restore_pending"] is True
    assert source["sleeping"] is True
    assert active["url"] == "https://www.startpage.com/"
    assert app.url_var.value == "https://www.startpage.com/"
    app.navigate_to.assert_not_called()


def test_dwm_restore_reclaims_selected_target_before_attach():
    source = main.BrowserApp._recover_dwm_host_after_taskbar.__code__
    # Keep this test semantic via inspect source because the implementation is
    # Windows/Win32 specific and cannot execute authoritatively on Linux CI.
    import inspect
    text = inspect.getsource(main.BrowserApp._recover_dwm_host_after_taskbar)
    activate = text.index("activate_embedded_chromium_target(active_target_id)")
    attach = text.index("attach_embedded_chromium(host, w, h)")
    assert "active_tab = self._active_tab()" in text
    assert "if not active_target_id:" in text
    assert activate < attach
    assert "self._chromium_frame_target_id = active_target_id" in text
