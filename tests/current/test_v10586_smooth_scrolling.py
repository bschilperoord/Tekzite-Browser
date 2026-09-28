from pathlib import Path

import pytest

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version_is_v10586():
    assert main.BROWSER_VERSION == "10.5.105"


def test_precision_delta_is_not_artificially_delayed():
    step, remaining = main.BrowserApp._smooth_scroll_component(8.0)
    assert step == 8.0
    assert remaining == 0.0


def test_coarse_wheel_delta_is_eased_and_conserves_distance():
    remaining = 120.0
    steps = []
    for _ in range(20):
        step, remaining = main.BrowserApp._smooth_scroll_component(remaining)
        steps.append(step)
        if not remaining:
            break
    assert len(steps) > 1
    assert steps[0] < 120.0
    assert sum(steps) == pytest.approx(120.0)


def test_smoothing_preserves_scroll_direction():
    down_step, down_remaining = main.BrowserApp._smooth_scroll_component(120.0)
    up_step, up_remaining = main.BrowserApp._smooth_scroll_component(-120.0)
    assert down_step > 0 and down_remaining > 0
    assert up_step < 0 and up_remaining < 0


def test_wheel_bridge_uses_eased_tail_on_dedicated_scroll_lane():
    block = MAIN[MAIN.index("def _flush_chromium_wheel"):MAIN.index("def _on_root_chromium_key")]
    assert "_smooth_scroll_component" in block
    assert "_chromium_smooth_scroll_interval_ms" in block
    assert "_chromium_scroll_executor.submit" in block
    assert 'purpose="scroll"' in block
    assert 'dispatch_embedded_chromium_mouse, "mouseWheel"' in block


def test_smooth_scroll_is_not_disabled_at_chromium_launch():
    assert '"--disable-smooth-scrolling"' not in MAIN
    net = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
    assert '"--disable-smooth-scrolling"' not in net


def test_linux_x11_wheel_ticks_are_routed_through_smoothing_bridge():
    assert 'self.chromium_surface.bind("<Button-4>", self._on_chromium_surface_wheel)' in MAIN
    assert 'self.chromium_surface.bind("<Button-5>", self._on_chromium_surface_wheel)' in MAIN
    wheel = MAIN[MAIN.index("def _on_chromium_surface_wheel"):MAIN.index("def _flush_chromium_wheel")]
    assert "if button == 4:" in wheel
    assert "elif button == 5:" in wheel
    assert "raw_delta = 120.0" in wheel
    assert "raw_delta = -120.0" in wheel
