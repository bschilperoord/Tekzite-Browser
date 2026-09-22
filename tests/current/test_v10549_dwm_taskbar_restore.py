from pathlib import Path

import main

ROOT = Path(main.__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.54"


def test_minimize_suspends_dwm_destination_before_iconifying_root():
    start = MAIN.index("    def _minimize_window(self):")
    end = MAIN.index("    def _restore_frameless_after_minimize(self):", start)
    block = MAIN[start:end]
    assert "self._suspend_dwm_host_for_minimize()" in block
    assert block.index("self._suspend_dwm_host_for_minimize()") < block.index("self.root.iconify()")


def test_dwm_sync_cannot_remap_popup_while_root_is_iconic():
    start = MAIN.index("    def _sync_dwm_host_geometry(")
    end = MAIN.index("    def _cancel_dwm_host_reveal(", start)
    block = MAIN[start:end]
    assert 'root_iconic = str(self.root.state()) == "iconic"' in block
    assert "not self._dwm_host_suspended_for_minimize" in block
    assert "and not root_iconic" in block


def test_dwm_host_style_remains_nonactivating_tool_window():
    start = MAIN.index("    def _repair_dwm_host_owner_and_style(")
    end = MAIN.index("    def _destroy_dwm_host_for_taskbar(", start)
    block = MAIN[start:end]
    assert "GWLP_HWNDPARENT = -8" in block
    assert "WS_EX_TOOLWINDOW" in block
    assert "WS_EX_NOACTIVATE" in block
    assert "~WS_EX_APPWINDOW" in block
    assert "SetWindowLongPtrW" in block


def test_map_event_starts_suspended_dwm_restore():
    start = MAIN.index("    def _on_window_map(")
    end = MAIN.index("    def normalize_url(", start)
    block = MAIN[start:end]
    assert "self._dwm_host_suspended_for_minimize" in block
    assert "self._restore_dwm_host_after_taskbar" in block
