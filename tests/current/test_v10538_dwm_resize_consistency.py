from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.47"


def test_dwm_resize_uses_committed_destination_size():
    block = MAIN[MAIN.index("def _schedule_dwm_geometry_sync"):MAIN.index("def _hide_dwm_host")]
    assert "host_size = self._sync_dwm_host_geometry" in block
    assert "w, h = map(int, host_size)" in block
    assert "resize_embedded_chromium(*viewport)" in block
    assert "viewport != self._dwm_last_chromium_viewport" in block


def test_root_configure_reconciles_dwm_size_not_only_position():
    block = MAIN[MAIN.index("def _on_root_configure_native_overlay"):MAIN.index("def _probe_visible_embedded_surface")]
    assert "size_changed = root_size != self._dwm_last_root_configure_size" in block
    assert "self._schedule_dwm_geometry_sync(resize=True, delay=8)" in block
    assert "self._schedule_dwm_geometry_sync(resize=False, delay=8)" in block


def test_maximize_and_restore_force_final_dwm_resize_pass():
    block = MAIN[MAIN.index("def _toggle_maximize"):MAIN.index("def _minimize_window")]
    assert "self._schedule_dwm_geometry_sync(resize=True, delay=1)" in block
    assert "self.root.after(70" in block
