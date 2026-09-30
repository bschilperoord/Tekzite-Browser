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


def test_page_dialog_modal_fastlane_stops_chromium_background_input():
    assert "_javascript_dialog_modal_active" in inspect.getsource(
        main.BrowserApp._chromium_input_surface_active
    )
    assert "_javascript_dialog_modal_active" in inspect.getsource(
        main.BrowserApp._poll_dwm_keyboard
    )
    assert "_javascript_dialog_modal_active" in inspect.getsource(
        main.BrowserApp._schedule_dwm_pointer_bridge
    )
    assert "_javascript_dialog_modal_active" in inspect.getsource(
        main.BrowserApp._on_root_chromium_key
    )
    assert "_javascript_dialog_modal_active" in inspect.getsource(
        main.BrowserApp._poll_chromium_cursor_probe
    )


def test_page_dialog_modal_fastlane_defers_synchronous_zoom_settle_work():
    zoom_apply = inspect.getsource(main.BrowserApp._run_scheduled_chromium_zoom_apply)
    dwm_refresh = inspect.getsource(main.BrowserApp._run_scheduled_dwm_zoom_refresh)
    resume = inspect.getsource(
        main.BrowserApp._resume_deferred_chromium_ui_work_after_page_dialog
    )

    assert "_javascript_dialog_modal_active" in zoom_apply
    assert "_javascript_dialog_deferred_zoom_all" in zoom_apply
    assert "_javascript_dialog_deferred_zoom_targets" in zoom_apply
    assert "_javascript_dialog_modal_active" in dwm_refresh
    assert "_javascript_dialog_deferred_dwm_zoom_refresh" in dwm_refresh
    assert "_run_scheduled_chromium_zoom_apply" in resume
    assert "_run_scheduled_dwm_zoom_refresh" in resume


def test_page_dialog_modal_fastlane_pauses_periodic_browser_polls():
    page_tick = inspect.getsource(main.BrowserApp._page_state_tick)
    zoom_tick = inspect.getsource(main.BrowserApp._zoom_watchdog_tick)
    page_one = inspect.getsource(main.BrowserApp._poll_one_tab_state)
    assert "_javascript_dialog_modal_active" in page_tick
    assert "root.after(600, self._page_state_tick)" in page_tick
    assert "_javascript_dialog_modal_active" in zoom_tick
    assert "1200, self._zoom_watchdog_tick" in zoom_tick
    assert "_javascript_dialog_modal_active" in page_one
    assert "root.after(250, finish)" in page_one


def test_page_dialog_sets_and_clears_modal_fastlane_around_cdp_answer():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    enter_at = block.index("self._javascript_dialog_modal_active = True")
    hide_at = block.index("_set_dwm_page_dialog_suspended(True)")
    answer_at = block.index("future.result()")
    restore_call_at = block.index("restore_chromium_presentation()", answer_at)
    assert enter_at < hide_at < answer_at < restore_call_at

    restore_helper = block[
        block.index("def restore_chromium_presentation"):
        block.index("def cleanup_overlay")
    ]
    assert "self._javascript_dialog_modal_active = False" in restore_helper
    assert "_schedule_dwm_pointer_bridge(delay=40)" in restore_helper
    assert "_resume_deferred_chromium_ui_work_after_page_dialog()" in restore_helper


def test_page_dialog_uses_content_overlay_not_native_toplevel():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "overlay = tk.Frame(" in block
    assert "self.content_frame" in block
    assert "overlay.place(x=0, y=0, relwidth=1, relheight=1)" in block
    assert "card.place(relx=0.5, rely=0.5, anchor='center')" in block
    assert "_javascript_dialog_last_mode = 'content-overlay'" in block
    assert "self._javascript_dialog_modal_active = True" in block

    assert "tk.Toplevel" not in block
    assert "_new_animated_toplevel" not in block
    assert "grab_set()" not in block
    assert "_raise_toplevel_above_dwm" not in block
    assert "attributes('-topmost'" not in block
    assert "SetForegroundWindow" not in block


def test_page_dialog_has_no_prewarm_or_first_window_activation_path():
    startup = FEATURES[
        FEATURES.index("def _feature_startup"):
        FEATURES.index("def _schedule_network_health_watch")
    ]
    assert "_prewarm_javascript_dialog_ui" not in startup
    assert "def _prewarm_javascript_dialog_ui" not in FEATURES
    assert "def _build_javascript_dialog_shell" not in FEATURES

    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "<Map>" not in block
    assert "after_idle" not in block
    assert "winfo_ismapped" not in block
    assert "persistent_topmost" not in block


def test_page_dialog_suspends_dwm_before_showing_overlay():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    hide_at = block.index("_set_dwm_page_dialog_suspended(True)")
    overlay_at = block.index("overlay.place(x=0, y=0, relwidth=1, relheight=1)")
    assert hide_at < overlay_at


def test_page_dialog_restores_dwm_only_after_cdp_answer_finishes():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    answer_at = block.index("future.result()")
    restore_at = block.index("restore_chromium_presentation()", answer_at)
    assert restore_at > answer_at
    assert "suppress_embedded_chromium_javascript_dialog_ui" not in block


def test_dialog_overlay_records_visible_handoff_timing():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "started = time.perf_counter()" in block
    assert "_javascript_dialog_last_show_ms" in block



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


def test_dialog_target_hint_breaks_first_navigation_target_commit_cycle(monkeypatch):
    target_id = "cold-start-target"
    session = {
        "target_id": target_id,
        "javascript_dialog_browser_channels": {},
        "page_cdp_channels": {},
    }
    monkeypatch.setattr(net, "_CHROMIUM_SESSION", session)
    assert net.get_embedded_chromium_javascript_dialog_target_hint() == target_id


def test_dialog_target_hint_prefers_channel_with_pending_event(monkeypatch):
    session = {
        "target_id": "generic-target",
        "javascript_dialog_browser_channels": {
            "dialog-target": {
                "target_id": "dialog-target",
                "events": [{"type": "confirm"}],
                "dialog_open": True,
                "closed": False,
            }
        },
        "page_cdp_channels": {},
    }
    monkeypatch.setattr(net, "_CHROMIUM_SESSION", session)
    assert (
        net.get_embedded_chromium_javascript_dialog_target_hint()
        == "dialog-target"
    )


def test_tk_dialog_poll_uses_engine_target_before_tab_commit():
    block = FEATURES[
        FEATURES.index("def _javascript_dialog_tick"):
        FEATURES.index("def _show_native_javascript_dialog")
    ]
    assert "get_embedded_chromium_javascript_dialog_target_hint" in block
    assert "_schedule_javascript_dialog_poll(70)" in block


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

