import inspect
import json
from pathlib import Path

import main
from engine import net


ROOT = Path(__file__).resolve().parents[2]
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_javascript_dialog_event_is_sanitized():
    row = net._normalize_javascript_dialog_event(
        {
            "method": "Page.javascriptDialogOpening",
            "params": {
                "type": "confirm",
                "message": "Restart Unbound DNS?",
                "url": "http://192.168.25.254:8083/dashboard",
                "defaultPrompt": "",
                "hasBrowserHandler": True,
            },
        },
        "tab-target",
    )
    assert row == {
        "target_id": "tab-target",
        "type": "confirm",
        "message": "Restart Unbound DNS?",
        "default_prompt": "",
        "url": "http://192.168.25.254:8083/dashboard",
        "origin": "http://192.168.25.254:8083",
        "has_browser_handler": True,
    }


def test_dialog_monitor_is_armed_before_navigation():
    block = NET[NET.index("def navigate_embedded_chromium"):NET.index("def _windows_descendant_pids")]
    assert "ensure_embedded_chromium_javascript_dialog_monitor" in block
    assert block.index("ensure_embedded_chromium_javascript_dialog_monitor") < block.index('"Page.navigate"')
    assert "'Target.attachToTarget'" in NET
    assert "'flatten': True" in NET
    assert "'Page.enable'" in NET
    assert "'Page.handleJavaScriptDialog'" in NET
    assert "'Page.javascriptDialogOpening'" in NET
    assert "session_id=str(channel.get('session_id') or '')" in NET
    assert "def _get_javascript_dialog_page_fallback_channel" in NET
    assert "purpose='dialog-fallback'" in NET
    assert "'ready-dual'" in NET
    assert "'page-fallback'" in NET


def test_tk_owns_alert_confirm_prompt_and_beforeunload_controls():
    assert "_schedule_javascript_dialog_poll(140)" in FEATURES
    assert "def _show_native_javascript_dialog" in FEATURES
    assert "'alert', 'confirm', 'prompt', 'beforeunload'" in FEATURES
    assert "'OK'" in FEATURES
    assert "'Cancel'" in FEATURES
    assert "'Leave'" in FEATURES
    assert "'Stay'" in FEATURES
    assert "win.grab_set()" in FEATURES
    assert "_raise_toplevel_above_dwm(" in FEATURES
    assert "win, hold_ms=520, persistent_topmost=True" in FEATURES


def test_javascript_dialog_topmost_is_not_released_while_modal_is_open():
    source = inspect.getsource(main.BrowserApp._raise_toplevel_above_dwm)
    assert "persistent_topmost=False" in source
    assert "if not persistent_topmost:" in source
    assert "if persistent_topmost:" in source
    assert "flags |= SWP_NOACTIVATE" in source
    assert "SetForegroundWindow" in source


