from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert 'BROWSER_VERSION = "10.5.73"' in MAIN


def test_dwm_mapping_uses_live_native_to_css_scale():
    block = MAIN[MAIN.index("def _dwm_local_to_chromium_xy"):MAIN.index("def _surface_xy")]
    assert "get_embedded_chromium_input_scale()" in block
    assert "x /= scale_x" in block
    assert "y /= scale_y" in block


def test_input_metrics_measure_css_viewport_and_device_scale():
    start = NET.index("def _refresh_dwm_input_metrics")
    end = NET.index("def get_embedded_chromium_input_scale", start)
    block = NET[start:end]
    assert "window.innerWidth" in block
    assert "window.innerHeight" in block
    assert "window.devicePixelRatio" in block
    assert 'session["dwm_input_css_scale_x"]' in block
    assert 'session["dwm_input_css_scale_y"]' in block


def test_first_visible_click_has_metrics_before_reveal():
    start = NET.index("def open_embedded_chromium")
    end = NET.index("def record_embedded_native_recovery", start)
    block = NET[start:end]
    ready = block.index("_wait_for_embedded_chromium_input_ready")
    metrics = block.index("_refresh_dwm_input_metrics", ready)
    startup_focus = block.index("_focus_embedded_chromium_startup_input", metrics)
    assert ready < metrics < startup_focus


def test_browser_zoom_does_not_get_double_applied():
    start = NET.index("def _refresh_dwm_input_metrics")
    end = NET.index("def dispatch_embedded_chromium_mouse", start)
    block = NET[start:end]
    assert "Browser zoom is already represented in devicePixelRatio" in block

