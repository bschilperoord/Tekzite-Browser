from __future__ import annotations

import types

import pytest

from engine import net


class _AliveProcess:
    def poll(self):
        return None


def test_pick_devtools_page_retries_transient_empty_linux_list(monkeypatch):
    calls = {"count": 0}

    def fake_json(port, path, timeout=1.0):
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        return [{
            "id": "page-1",
            "type": "page",
            "url": "chrome://newtab/",
            "webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/page/page-1",
        }]

    monkeypatch.setattr(net, "_devtools_json", fake_json)
    monkeypatch.setattr(net.os, "name", "posix", raising=False)
    page = net._pick_devtools_page(1, {"process": _AliveProcess()})

    assert calls["count"] >= 2
    assert page["id"] == "page-1"


def test_pick_devtools_page_error_reports_observed_targets(monkeypatch):
    monkeypatch.setattr(
        net,
        "_devtools_json",
        lambda *args, **kwargs: [{
            "id": "worker-1",
            "type": "service_worker",
            "url": "https://example.invalid/sw.js",
        }],
    )
    monkeypatch.setattr(net.os, "name", "nt", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        net._pick_devtools_page(1, {"process": _AliveProcess()})

    message = str(excinfo.value)
    assert "no debuggable page" in message
    assert "service_worker:https://example.invalid/sw.js" in message