def test_javascript_dialog_arms_input_once_after_toplevel_is_mapped():
    block = FEATURES[
        FEATURES.index("win.protocol('WM_DELETE_WINDOW', close_action)"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "def arm_dialog_input" in block
    assert "win.winfo_ismapped()" in block
    bind_pos = block.index("win.bind('<Map>', arm_after_map, add='+')")
    show_pos = block.index("win.deiconify()")
    assert bind_pos < show_pos
    assert "win.after_idle(arm_dialog_input)" in block
    assert "win.after(48, arm_dialog_input)" in block
    assert "state['input_armed'] = True" in block
    assert "state['arm_attempts']" not in block
    assert "grab_current()" not in block
    assert "win.after(20, arm_dialog_input)" not in block
    assert "win.after(80, reassert_dialog_z_order)" not in block
    assert "win.after(220, reassert_dialog_z_order)" not in block


def test_fixed_size_page_dialog_does_not_drain_tk_idle_queue():
    center = inspect.getsource(main.BrowserApp._screen_center_geometry)
    assert "if width is None or height is None:" in center
    assert center.index("if width is None or height is None:") < center.index("win.update_idletasks()")

    raise_source = inspect.getsource(main.BrowserApp._raise_toplevel_above_dwm)
    assert "prepare_tk=True" in raise_source
    assert "if prepare_tk:" in raise_source

    block = FEATURES[
        FEATURES.index("def arm_dialog_input"):
        FEATURES.index("def arm_after_map")
    ]
    assert "prepare_tk=False" in block
    assert "update_idletasks()" not in block


def test_page_dialog_shell_is_prewarmed_before_first_real_dialog():
    assert "def _prewarm_javascript_dialog_ui" in FEATURES
    startup = FEATURES[
        FEATURES.index("def _feature_startup"):
        FEATURES.index("def _schedule_network_health_watch")
    ]
    assert "self.root.after(350, self._prewarm_javascript_dialog_ui)" in startup

    prewarm = FEATURES[
        FEATURES.index("def _prewarm_javascript_dialog_ui"):
        FEATURES.index("def _show_native_javascript_dialog")
    ]
    assert "_build_javascript_dialog_shell()" in prewarm
    assert "560x330-32000-32000" in prewarm
    assert "win.deiconify()" in prewarm
    assert "win.withdraw()" in prewarm
    assert "_javascript_dialog_prewarm_ready = True" in prewarm


def test_first_real_page_dialog_reuses_prewarmed_shell():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "_javascript_dialog_prewarm_shell" in block
    assert "_javascript_dialog_last_used_prewarm" in block
    assert "shell = self._build_javascript_dialog_shell()" in block
    assert "title.configure(text=title_text)" in block
    assert "host_label.configure(text=str(host))" in block
    assert "message_label.configure(text=shown_message)" in block
    assert "_javascript_dialog_last_show_ms" in block


def test_non_animated_toplevel_is_visible_immediately():
    source = inspect.getsource(main.BrowserApp._new_animated_toplevel)
    assert '0.0 if (auto_animate and self._motion_enabled()) else 1.0' in source


def test_page_dialog_suspends_only_dwm_presentation():
    sync_source = inspect.getsource(main.BrowserApp._sync_dwm_host_geometry)
    helper_source = inspect.getsource(main.BrowserApp._set_dwm_page_dialog_suspended)
    assert "not self._dwm_host_suspended_for_page_dialog" in sync_source
    assert "self._dwm_host_suspended_for_page_dialog = suspended" in helper_source
    assert "_sync_dwm_host_geometry(show=not suspended" in helper_source


def test_page_dialog_restores_dwm_only_after_cdp_answer_finishes():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    hide_at = block.index("_set_dwm_page_dialog_suspended(True)")
    show_at = block.index("win.deiconify()", hide_at)
    answer_at = block.index("future.result()")
    restore_at = block.index("restore_chromium_presentation()", answer_at)
    assert hide_at < show_at
    assert restore_at > answer_at
    assert "suppress_embedded_chromium_javascript_dialog_ui" not in block


class _FakeRoot:
    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080


def test_normal_startup_geometry_is_centered(monkeypatch):
    monkeypatch.setattr(main.sys, "platform", "linux")
    assert main._centered_startup_geometry(_FakeRoot(), 1280, 800) == "1280x800+320+140"


def test_browser_init_uses_centered_geometry_except_tab_tearoff():
    source = inspect.getsource(main.BrowserApp.__init__)
    assert "_centered_startup_geometry(" in source
    assert 'requested_position = getattr(self, "_requested_window_position", None)' in source
    assert "if requested_position:" in source
    assert "self.root.geometry(_centered_startup_geometry(" in source


def test_browser_target_session_filters_and_queues_matching_dialog_events():
    channel = {
        "target_id": "tab-target",
        "session_id": "session-1",
        "events": [],
    }
    ignored = net._record_javascript_dialog_browser_event(
        channel,
        {
            "sessionId": "other-session",
            "method": "Page.javascriptDialogOpening",
            "params": {
                "type": "confirm",
                "message": "wrong target",
                "url": "https://wrong.example/",
            },
        },
    )
    assert ignored is None
    assert channel["events"] == []

    event = net._record_javascript_dialog_browser_event(
        channel,
        {
            "sessionId": "session-1",
            "method": "Page.javascriptDialogOpening",
            "params": {
                "type": "confirm",
                "message": "Restart Kea DHCPv4?",
                "url": "http://192.168.25.254:8083/",
                "hasBrowserHandler": True,
            },
        },
    )
    assert event["target_id"] == "tab-target"
    assert event["type"] == "confirm"
    assert event["message"] == "Restart Kea DHCPv4?"
    assert channel["events"] == [event]
    assert channel["dialog_open"] is True


class _DialogProtocolWs:
    def __init__(self):
        self.sent = []
        self.responses = [
            json.dumps({
                "sessionId": "session-1",
                "method": "Page.javascriptDialogOpening",
                "params": {
                    "type": "confirm",
                    "message": "Restart service?",
                    "url": "http://router.test/",
                    "hasBrowserHandler": True,
                },
            }),
            json.dumps({"id": 5000, "result": {}}),
        ]

    def settimeout(self, _timeout):
        pass

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        return self.responses.pop(0)


def test_browser_session_call_preserves_dialog_event_while_waiting_for_response():
    ws = _DialogProtocolWs()
    channel = {
        "target_id": "tab-target",
        "session_id": "session-1",
        "ws": ws,
        "lock": net.threading.RLock(),
        "next_message_id": 5000,
        "events": [],
        "closed": False,
    }
    result = net._javascript_dialog_browser_call(
        channel,
        "Page.enable",
        {},
        session_id="session-1",
        timeout=0.5,
    )
    assert result == {}
    assert ws.sent[0]["sessionId"] == "session-1"
    assert ws.sent[0]["method"] == "Page.enable"
    assert channel["events"][0]["type"] == "confirm"
    assert channel["events"][0]["message"] == "Restart service?"

class _DirectPageDialogWs:
    def __init__(self):
        self.responses = [
            json.dumps({
                "method": "Page.javascriptDialogOpening",
                "params": {
                    "type": "confirm",
                    "message": "Restart Kea DHCPv6?",
                    "url": "http://192.168.25.254:8083/",
                    "hasBrowserHandler": True,
                },
            }),
        ]

    def settimeout(self, _timeout):
        pass

    def recv(self):
        return self.responses.pop(0)


def test_dialog_poll_uses_direct_page_fallback_when_browser_observer_is_silent(monkeypatch):
    target_id = "router-target"
    direct = {
        "target_id": target_id,
        "ws": _DirectPageDialogWs(),
        "lock": net.threading.RLock(),
        "closed": False,
        "enabled_domains": {"Page"},
        "javascript_dialog_events": [],
    }
    session = {
        "page_cdp_channels": {f"{target_id}:dialog-fallback": direct},
        "javascript_dialog_browser_channels": {},
    }

    def fail_browser(*_args, **_kwargs):
        raise RuntimeError("browser observer unavailable")

    monkeypatch.setattr(net, "_CHROMIUM_SESSION", session)
    monkeypatch.setattr(net, "_get_javascript_dialog_browser_channel", fail_browser)
    monkeypatch.setattr(
        net,
        "_get_javascript_dialog_page_fallback_channel",
        lambda *_args, **_kwargs: direct,
    )

    rows = net.poll_embedded_chromium_javascript_dialogs(target_id, timeout=0.04)
    assert len(rows) == 1
    assert rows[0]["type"] == "confirm"
    assert rows[0]["message"] == "Restart Kea DHCPv6?"
    assert session["javascript_dialog_resolution_paths"][target_id] == "page-fallback"
    assert session["javascript_dialog_monitor_stage"] == "event-page-fallback"

