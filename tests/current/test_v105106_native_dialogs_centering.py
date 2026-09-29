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


def test_tk_owns_alert_confirm_prompt_and_beforeunload_controls():
    assert "_schedule_javascript_dialog_poll(20)" in FEATURES
    assert "def _show_native_javascript_dialog" in FEATURES
    assert "'alert', 'confirm', 'prompt', 'beforeunload'" in FEATURES
    assert "'OK'" in FEATURES
    assert "'Cancel'" in FEATURES
    assert "'Leave'" in FEATURES
    assert "'Stay'" in FEATURES
    assert "win.grab_set()" in FEATURES
    assert "_raise_toplevel_above_dwm(win, hold_ms=520)" in FEATURES


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


def test_auto_animate_false_dialogs_are_not_created_fully_transparent():
    source = inspect.getsource(main.BrowserApp._new_animated_toplevel)
    assert "0.0 if (auto_animate and self._motion_enabled()) else 1.0" in source
    assert "_bind_native_dialog_owner" in source


def test_parent_centered_small_modals_opt_out_of_second_centering_pass():
    for method in (
        main.BrowserApp._show_message,
        main.BrowserApp._ask_yes_no,
        main.BrowserApp._ask_string_animated,
    ):
        source = inspect.getsource(method)
        assert "auto_center=False" in source


def test_windows_dialog_raise_prefers_native_owner_over_global_topmost():
    source = inspect.getsource(main.BrowserApp._raise_toplevel_above_dwm)
    assert "_bind_native_dialog_owner" in source
    assert "GWLP_HWNDPARENT" in inspect.getsource(main.BrowserApp._bind_native_dialog_owner)
    assert "HWND_TOP = 0" in inspect.getsource(main.BrowserApp._bind_native_dialog_owner)
    assert "wintypes.HWND(HWND_TOPMOST)" not in source


def test_permission_prompt_is_modal_and_uses_shared_dwm_raise_path():
    block = FEATURES[
        FEATURES.index("def _show_permission_request_prompt"):
        FEATURES.index("def _show_permissions_manager")
    ]
    assert "win.grab_set()" in block
    assert "_raise_toplevel_above_dwm(win, hold_ms=520)" in block


def test_settings_dialog_uses_native_owner_path_instead_of_direct_topmost():
    source = inspect.getsource(main.BrowserApp.show_preferences)
    assert "_bind_native_dialog_owner(win, self.root)" in source
    assert "_raise_toplevel_above_dwm(win, hold_ms=520)" in source
    assert 'win.attributes("-topmost", True)' not in source


def test_page_dialog_suspends_dwm_chromium_surface():
    sync_source = inspect.getsource(main.BrowserApp._sync_dwm_host_geometry)
    helper_source = inspect.getsource(main.BrowserApp._set_dwm_page_dialog_suspended)
    assert "transparent" in sync_source
    assert "self._dwm_host_suspended_for_page_dialog" in sync_source
    assert "self._dwm_page_dialog_visual_preblocked" in sync_source
    assert "self._dwm_host_suspended_for_page_dialog = suspended" in helper_source
    assert "user32.ShowWindow(hwnd, 0)" not in helper_source
    fast_source = inspect.getsource(main.BrowserApp._set_dwm_page_dialog_visual_fast)
    assert "ShowWindowAsync" in fast_source
    assert "_sync_dwm_host_geometry(show=True, transparent=suspended)" in helper_source


def test_native_page_dialog_hides_chromium_until_cdp_answer_finishes():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]

    # Open phase: Chromium is hidden before the Tk dialog is made visible.
    hide_at = block.index("_set_dwm_page_dialog_suspended(True)")
    show_dialog_at = block.index("win.deiconify()")
    assert hide_at < show_dialog_at

    # Close phase lives in nested callbacks defined earlier in source text, so
    # verify its internal runtime sequence independently of the open phase.
    decide = block[
        block.index("def decide(accept, prompt_text=None):"):
        block.index("header = tk.Frame")
    ]
    result_at = decide.index("future.result()")
    settle_at = decide.index(
        "self.root.after(40, lambda: finish_native_teardown(ok))", result_at
    )
    assert result_at < settle_at

    teardown = decide[
        decide.index("def finish_native_teardown(ok):"):
        decide.index("def finish_answer():")
    ]
    destroy_at = teardown.index("destroy_native_dialog()")
    restore_at = teardown.index("self.root.after(40, restore_after_native_close)")
    assert destroy_at < restore_at
    assert "_set_dwm_page_dialog_suspended(False)" in block

def test_javascript_dialog_watcher_has_no_large_polling_blind_spot():
    block = FEATURES[
        FEATURES.index("def _schedule_javascript_dialog_poll"):
        FEATURES.index("def _show_native_javascript_dialog")
    ]
    assert "timeout=0.32" in block
    assert "self.root.after(8, finish)" in block
    assert "_schedule_javascript_dialog_poll(20 if rows else 2)" in block
    assert "max(1, int(delay_ms))" in block
    assert "90 if rows else 140" not in block


