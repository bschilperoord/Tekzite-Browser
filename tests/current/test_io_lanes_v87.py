from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_version_87():
    assert 'BROWSER_VERSION = "10.5.32"' in MAIN


def test_latency_sensitive_io_channels_are_warmed():
    assert 'def warm_embedded_chromium_io_channels' in NET
    assert '("input", "scroll", "hover")' in NET
    assert 'purposes=("input",)' in NET
    assert '("scroll", "hover")' in MAIN


def test_hover_has_its_own_cdp_channel_not_just_worker():
    cursor = NET[NET.index('def get_embedded_chromium_cursor'):NET.index('def get_embedded_chromium_context')]
    assert 'purpose="cursor"' in cursor
    motion = MAIN[MAIN.index('def _flush_chromium_surface_motion'):MAIN.index('def _tk_cursor_for_css')]
    assert 'purpose="hover"' in motion


def test_scroll_isolated_and_coalesced():
    assert 'thread_name_prefix="tekzite-cdp-scroll"' in MAIN
    wheel = MAIN[MAIN.index('def _on_chromium_surface_wheel'):MAIN.index('def _on_root_chromium_key')]
    assert '_chromium_pending_wheel' in wheel
    assert '_chromium_scroll_executor.submit' in wheel
    assert 'purpose="scroll"' in wheel
    assert '_submit_chromium_input' not in wheel
