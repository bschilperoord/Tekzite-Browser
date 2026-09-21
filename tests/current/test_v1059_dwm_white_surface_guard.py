from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_dwm_host_is_layered_and_alpha_driven():
    block = MAIN[MAIN.index("def _ensure_dwm_host"):MAIN.index("def _sync_dwm_host_geometry")]
    assert "WS_EX_LAYERED" in block
    assert "WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED" in block

    sync = MAIN[MAIN.index("def _sync_dwm_host_geometry"):MAIN.index("def _cancel_dwm_host_reveal")]
    assert "SetLayeredWindowAttributes" in sync
    assert "target_alpha = 0 if transparent else 255" in sync


def test_initial_dwm_reveal_starts_transparent_then_turns_opaque():
    block = MAIN[MAIN.index("def _show_embedded_host"):MAIN.index("def _arm_dwm_input_surface")]
    assert "self._dwm_reveal_pending = True" in block
    assert "self._sync_dwm_host_geometry(show=True, transparent=True)" in block
    assert "self._schedule_dwm_host_reveal(delay=45)" in block
    assert "self.root.after(140, self._reveal_dwm_host)" in block


def test_geometry_sync_preserves_transparent_reveal_guard():
    block = MAIN[MAIN.index("def _schedule_dwm_geometry_sync"):MAIN.index("def _hide_dwm_host")]
    assert "transparent=bool(self._dwm_reveal_pending)" in block

