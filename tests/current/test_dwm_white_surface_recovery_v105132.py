"""Cold-start white DWM surface regression tests (no real Windows GUI needed)."""

from concurrent.futures import Future
from pathlib import Path

from PIL import Image, ImageDraw

import main

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine/net.py").read_text(encoding="utf-8")


def _white_compositor_screenshot():
    # A white page with a dark top strip has a high whole-frame RGB span.
    # v10.5.132 incorrectly classified such a DWM surface as healthy.
    img = Image.new("RGB", (1000, 700), (241, 241, 241))
    painter = ImageDraw.Draw(img)
    painter.rectangle((0, 0, 999, 65), fill=(12, 22, 32))
    painter.rectangle((0, 678, 999, 699), fill=(31, 31, 44))
    return img


def test_white_center_with_contrasting_edges_is_detected():
    health = main._dwm_visible_surface_health(_white_compositor_screenshot())
    assert health["span"] >= 200
    assert health["dominant"] < .975
    assert health["center_pale_ratio"] > .94
    assert health["blank"] is True
    assert health["reason"] == "white-center"


def test_painted_content_not_mistaken_for_white_host():
    image = _white_compositor_screenshot()
    painter = ImageDraw.Draw(image)
    for y in range(140, 580, 28):
        painter.rectangle((180, y, 780, y + 12), fill=(34, 55, 88))
    result = main._dwm_visible_surface_health(image)
    assert result["blank"] is False
    assert result["reason"] == "content"


def test_valid_dark_website_does_not_trigger_white_screen():
    image = Image.new("RGB", (1000, 700), (13, 19, 27))
    painter = ImageDraw.Draw(image)
    for x in range(100, 900, 60):
        painter.rectangle((x, 110, x + 18, 590), fill=(48, 96, 123))
    assert main._dwm_visible_surface_health(image)["blank"] is False


def test_dwm_visible_probe_attempts_repair_then_uses_software(monkeypatch):
    class Root:
        def __init__(self):
            self.queue = []

        def after(self, milliseconds, callback, *args):
            self.queue.append((milliseconds, callback, args))
            return len(self.queue)

        def state(self):
            return "normal"

        def winfo_viewable(self):
            return True

        def update_idletasks(self):
            pass

    class Edge:
        def winfo_rootx(self):
            return 30

        def winfo_rooty(self):
            return 180

        def winfo_width(self):
            return 1000

        def winfo_height(self):
            return 700

    class Status:
        def set(self, text):
            self.value = text

    tab = {"chromium_target_id": "first-page", "loading": False}
    app = object.__new__(main.BrowserApp)
    app._navigation_generation = 1
    app._window_drag_active = False
    app._embedded_mode = True
    app._chromium_software_mode = False
    app.root = Root()
    app.edge_host = Edge()
    app.status_var = Status()
    app._active_tab = lambda: tab
    repairs = []
    fallbacks = []
    recorded = []

    def repair(generation, target_id, viewport, attempt):
        repairs.append((generation, target_id, viewport, attempt))
        tab["native_surface_repair_attempted"] = True
        tab["native_surface_blank_confirmations"] = 0
        return True

    app._repair_stalled_dwm_once = repair
    app._show_chromium_software_surface = lambda target: fallbacks.append(target)
    monkeypatch.setattr(main.ImageGrab, "grab", lambda **kwargs: _white_compositor_screenshot())
    monkeypatch.setattr(main, "record_embedded_surface_probe", lambda *a, **kw: recorded.append((a, kw)))
    monkeypatch.setattr(main, "record_embedded_native_recovery", lambda *a, **kw: True)

    app._probe_visible_embedded_surface(1, "first-page", True, 1)
    assert not repairs and not fallbacks
    _ms, cb, args = app.root.queue.pop(0)
    cb(*args)
    assert len(repairs) == 1 and not fallbacks

    app._probe_visible_embedded_surface(1, "first-page", True, 3)
    assert not fallbacks
    _ms, cb, args = app.root.queue.pop(0)
    cb(*args)
    assert fallbacks == ["first-page"]
    assert tab["presentation"] == "software"
    assert tab["software_fallback_reason"] == "visible-surface"
    assert tab["native_recovery_viewport"] == (1000, 700)
    assert recorded[-1][0][4] is True
    assert recorded[-1][1]["details"]["reason"] == "white-center"


def test_cold_dwm_repair_is_one_shot_and_async(monkeypatch):
    class Executor:
        def submit(self, fn):
            result = Future()
            result.set_result(fn())
            return result

    class Root:
        def __init__(self):
            self.queue = []

        def after(self, delay, fn, *args):
            self.queue.append((delay, fn, args))

    class Status:
        def set(self, text):
            self.value = text

    tab = {"chromium_target_id": "a"}
    app = object.__new__(main.BrowserApp)
    app._navigation_generation = 42
    app.root = Root()
    app.status_var = Status()
    app._executor = Executor()
    app._active_tab = lambda: tab
    calls = []
    monkeypatch.setattr(main, "request_embedded_chromium_dwm_reregister", lambda: calls.append("reregister") or True)
    monkeypatch.setattr(main, "resize_embedded_chromium", lambda w, h: calls.append((w, h)) or True)
    assert app._repair_stalled_dwm_once(42, "a", (1440, 677), 2) is True
    assert app._repair_stalled_dwm_once(42, "a", (1440, 677), 2) is False
    assert calls == ["reregister", (1440, 677)]
    _, callback, args = app.root.queue.pop(0)
    callback(*args)
    assert tab["native_surface_repair_succeeded"] is True
    assert tab["native_surface_repair_pending"] is False
    assert app.root.queue[0][0] == 650
    assert app.root.queue[0][2] == (42, "a", True, 3)


def test_generation_or_target_switch_cannot_repair_stale_tab():
    app = object.__new__(main.BrowserApp)
    app._navigation_generation = 2
    app._active_tab = lambda: {"chromium_target_id": "new"}
    assert app._repair_stalled_dwm_once(1, "old", (1000, 600), 2) is False


def test_debug_report_includes_screen_health_details():
    assert "visible_surface_probe_details" in NET
    assert "details=None" in NET
    assert "request_embedded_chromium_dwm_reregister()" in SOURCE
    assert "self._show_chromium_software_surface(target_id)" in SOURCE
