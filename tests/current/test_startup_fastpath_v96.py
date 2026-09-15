from pathlib import Path

NET = Path("engine/net.py").read_text(encoding="utf-8")


def test_devtools_wait_does_not_hide_on_every_poll():
    block = NET[NET.index("def _wait_for_devtools"):NET.index("class _StdlibWebSocket")]
    assert "time.sleep(0.01)" in block
    assert "version_info = _devtools_json" in block
    # Hide is done outside the miss loop and once on successful readiness, not per miss.
    assert block.count("_hide_process_windows(process.pid)") <= 2


def test_browser_ws_url_reuses_devtools_version_payload():
    assert '"browser_ws_url": str((wait_info.get("version") or {}).get("webSocketDebuggerUrl") or "")' in NET
    browser = NET[NET.index("def _get_persistent_browser_cdp_channel"):NET.index("def _browser_cdp_call")]
    assert 'session or {}).get("browser_ws_url")' in browser


def test_dwm_presenter_settle_is_off_critical_path():
    block = NET[NET.index("def _position_native_chromium_overlay"):NET.index("def attach_embedded_chromium")]
    assert 'name="tekzite-dwm-presenter-park"' in block
    assert '_park_chromium_top_level_presenters(session, source, passes=3, settle_delay=0.04)' in block
    assert 'threading.Thread' in block
    assert 'time.sleep(0.012)' not in block


def test_cold_resize_kick_is_deferred():
    block = NET[NET.index("def _wait_for_attached_first_frame"):NET.index("def navigate_embedded_chromium")]
    assert "elapsed >= 0.030" in block
