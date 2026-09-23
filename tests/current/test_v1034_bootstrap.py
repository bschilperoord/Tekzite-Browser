from pathlib import Path
from unittest.mock import patch

import main
from engine import net


def _page(target_id, url):
    return {
        "id": target_id,
        "type": "page",
        "url": url,
        "webSocketDebuggerUrl": f"ws://127.0.0.1/devtools/page/{target_id}",
    }


def test_release_is_v1034():
    assert main.BROWSER_VERSION == "10.5.80"


def test_cold_native_start_always_uses_blank_bootstrap():
    source = Path(net.__file__).read_text(encoding="utf-8")
    block = source[source.index("def open_embedded_chromium"):source.index("def record_embedded_native_recovery")]
    assert 'bootstrap_launch_url = "about:blank" if first_native_bootstrap else None' in block
    assert '"about:blank" if first_native_bootstrap else str(url or "about:blank")' in block
    assert 'direct_launch_url = str(url or "about:blank")' not in block


def test_bootstrap_waits_for_delayed_app_target_and_claims_it():
    session = {"port": 9222, "launch_url": "about:blank", "default_page_zoom_percent": 100}
    pages = [[], [_page("bootstrap-1", "about:blank")]]
    browser_calls = []

    def browser_call(_session, method, params=None, **kwargs):
        browser_calls.append((method, params or {}))
        return {}

    with patch.object(net, "_start_persistent_chromium_session", return_value=session), \
         patch.object(net, "_devtools_json", side_effect=pages), \
         patch.object(net, "_browser_cdp_call", side_effect=browser_call), \
         patch.object(net, "_persistent_page_cdp_call") as page_call, \
         patch.object(net.time, "sleep"):
        target = net.create_embedded_chromium_target("about:blank", require_bootstrap=True)

    assert target == "bootstrap-1"
    assert session["native_app_target_id"] == "bootstrap-1"
    assert session["bootstrap_claim_reason"] == "expected-url"
    assert session["bootstrap_socket_skipped"] is True
    assert page_call.call_count == 0
    assert [method for method, _ in browser_calls] == ["Target.activateTarget"]


def test_bootstrap_claims_single_canonicalized_page_instead_of_creating_second_target():
    session = {"port": 9222, "launch_url": "about:blank", "default_page_zoom_percent": 100}
    browser_calls = []

    def browser_call(_session, method, params=None, **kwargs):
        browser_calls.append((method, params or {}))
        return {}

    with patch.object(net, "_start_persistent_chromium_session", return_value=session), \
         patch.object(net, "_devtools_json", return_value=[_page("only-page", "https://www.guru3d.com/")]), \
         patch.object(net, "_browser_cdp_call", side_effect=browser_call), \
         patch.object(net, "_persistent_page_cdp_call") as page_call:
        target = net.create_embedded_chromium_target("about:blank", require_bootstrap=True)

    assert target == "only-page"
    assert session["bootstrap_claim_reason"] == "sole-page-fallback"
    assert not any(method == "Target.createTarget" for method, _ in browser_calls)
    page_call.assert_called_once()
    assert page_call.call_args.args[1] == "Page.navigate"
    assert page_call.call_args.args[2] == {"url": "about:blank"}

