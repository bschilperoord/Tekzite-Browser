from pathlib import Path
from unittest.mock import Mock

import main
import engine.net as net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_soft_tab_close_runs_on_mouse_release_not_press():
    block = MAIN[MAIN.index("def _create_soft_tab"):MAIN.index("def _place_new_tab_button_inline")]
    assert 'canvas.bind("<ButtonRelease-1>", left_click)' in block
    assert 'canvas.bind("<Button-1>", left_click)' not in block
    assert 'canvas.bind("<ButtonRelease-2>"' in block


def test_close_callback_never_starts_chromium_handoff_inline():
    close = MAIN[MAIN.index("def _close_tab(self"):MAIN.index("def _close_active_tab")]
    active = close[close.index("if was_active:"):]
    assert "self._select_replacement_tab_chrome(replacement)" in active
    assert "self._schedule_closed_tab_handoff(replacement, target_id)" in active
    assert "self._switch_tab(" not in active


def test_scheduled_handoff_is_cancelable_before_it_starts():
    block = MAIN[MAIN.index("def _schedule_closed_tab_handoff"):MAIN.index("def _close_tab(self")]
    assert "self.root.after(180, begin_handoff)" in block
    assert "reservation != self._tab_switch_serial" in block
    assert "self.active_tab_id != replacement_id" in block


def test_activation_uses_lock_free_devtools_http_endpoint():
    block = NET[NET.index("def activate_embedded_chromium_target"):NET.index("def close_embedded_chromium_target")]
    assert '_devtools_target_http_command(session, "activate"' in block
    assert "_browser_cdp_call(" not in block


def test_target_close_uses_lock_free_devtools_http_endpoint():
    block = NET[NET.index("def close_embedded_chromium_target"):NET.index("def fetch_rendered_dom")]
    assert '_devtools_target_http_command(session, "close"' in block
    assert "_browser_cdp_call(" not in block


def test_http_target_command_is_loopback_only_and_bounded(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, amount):
            assert amount == 4096
            return b"Target activated"

    called = {}
    def fake_urlopen(url, timeout):
        called["url"] = url
        called["timeout"] = timeout
        return Response()

    monkeypatch.setattr(net, "_stdlib_urlopen", fake_urlopen)
    assert net._devtools_target_http_command({"port": 9222}, "activate", "ABC/123", timeout=0.2)
    assert called["url"] == "http://127.0.0.1:9222/json/activate/ABC%2F123"
    assert called["timeout"] == 0.2

