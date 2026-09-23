from pathlib import Path

import engine.net as net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version():
    assert 'BROWSER_VERSION = "10.5.73"' in MAIN


def test_dwm_input_metrics_prefer_visible_pixel_contract(monkeypatch):
    # Simulate the exact maximize race: DWM is already 1920x900, Chromium's
    # cached RenderWidgetHost still describes the old 1200x700 window, while
    # the CSS viewport reports 1536x720 at 125% native/CSS scaling.
    session = {
        "port": 9222,
        "target_id": "page-1",
        "dwm_thumbnail_pixel_contract": (1920, 900),
        "dwm_render_size_after_chrome_expand": (1200, 700),
    }
    monkeypatch.setattr(net, "_EDGE_SESSION", session)
    monkeypatch.setattr(
        net,
        "_persistent_page_cdp_call",
        lambda *args, **kwargs: {
            "result": {
                "value": {"iw": 1536, "ih": 720, "dpr": 1.25, "vv": 1.0}
            }
        },
    )

    sx, sy = net._refresh_dwm_input_metrics(session, target_id="page-1", timeout=0.25)

    assert sx == 1.25
    assert sy == 1.25
    assert session["dwm_input_render_pixels"] == (1920.0, 900.0)
    assert session["dwm_input_scale_source"] == "dwm-visible-contract/css-viewport"


def test_forced_recrop_is_not_suppressed_by_cached_viewport():
    start = MAIN.index("def _schedule_dwm_geometry_sync")
    end = MAIN.index("def _hide_dwm_host", start)
    block = MAIN[start:end]
    assert "force_resize=False" in block
    assert "if force_now or viewport != self._dwm_last_chromium_viewport" in block
    assert "refresh_input_metrics=True" not in block  # caller chooses it explicitly
    assert block.index("resize_embedded_chromium(*viewport)") < block.index(
        "refresh_embedded_chromium_dwm_input_metrics"
    )


def test_maximize_forces_one_recrop_then_only_remeasures_input():
    start = MAIN.index("def _toggle_maximize")
    end = MAIN.index("def _schedule_taskbar_restore_check", start)
    block = MAIN[start:end]
    assert "force_recrop=True" in block
    assert block.count("force_recrop=True") == 1
    assert block.count("force_recrop=False") == 2

    rearm_start = MAIN.index("def _rearm_dwm_input_after_maximize")
    rearm_end = MAIN.index("def _toggle_maximize", rearm_start)
    rearm = MAIN[rearm_start:rearm_end]
    assert "request_embedded_chromium_dwm_recrop()" in rearm
    assert "force_resize=bool(force_recrop)" in rearm
    assert "refresh_input_metrics=True" in rearm
