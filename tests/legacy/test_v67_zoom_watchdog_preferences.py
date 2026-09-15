from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_version_v67():
    assert 'BROWSER_VERSION = "6.7"' in MAIN


def test_zoom_watchdog_runs_periodically_and_only_corrects_drift():
    assert "def _zoom_watchdog_tick(self):" in MAIN
    assert "_zoom_watchdog_interval_ms = 1500" in MAIN
    assert "check_embedded_chromium_zoom(wanted, target_id)" in MAIN
    assert 'status.get("ready") and not status.get("matches")' in MAIN
    assert "self._apply_chromium_zoom(target_id)" in MAIN


def test_zoom_watchdog_checks_computed_zoom_and_waits_for_loaded_document():
    assert "def check_embedded_chromium_zoom" in NET
    assert "state === 'loading'" in NET
    assert "getComputedStyle(root).zoom" in NET
    assert "computedZoom" in NET
    assert "data-tekzite-page-zoom" in NET


def test_preferences_center_on_monitor_work_area():
    assert "def _monitor_work_area_for_window" in MAIN
    assert "MonitorFromWindow" in MAIN
    assert "GetMonitorInfoW" in MAIN
    assert "rcWork" in MAIN
    assert "x = left + (work_w - dialog_width) // 2" in MAIN
    assert "y = top + (work_h - dialog_h) // 2" in MAIN


def test_preferences_height_tracks_requested_content_height():
    assert "requested_h = max(1, int(outer.winfo_reqheight()))" in MAIN
    assert "client_h = requested_h + 2" in MAIN
    assert 'win.geometry(f"{dialog_width}x{dialog_h}+{x}+{y}")' in MAIN
    assert "win.resizable(False, False)" in MAIN


def test_preferences_no_longer_has_fixed_720_height():
    prefs = MAIN.split("def show_preferences(self):", 1)[1].split("def _show_about", 1)[0]
    assert "dialog_height = 720" not in prefs
    assert 'win.geometry(f"{dialog_width}x1")' in prefs
