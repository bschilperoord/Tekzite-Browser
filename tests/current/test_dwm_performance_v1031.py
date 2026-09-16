from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version_1031():
    assert 'BROWSER_VERSION = "10.5.1"' in MAIN


def test_steady_state_dwm_resize_has_fast_path_without_flush():
    block = NET[NET.index("def _resize_existing_dwm_thumbnail_fast"):NET.index("def request_embedded_chromium_dwm_recrop")]
    assert "DwmUpdateThumbnailProperties" in block
    assert "dwm_fast_resize_count" in block
    assert "dwm_fast_resize_noop_count" in block
    # The comment may mention the API, but the helper must not invoke it.
    assert ".DwmFlush(" not in block


def test_normal_dwm_resize_prefers_fast_path_and_navigation_can_force_recrop():
    resize = NET[NET.index("def resize_embedded_chromium"):NET.index("def focus_embedded_chromium")]
    assert "_resize_existing_dwm_thumbnail_fast" in resize
    assert 'pop("dwm_force_full_recrop", False)' in resize
    recrop = MAIN[MAIN.index("def _refresh_dwm_crop_after_navigation"):MAIN.index("@staticmethod", MAIN.index("def _refresh_dwm_crop_after_navigation"))]
    assert "request_embedded_chromium_dwm_recrop()" in recrop


def test_presenter_parking_is_rate_limited_and_single_flight():
    block = NET[NET.index("def _position_native_chromium_overlay"):NET.index("def _wait_for_live_embed_owner")]
    assert 'dwm_presenter_last_park_at' in block
    assert 'dwm_presenter_park_thread_running' in block
    assert '>= 1.0' in block


def test_drag_batches_top_level_and_dwm_moves():
    block = MAIN[MAIN.index("def _native_move_window_drag"):MAIN.index("def _start_window_drag")]
    assert "BeginDeferWindowPos(2)" in block
    assert "DeferWindowPos" in block
    assert "EndDeferWindowPos" in block
    assert "_native_drag_last_xy" in block


def test_dwm_move_only_geometry_uses_swp_nosize():
    block = MAIN[MAIN.index("def _sync_dwm_host_geometry"):MAIN.index("def _schedule_dwm_geometry_sync")]
    assert "same_size" in block
    assert "flags |= SWP_NOSIZE" in block
