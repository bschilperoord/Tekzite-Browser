import base64

import engine.net as net
import main


class _DoneFuture:
    def __init__(self, value):
        self._value = value

    def done(self):
        return True

    def result(self):
        return self._value


class _Executor:
    def __init__(self, value):
        self.value = value

    def submit(self, *args, **kwargs):
        return _DoneFuture(self.value)


class _Root:
    def __init__(self):
        self.callbacks = []

    def after(self, _delay, fn, *args):
        self.callbacks.append(lambda: fn(*args))
        return len(self.callbacks)


class _Var:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


def _poll_app(tab, info):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.tabs = [tab]
    app._page_state_inflight = set()
    app._executor = _Executor(info)
    app.root = _Root()
    app.active_tab_id = tab["id"]
    app._address_focus_active = False
    app.url_var = _Var()
    app._canonical_tab_url = lambda value: str(value or "").rstrip("/")
    app._maybe_start_google_auth_handoff = lambda *args, **kwargs: False
    app._decode_favicon_photo = lambda value: f"photo:{value}"
    app._record_page_visit = lambda tab: None
    app._refresh_standard_toolbar_state = lambda: None
    app._refresh_tab_strip = lambda: None
    return app


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.122"


def test_page_change_drops_previous_site_icon_before_new_icon_is_ready():
    tab = {
        "id": 1,
        "chromium_target_id": "target-1",
        "url": "https://site-a.example/",
        "title": "A",
        "page_state_epoch": 0,
        "favicon_url": "https://site-a.example/favicon.ico",
        "favicon_photo": "photo-a",
        "favicon_page_url": "https://site-a.example/",
        "favicon_photo_url": "https://site-a.example/favicon.ico",
        "loading": False,
        "audible": False,
    }
    info = {
        "url": "https://site-b.example/",
        "title": "B",
        "readyState": "complete",
        "audible": False,
        "favicon": "https://site-b.example/favicon.ico",
        "favicon_page_url": "https://site-b.example/",
        # Deliberately no favicon_b64 yet: site A's decoded icon must not remain.
    }
    app = _poll_app(tab, info)

    app._poll_one_tab_state(1, "target-1", include_favicon=False)
    app.root.callbacks.pop(0)()

    assert tab["url"] == "https://site-b.example/"
    assert tab["favicon_page_url"] == "https://site-b.example/"
    assert tab["favicon_url"] == "https://site-b.example/favicon.ico"
    assert tab["favicon_photo"] is None
    assert tab["favicon_photo_url"] == ""


def test_stale_inflight_page_state_cannot_write_old_favicon_after_navigation():
    tab = {
        "id": 2,
        "chromium_target_id": "target-2",
        "url": "https://site-a.example/",
        "title": "A",
        "page_state_epoch": 4,
        "favicon_url": "",
        "favicon_photo": None,
        "favicon_page_url": "",
        "favicon_photo_url": "",
        "loading": True,
        "audible": False,
    }
    info = {
        "url": "https://site-a.example/",
        "title": "A stale",
        "readyState": "complete",
        "audible": False,
        "favicon": "https://site-a.example/favicon.ico",
        "favicon_page_url": "https://site-a.example/",
        "favicon_b64": "old-icon",
    }
    app = _poll_app(tab, info)

    app._poll_one_tab_state(2, "target-2", include_favicon=True)
    # Simulate navigate_to() winning while the old favicon request is in flight.
    tab["page_state_epoch"] += 1
    tab["url"] = "https://site-b.example/"
    app.root.callbacks.pop(0)()

    assert tab["url"] == "https://site-b.example/"
    assert tab["favicon_url"] == ""
    assert tab["favicon_photo"] is None


def test_network_favicon_bytes_are_discarded_if_target_navigates_during_fetch(monkeypatch):
    monkeypatch.setattr(net, "_CHROMIUM_SESSION", {"port": 9222})
    calls = []

    def fake_cdp(session, method, params=None, **kwargs):
        calls.append((method, kwargs.get("internal_source")))
        if len(calls) == 1:
            return {"result": {"value": {
                "title": "A",
                "url": "https://site-a.example/",
                "readyState": "complete",
                "favicon": "https://site-a.example/favicon.ico",
                "audible": False,
            }}}
        return {"result": {"value": "https://site-b.example/"}}

    monkeypatch.setattr(net, "_persistent_page_cdp_call", fake_cdp)
    monkeypatch.setattr(net, "fetch_favicon_bytes", lambda url: b"ICON-A")

    state = net.get_embedded_chromium_page_state(
        target_id="target-1", include_favicon=True, timeout=1
    )

    assert state["favicon_page_url"] == "https://site-a.example/"
    assert "favicon_b64" not in state
    assert calls == [
        ("Runtime.evaluate", "page-state/metadata"),
        ("Runtime.evaluate", "page-state/favicon-owner"),
    ]


def test_network_favicon_bytes_are_kept_when_page_owner_is_unchanged(monkeypatch):
    monkeypatch.setattr(net, "_CHROMIUM_SESSION", {"port": 9222})
    responses = iter([
        {"result": {"value": {
            "title": "A",
            "url": "https://site-a.example/",
            "readyState": "complete",
            "favicon": "https://site-a.example/favicon.ico",
            "audible": False,
        }}},
        {"result": {"value": "https://site-a.example/"}},
    ])
    monkeypatch.setattr(net, "_persistent_page_cdp_call", lambda *a, **k: next(responses))
    monkeypatch.setattr(net, "fetch_favicon_bytes", lambda url: b"ICON-A")

    state = net.get_embedded_chromium_page_state(
        target_id="target-1", include_favicon=True, timeout=1
    )

    assert base64.b64decode(state["favicon_b64"]) == b"ICON-A"
