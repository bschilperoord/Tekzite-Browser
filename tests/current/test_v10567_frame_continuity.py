from pathlib import Path
import inspect

import main
from engine import net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.73"


def test_hot_native_navigation_keeps_existing_dwm_surface_visible():
    block = inspect.getsource(main.BrowserApp._navigate_embedded)
    assert "keep_live_native_surface = bool(" in block
    assert "self._sync_dwm_host_geometry(show=True, transparent=False)" in block
    assert "not create_new_target" in block


def test_hot_navigation_completion_does_not_repeat_timed_reveal():
    block = inspect.getsource(main.BrowserApp._poll_embedded_navigation)
    assert 'hot_native_reuse = bool(session.get("hot_navigation_reused_native_surface"))' in block
    assert "if (hot_native_reuse and self._embedded_mode" in block
    assert "self._cancel_dwm_host_reveal()" in block
    assert "self._sync_dwm_host_geometry(show=True, transparent=False)" in block


def test_cold_bootstrap_retries_frame_gate_before_reveal():
    start = NET.index("def open_embedded_chromium")
    end = NET.index("def record_embedded_native_recovery", start)
    block = NET[start:end]
    first = block.index("attached_ready = _wait_for_attached_first_frame(session, timeout=2.0)")
    retry = block.index('session["attached_frame_retry_attempted"] = True', first)
    recrop = block.index('session["dwm_force_full_recrop"] = True', retry)
    resize = block.index("resize_embedded_chromium(width, height)", recrop)
    second = block.index("attached_ready = _wait_for_attached_first_frame(session, timeout=2.0)", resize)
    assert first < retry < recrop < resize < second
