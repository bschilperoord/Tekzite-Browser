from pathlib import Path

import main
from engine import net

ROOT = Path(main.__file__).resolve().parent
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = Path(net.__file__).read_text(encoding="utf-8")


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.80"


def test_raw_dwm_destination_has_no_visible_debug_caption():
    start = MAIN.index("    def _ensure_dwm_host(")
    end = MAIN.index("    def _repair_dwm_host_owner_and_style(", start)
    block = MAIN[start:end]
    assert '"STATIC", "", WS_POPUP' in block
    assert '"STATIC", "Tekzite DWM Surface", WS_POPUP' not in block


def test_restore_stays_suspended_until_fresh_destination_recovery():
    start = MAIN.index("    def _restore_dwm_host_after_taskbar(")
    end = MAIN.index("    def _recover_dwm_host_after_taskbar(", start)
    block = MAIN[start:end]
    assert "self._dwm_host_suspended_for_minimize = True" in block
    assert "self.root.after(" in block
    assert "self._recover_dwm_host_after_taskbar" in block


def test_recovery_reregisters_before_mapping_destination():
    start = MAIN.index("    def _recover_dwm_host_after_taskbar(")
    end = MAIN.index("    def _sync_dwm_host_geometry(", start)
    block = MAIN[start:end]
    assert "request_embedded_chromium_dwm_reregister()" in block
    assert "attach_embedded_chromium(host, w, h)" in block
    assert "self._sync_dwm_host_geometry(show=True, transparent=True)" in block
    assert block.index("attach_embedded_chromium(host, w, h)") < block.index("self._sync_dwm_host_geometry(show=True, transparent=True)")


def test_engine_cold_reregister_unhooks_old_thumbnail_and_flushes():
    start = NET.index("def request_embedded_chromium_dwm_reregister(")
    assert '_EDGE_SESSION["dwm_force_reregister"] = True' in NET[start:start+900]
    overlay = NET[NET.index("def _position_native_chromium_overlay("):NET.index("def _wait_for_live_embed_owner(")]
    assert 'force_reregister = bool(session.pop("dwm_force_reregister", False))' in overlay
    assert "and not force_reregister" in overlay
    assert "if force_reregister or not old_thumb" in overlay
    assert "dwm_restore_reregister_count" in overlay
