from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def _block(name, next_name=None):
    start = MAIN.index(f"    def {name}(")
    if next_name:
        end = MAIN.index(f"    def {next_name}(", start)
    else:
        end = MAIN.find("\n    def ", start + 8)
        if end < 0:
            end = len(MAIN)
    return MAIN[start:end]


def test_drag_priority_state_is_initialized():
    for token in (
        "self._window_drag_deferred_recrop = None",
        "self._window_drag_deferred_probe = None",
        "self._window_drag_deferred_zoom_all = False",
        "self._window_drag_deferred_zoom_targets = set()",
        "self._window_drag_deferred_dwm_zoom_refresh = False",
        "self._window_drag_settle_after_id = None",
    ):
        assert token in MAIN


def test_root_configure_does_zero_work_during_drag():
    block = _block("_on_root_configure_native_overlay")
    guard = 'if getattr(self, "_window_drag_active", False):'
    assert guard in block
    assert block.index(guard) < block.index("self._apply_window_rounding()")


def test_rounding_and_drag_prewarm_do_not_drain_idle_work_mid_drag():
    rounding = _block("_apply_window_rounding")
    assert 'if getattr(self, "_window_drag_active", False):' in rounding
    assert rounding.index('if getattr(self, "_window_drag_active", False):') < rounding.index("self.root.update_idletasks()")

    prewarm = _block("_prewarm_native_window_drag")
    assert 'if not getattr(self, "_window_drag_active", False):' in prewarm
    assert "self.root.update_idletasks()" in prewarm


def test_queued_dwm_geometry_is_preserved_until_release():
    block = _block("_schedule_dwm_geometry_sync")
    guard = 'if getattr(self, "_window_drag_active", False):'
    assert guard in block
    assert block.index(guard) < block.index("do_resize = bool(self._dwm_pending_resize)")
    # Pending state must not be cleared before the drag guard.
    before_guard = block[:block.index(guard)]
    assert "self._dwm_pending_resize = False" not in before_guard


def test_startup_recrops_and_screen_probes_defer_during_drag():
    recrop = _block("_refresh_dwm_crop_after_navigation")
    assert "self._window_drag_deferred_recrop = (generation, int(delay_index))" in recrop
    assert recrop.index("_window_drag_deferred_recrop") < recrop.index("request_embedded_chromium_dwm_recrop()")

    probe = _block("_probe_visible_embedded_surface")
    assert "self._window_drag_deferred_probe = (" in probe
    assert probe.index("_window_drag_deferred_probe") < probe.index("ImageGrab.grab(")


def test_navigation_completion_waits_for_drag_release():
    block = _block("_poll_embedded_navigation")
    assert '32 if getattr(self, "_window_drag_active", False) else 8' in block
    assert 'if getattr(self, "_window_drag_active", False):' in block
    guard = block.index('if getattr(self, "_window_drag_active", False):', block.index("future.done()"))
    assert guard < block.index("future.result()")


def test_zoom_settle_and_watchdog_are_drag_aware():
    scheduled = _block("_run_scheduled_chromium_zoom_apply", "_schedule_chromium_zoom_apply")
    assert "self._window_drag_deferred_zoom_all = True" in scheduled
    assert "self._window_drag_deferred_zoom_targets.add(target_id)" in scheduled

    dwm = _block("_run_scheduled_dwm_zoom_refresh", "_schedule_dwm_zoom_refresh")
    assert "self._window_drag_deferred_dwm_zoom_refresh = True" in dwm

    watchdog = _block("_zoom_watchdog_tick")
    assert "self.root.after(300, self._zoom_watchdog_tick)" in watchdog
    assert watchdog.index("_window_drag_active") < watchdog.index("check_embedded_chromium_zoom")


def test_taskbar_and_pointer_watchdogs_back_off_during_drag():
    taskbar = _block("_taskbar_presence_guard")
    assert "self._schedule_taskbar_presence_guard(300)" in taskbar

    pointer = _block("_poll_dwm_pointer_bridge")
    assert "self._schedule_dwm_pointer_bridge(delay=48)" in pointer
    assert pointer.index("_window_drag_active") < pointer.index("GetCursorPos")


def test_page_state_ui_updates_wait_for_drag_release():
    tick = _block("_page_state_tick")
    assert "self.root.after(250, self._page_state_tick)" in tick

    poll = _block("_poll_one_tab_state")
    assert 'if getattr(self, "_window_drag_active", False):' in poll
    assert "self.root.after(80, finish)" in poll


def test_drag_can_lazily_adopt_dwm_surface_created_after_mouse_down():
    block = _block("_native_move_window_drag")
    assert "if (offset is None and self._dwm_host_rect is not None" in block
    assert "anchor = self._native_drag_last_xy" in block
    assert "self._native_drag_dwm_offset = offset" in block


def test_drag_start_cancels_pending_geometry_timer_but_keeps_flags():
    block = _block("_start_window_drag")
    assert "self.root.after_cancel(self._dwm_geometry_after_id)" in block
    assert "self._dwm_pending_resize = False" not in block
    assert "self._dwm_pending_force_resize = False" not in block


def test_drag_release_replays_deferred_work_in_staggered_slices():
    end = _block("_end_window_drag", "_schedule_post_drag_maintenance")
    assert "self._schedule_post_drag_maintenance()" in end

    flush = _block("_flush_post_drag_maintenance")
    assert "self.root.after(35, self._refresh_dwm_crop_after_navigation, *recrop)" in flush
    assert "self.root.after(85, self._run_scheduled_chromium_zoom_apply, None, True)" in flush
    assert "self.root.after(150, self._run_scheduled_dwm_zoom_refresh)" in flush
    assert "self.root.after(220, self._probe_visible_embedded_surface, *probe)" in flush
    assert flush.index("35, self._refresh_dwm_crop_after_navigation") < flush.index("220, self._probe_visible_embedded_surface")
