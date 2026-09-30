import engine.net as net
import main


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.116"


def test_later_tab_never_reuses_first_bootstrap_target(monkeypatch):
    session = {
        "app_bootstrap_target_claimed": True,
        "native_app_target_id": "first-tab-target",
        "default_page_zoom_percent": 100,
        "port": 9222,
    }
    calls = []

    monkeypatch.setattr(net, "_start_persistent_chromium_session", lambda timeout=12: session)
    monkeypatch.setattr(
        net,
        "_devtools_json",
        lambda *a, **k: [{"id": "first-tab-target", "type": "page", "webSocketDebuggerUrl": "ws://first"}],
    )

    def fake_browser_call(_session, method, params=None, **kwargs):
        calls.append((method, dict(params or {})))
        if method == "Target.createTarget":
            return {"targetId": "second-tab-target"}
        return {}

    monkeypatch.setattr(net, "_browser_cdp_call", fake_browser_call)

    created = net.create_embedded_chromium_target("about:blank", require_bootstrap=False)

    assert created == "second-tab-target"
    assert created != session["native_app_target_id"]
    assert ("Target.createTarget", {"url": "about:blank", "newWindow": False, "background": False}) in calls
    assert ("Target.activateTarget", {"targetId": "second-tab-target"}) in calls


def test_first_bootstrap_path_can_reuse_claimed_app_target(monkeypatch):
    session = {
        "app_bootstrap_target_claimed": True,
        "native_app_target_id": "first-tab-target",
        "default_page_zoom_percent": 100,
        "port": 9222,
    }
    calls = []

    monkeypatch.setattr(net, "_start_persistent_chromium_session", lambda timeout=12: session)
    monkeypatch.setattr(
        net,
        "_devtools_json",
        lambda *a, **k: [{"id": "first-tab-target", "type": "page", "webSocketDebuggerUrl": "ws://first"}],
    )
    monkeypatch.setattr(net, "_browser_cdp_call", lambda *a, **k: calls.append((a, k)) or {})

    reused = net.create_embedded_chromium_target("about:blank", require_bootstrap=True)

    assert reused == "first-tab-target"
    assert calls == []
