from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_version_v620():
    assert 'BROWSER_VERSION = "6.2"' in MAIN


def test_preserves_previous_chrome_height():
    assert 'previous_chrome_h = max(0, int(session.get("dwm_custom_chrome_height") or 0))' in NET
    assert 'session["dwm_chrome_height_locked"] = previous_chrome_h' in NET


def test_no_bare_viewport_first_pass():
    assert 'int(height) + int(previous_chrome_h) + nonclient_h' in NET
    assert 'collapse to the bare viewport first' in NET


def test_changed_crop_requires_stability():
    assert 'if count >= 3:' in NET
    assert 'session["dwm_chrome_pending_count"]' in NET
    assert 'three consecutive times' in NET


def test_stable_source_resize_is_skipped():
    assert 'session["dwm_source_resize_skipped_stable"] = not resize_needed' in NET
    assert 'if resize_needed:' in NET


def test_v61_drag_coalescing_retained():
    assert 'def _schedule_dwm_geometry_sync(self, resize=False, delay=16):' in MAIN
    assert 'viewport != self._dwm_last_chromium_viewport' in MAIN
