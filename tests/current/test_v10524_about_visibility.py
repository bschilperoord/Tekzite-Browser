from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_animated_toplevel_does_not_start_from_idle_layout_pass():
    block = MAIN[MAIN.index("def _new_animated_toplevel"):MAIN.index("def _animate_toplevel_in")]
    assert "win.after(1" in block
    assert "win.after_idle" not in block


def test_about_is_built_hidden_then_raised_after_geometry():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(self)")]
    assert "win.withdraw()" in block
    assert "win.geometry" in block
    assert block.index("win.geometry") < block.index("self._raise_toplevel_above_dwm(win")


def test_about_uses_native_z_order_over_dwm():
    block = MAIN[MAIN.index("def _raise_toplevel_above_dwm"):MAIN.index("def _show_about")]
    assert "HWND_TOPMOST = -1" in block
    assert "HWND_NOTOPMOST = -2" in block
    assert "SetWindowPos" in block
    assert "GetAncestor" in block


def test_existing_about_is_raised_not_duplicated():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(self)")]
    assert 'getattr(self, "_about_window", None)' in block
    assert "self._raise_toplevel_above_dwm(existing" in block

