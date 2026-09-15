from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_version_v610():
    assert 'BROWSER_VERSION = "6.1"' in MAIN


def test_dwm_starts_hidden_until_surface_ready():
    assert 'self._dwm_surface_ready = False' in MAIN
    assert 'should_show = bool(show and self._dwm_surface_ready)' in MAIN
    show_block = MAIN[MAIN.index('    def _show_embedded_host'):MAIN.index('    def _on_edge_host_configure')]
    assert 'self._dwm_surface_ready = False' in show_block
    assert 'self._dwm_surface_ready = True' in show_block
    assert show_block.index('self._dwm_surface_ready = True') > show_block.index('resize_embedded_chromium(host_w, host_h)')


def test_dwm_geometry_is_coalesced():
    assert 'def _schedule_dwm_geometry_sync(self, resize=False, delay=16):' in MAIN
    assert 'self._dwm_geometry_after_id' in MAIN
    assert 'self.root.after(max(1, int(delay)), _flush)' in MAIN


def test_window_move_does_not_resize_chromium():
    block = MAIN[MAIN.index('    def _on_root_configure_native_overlay'):MAIN.index('    def _probe_visible_embedded_surface')]
    assert 'self._schedule_dwm_geometry_sync(resize=False, delay=16)' in block
    dwm_branch = block.split('if self._chromium_dwm_mode:', 1)[1].split('return', 1)[0]
    assert 'resize_embedded_chromium' not in dwm_branch


def test_dwm_resize_only_when_viewport_changes():
    block = MAIN[MAIN.index('    def _schedule_dwm_geometry_sync'):MAIN.index('    def _hide_dwm_host')]
    assert 'viewport != self._dwm_last_chromium_viewport' in block
    assert 'resize_embedded_chromium(w, h)' in block


def test_dwm_move_preserves_z_order():
    block = MAIN[MAIN.index('    def _sync_dwm_host_geometry'):MAIN.index('    def _schedule_dwm_geometry_sync')]
    assert 'SWP_NOZORDER = 0x0004' in block
    assert 'SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOZORDER' in block
    assert 'HWND_TOP' not in block
