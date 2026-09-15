from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")

def test_startup_prefocuses_page_editable_before_reveal():
    assert 'def _focus_embedded_chromium_startup_input' in NET
    open_block = NET[NET.index('def open_embedded_chromium'):NET.index('def record_embedded_native_recovery')]
    assert '_focus_embedded_chromium_startup_input' in open_block
    assert 'if first_native_bootstrap:' in open_block

def test_dwm_keyboard_lane_arms_before_show():
    block = MAIN[MAIN.index('self._dwm_surface_ready = True'):MAIN.index('def _arm_dwm_input_surface')]
    assert block.index('self._arm_dwm_input_surface()') < block.index('self._sync_dwm_host_geometry(show=True')
