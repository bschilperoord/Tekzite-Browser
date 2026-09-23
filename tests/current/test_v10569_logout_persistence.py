import inspect

import main
import engine.net as net


def test_normal_exit_requests_graceful_chromium_profile_flush():
    assert main.BROWSER_VERSION == "10.5.80"
    source = inspect.getsource(main.BrowserApp.on_close)
    assert "close_embedded_chromium(" in source
    assert "graceful=True" in source
    assert "timeout=6.0" in source


def test_graceful_shutdown_uses_browser_close_before_force_fallback():
    public = inspect.getsource(net.close_embedded_chromium)
    clean = inspect.getsource(net._close_embedded_chromium_cleanly_for_auth_unlocked)
    assert "if graceful and _EDGE_SESSION" in public
    assert "_close_embedded_chromium_cleanly_for_auth_unlocked" in public
    assert public.index("_close_embedded_chromium_cleanly_for_auth_unlocked") < public.rindex("_close_embedded_chromium_unlocked")
    assert '"Browser.close"' in clean


def test_successful_graceful_close_does_not_run_force_fallback(monkeypatch, tmp_path):
    previous = net._EDGE_SESSION
    calls = []
    try:
        net._EDGE_SESSION = {"profile": str(tmp_path / "profile")}

        def clean(timeout=6.0):
            calls.append(("clean", timeout))
            return True

        def force(*args, **kwargs):
            raise AssertionError("force fallback must not run after clean Browser.close")

        monkeypatch.setattr(net, "_close_embedded_chromium_cleanly_for_auth_unlocked", clean)
        monkeypatch.setattr(net, "_close_embedded_chromium_unlocked", force)
        assert net.close_embedded_chromium(clear_profile=False, graceful=True, timeout=3.25)
        assert calls == [("clean", 3.25)]
    finally:
        net._EDGE_SESSION = previous