def test_page_dialog_suppression_never_blocks_tk_on_dwm_hide():
    source = inspect.getsource(main.BrowserApp._set_dwm_page_dialog_visual_fast)
    assert "SetLayeredWindowAttributes" in source
    assert "target_alpha = 0 if hidden else 255" in source
    assert "ShowWindowAsync" in source
    assert "user32.ShowWindow(hwnd, 0)" not in source


def test_page_dialog_hides_chromium_before_tk_window_is_built():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    hide_at = block.index("_set_dwm_page_dialog_suspended(True)")
    window_at = block.index("self._new_animated_toplevel")
    assert hide_at < window_at
    assert "self.root.after(8, finish_answer)" in block


def test_page_dialog_has_dedicated_serialized_cdp_executor():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'thread_name_prefix="tekzite-js-dialog"' in source
    block = FEATURES[
        FEATURES.index("def _javascript_dialog_tick"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "self._javascript_dialog_executor.submit(" in block
    assert "poll_embedded_chromium_javascript_dialogs" in block
    assert "resolve_embedded_chromium_javascript_dialog" in block


def test_page_dialog_pauses_dwm_input_watchdogs():
    source = inspect.getsource(main.BrowserApp._set_dwm_page_dialog_suspended)
    assert "self._stop_dwm_keyboard_poll()" in source
    assert 'self.root.after_cancel(after_id)' in source
    assert "self._dwm_pointer_after_id = None" in source
    assert "self._chromium_left_button_down = False" in source
    assert "self._schedule_dwm_pointer_bridge(delay=16)" in source
    assert "self._schedule_dwm_keyboard_poll(delay=18)" in source


def test_native_dialog_activation_is_explicit_but_does_not_steal_cross_app_focus():
    source = inspect.getsource(main.BrowserApp._activate_native_dialog)
    assert "SetForegroundWindow" in source
    assert "SetActiveWindow" in source
    assert "SetFocus" in source
    assert "same_app_foreground" in source
    assert "int(foreground_pid.value) == int(os.getpid())" in source


def test_page_dialog_is_fully_built_hidden_before_first_visible_frame():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    create_at = block.index("self._new_animated_toplevel")
    withdraw_at = block.index("win.withdraw()", create_at)
    deiconify_at = block.index("win.deiconify()", withdraw_at)
    activate_at = block.index("self._activate_native_dialog(win)", deiconify_at)
    grab_at = block.index("win.grab_set()", activate_at)
    assert create_at < withdraw_at < deiconify_at < activate_at < grab_at
    assert "win.after(0, reinforce_activation)" in block


def test_page_dialog_closes_without_generic_fade_callback_churn():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert 'getattr(win, "_tekzite_original_destroy", None)' in block


def test_page_dialog_keeps_dwm_destination_mapped_while_transparent():
    source = inspect.getsource(main.BrowserApp._sync_dwm_host_geometry)
    should_show = source[source.index("should_show = bool("):source.index("if should_show", source.index("should_show = bool("))]
    assert "_dwm_host_suspended_for_minimize" in should_show
    assert "_dwm_host_suspended_for_page_dialog" not in should_show
    assert "transparent" in source
    assert "self._dwm_host_suspended_for_page_dialog" in source
    assert "self._dwm_page_dialog_visual_preblocked" in source


def test_dwm_visibility_changes_prefer_async_window_mapping():
    source = inspect.getsource(main.BrowserApp._sync_dwm_host_geometry)
    assert source.count("ShowWindowAsync") >= 2


def test_page_dialog_uses_single_hwnd_owner_pass():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "self._bind_native_dialog_owner(win, self.root)" in block
    assert "self._activate_native_dialog(win)" in block
    assert "_raise_toplevel_above_dwm(win, hold_ms=520)" not in block


def test_native_dialog_activation_reuses_materialized_hwnd():
    source = inspect.getsource(main.BrowserApp._activate_native_dialog)
    cached_at = source.index('getattr(win, "_tekzite_native_dialog_hwnd", 0)')
    idle_at = source.index("win.update_idletasks()")
    assert cached_at < idle_at


def test_page_dialog_disables_delayed_generic_prepare():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    assert "auto_prepare=False" in block
    assert "auto_center=False" in block


def test_toplevel_factory_can_skip_delayed_prepare_callback():
    source = inspect.getsource(main.BrowserApp._new_animated_toplevel)
    assert "auto_prepare=True" in source
    assert 'win._tekzite_auto_prepare = bool(auto_prepare)' in source
    assert 'if getattr(win, "_tekzite_auto_prepare", True):' in source


def test_native_page_dialog_path_is_prewarmed_before_first_real_dialog():
    startup = FEATURES[
        FEATURES.index("def _feature_startup"):
        FEATURES.index("def _schedule_network_health_watch")
    ]
    warmup = FEATURES[
        FEATURES.index("def _prewarm_native_page_dialog"):
        FEATURES.index("def _schedule_network_health_watch")
    ]
    assert "self.root.after(" in startup
    assert "350, self._prewarm_native_page_dialog" in startup
    assert "auto_prepare=False" in warmup
    assert "win.withdraw()" in warmup
    assert "self._bind_native_dialog_owner(win, self.root)" in warmup
    assert "button.event_generate('<Enter>')" in warmup
    assert "win.deiconify()" not in warmup


def test_cdp_worker_preblocks_chromium_before_tk_completion_poll():
    block = FEATURES[
        FEATURES.index("def _javascript_dialog_tick"):
        FEATURES.index("def _show_native_javascript_dialog")
    ]
    wait_at = block.index("def wait_for_dialog()")
    poll_at = block.index("poll_embedded_chromium_javascript_dialogs", wait_at)
    preblock_at = block.index("_set_dwm_page_dialog_visual_fast(True)", poll_at)
    submit_at = block.index("self._javascript_dialog_executor.submit(wait_for_dialog)", preblock_at)
    tk_finish_at = block.index("def finish():", submit_at)
    assert wait_at < poll_at < preblock_at < submit_at < tk_finish_at


def test_geometry_refresh_cannot_resurrect_chromium_during_preblock_gap():
    source = inspect.getsource(main.BrowserApp._sync_dwm_host_geometry)
    assert "or self._dwm_page_dialog_visual_preblocked" in source
    fast = inspect.getsource(main.BrowserApp._set_dwm_page_dialog_visual_fast)
    assert "self._dwm_page_dialog_visual_preblocked = hidden" in fast


def test_native_dialog_failure_releases_worker_visual_preblock():
    block = FEATURES[
        FEATURES.index("def _javascript_dialog_tick"):
        FEATURES.index("def _show_native_javascript_dialog")
    ]
    assert "_set_dwm_page_dialog_visual_fast(False)" in block


def test_chromium_stays_hidden_until_after_tk_dialog_teardown():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    decide = block[block.index("def decide(accept, prompt_text=None):"):block.index("header = tk.Frame")]
    prehide_at = decide.index("_set_dwm_page_dialog_visual_fast(True)")
    submit_at = decide.index("self._javascript_dialog_executor.submit(work)")
    result_at = decide.index("future.result()")
    settle_at = decide.index("self.root.after(40, lambda: finish_native_teardown(ok))")
    destroy_def_at = decide.index("def destroy_native_dialog():")
    teardown_at = decide.index("def finish_native_teardown(ok):")
    restore_schedule_at = decide.index("self.root.after(40, restore_after_native_close)")
    assert prehide_at < submit_at < result_at < settle_at
    assert destroy_def_at < teardown_at < restore_schedule_at


def test_success_path_does_not_restore_chromium_before_native_close():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    decide = block[block.index("def decide(accept, prompt_text=None):"):block.index("header = tk.Frame")]
    teardown = decide[
        decide.index("def finish_native_teardown(ok):"):
        decide.index("def finish_answer():")
    ]
    assert "_set_dwm_page_dialog_visual_fast(True)" in teardown
    assert "destroy_native_dialog()" in teardown
    assert "self.root.after(40, restore_after_native_close)" in teardown
    assert teardown.index("destroy_native_dialog()") < teardown.index(
        "self.root.after(40, restore_after_native_close)"
    )


def test_post_cdp_settle_keeps_tk_dialog_visible_across_compositor_frames():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    decide = block[block.index("def decide(accept, prompt_text=None):"):block.index("header = tk.Frame")]
    finish = decide[decide.index("def finish_answer():"):]
    assert "_set_dwm_page_dialog_visual_fast(True)" in finish
    assert "self.root.after(40, lambda: finish_native_teardown(ok))" in finish


def test_net_waits_for_real_javascript_dialog_closed_event():
    net_source = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
    resolve = net_source[
        net_source.index("def resolve_embedded_chromium_javascript_dialog"):
        net_source.index("def set_embedded_chromium_permission")
    ]
    waiter = net_source[
        net_source.index("def _wait_for_javascript_dialog_closed"):
        net_source.index("def resolve_embedded_chromium_javascript_dialog")
    ]
    recorder = net_source[
        net_source.index("def _record_javascript_dialog_browser_event"):
        net_source.index("def _javascript_dialog_browser_call")
    ]
    assert "_wait_for_javascript_dialog_closed(" in resolve
    assert "channel['dialog_open'] = False" not in resolve
    assert "Page.javascriptDialogClosed" in waiter
    assert "last_dialog_closed_at" in recorder
    assert "last_dialog_close_confirmed" in resolve


def test_close_handoff_uses_multi_frame_hidden_guard():
    block = FEATURES[
        FEATURES.index("def _show_native_javascript_dialog"):
        FEATURES.index("def _schedule_permission_prompt_poll")
    ]
    decide = block[
        block.index("def decide(accept, prompt_text=None):"):
        block.index("header = tk.Frame")
    ]
    assert "self.root.after(40, lambda: finish_native_teardown(ok))" in decide
    assert "self.root.after(40, restore_after_native_close)" in decide
