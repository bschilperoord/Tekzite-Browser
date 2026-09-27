import json
from pathlib import Path

from engine import net

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_chromium_uses_explicit_debug_port_not_automation_port_zero():
    assert '"--remote-debugging-port=0"' not in NET
    assert 'f"--remote-debugging-port={port}"' in NET
    assert 'port = _free_loopback_port()' in NET
    assert 'requested_port=port' in NET


def test_wait_for_devtools_can_poll_explicit_port_without_active_port_file(monkeypatch):
    class Proc:
        pid = 12345
        def poll(self):
            return None

    def no_active_file(_profile):
        raise AssertionError("explicit-port mode must not depend on DevToolsActivePort")

    monkeypatch.setattr(net, "_read_devtools_active_port", no_active_file)
    monkeypatch.setattr(net, "_hide_process_windows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(net, "_listener_pid_for_port", lambda _port: Proc.pid)
    monkeypatch.setattr(net, "allow_loopback_port", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(net, "revoke_loopback_port", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(net, "_devtools_json", lambda port, path, timeout: {
        "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/test"
    })

    result = net._wait_for_devtools("unused", Proc(), timeout=0.2, requested_port=45678)
    assert result["port"] == 45678
    assert result["version"]["webSocketDebuggerUrl"].startswith("ws://127.0.0.1:45678/")


def test_cloudflare_compatibility_exception_is_referer_only():
    rules = json.loads((ROOT / "chromium_zoom_extension" / "privacy_headers.json").read_text(encoding="utf-8"))
    referer_rule = next(r for r in rules if any(
        h.get("header") == "referer" for h in r["action"].get("requestHeaders", [])
    ))
    excluded = set(referer_rule["condition"].get("excludedRequestDomains", []))
    assert {"chatgpt.com", "openai.com", "challenges.cloudflare.com"} <= excluded

    metadata_rule = next(r for r in rules if any(
        h.get("header") == "x-client-data" for h in r["action"].get("requestHeaders", [])
    ))
    assert "excludedRequestDomains" not in metadata_rule["condition"]
    headers = {h.get("header") for h in metadata_rule["action"].get("requestHeaders", [])}
    assert {"x-client-data", "x-chrome-connected"} <= headers
