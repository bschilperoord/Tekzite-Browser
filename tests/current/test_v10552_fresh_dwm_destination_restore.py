from pathlib import Path

import main

ROOT = Path(main.__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_is_v10552():
    assert main.BROWSER_VERSION == "10.5.54"


def test_minimize_destroys_transient_dwm_destination():
    start = MAIN.index("    def _suspend_dwm_host_for_minimize(")
    end = MAIN.index("    def _restore_dwm_host_after_taskbar(", start)
    block = MAIN[start:end]
    assert "self._destroy_dwm_host_for_taskbar()" in block


def test_destroy_resets_all_host_identity_state():
    start = MAIN.index("    def _destroy_dwm_host_for_taskbar(")
    end = MAIN.index("    def _suspend_dwm_host_for_minimize(", start)
    block = MAIN[start:end]
    assert "DestroyWindow" in block
    assert "self._dwm_host = None" in block
    assert "self._dwm_host_owner_hwnd = None" in block
    assert "self._dwm_host_rect = None" in block
    assert "self._dwm_host_wndproc = None" in block


def test_restore_creates_new_host_and_reattaches_engine_before_reveal():
    start = MAIN.index("    def _recover_dwm_host_after_taskbar(")
    end = MAIN.index("    def _sync_dwm_host_geometry(", start)
    block = MAIN[start:end]
    assert "host = int(self._ensure_dwm_host())" in block
    assert "attach_embedded_chromium(host, w, h)" in block
    assert "self._dwm_surface_ready = True" in block
    assert "self._sync_dwm_host_geometry(show=True, transparent=True)" in block
    assert block.index("host = int(self._ensure_dwm_host())") < block.index("attach_embedded_chromium(host, w, h)")
    assert block.index("attach_embedded_chromium(host, w, h)") < block.index("self._dwm_surface_ready = True")
    assert block.index("self._dwm_surface_ready = True") < block.index("self._sync_dwm_host_geometry(show=True, transparent=True)")


def test_failed_restore_discards_failed_destination_before_retry():
    start = MAIN.index("    def _recover_dwm_host_after_taskbar(")
    end = MAIN.index("    def _sync_dwm_host_geometry(", start)
    block = MAIN[start:end]
    assert "self._destroy_dwm_host_for_taskbar()" in block
    assert "int(attempt) < 4" in block
