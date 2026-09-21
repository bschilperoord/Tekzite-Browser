from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.32"


def test_about_is_dedicated_toplevel_not_generic_message():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(self)")]
    assert "self._new_animated_toplevel" in block
    assert "self._show_message" not in block
    assert 'win.title("About Tekzite")' in block


def test_about_is_brought_above_dwm_and_reused():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(self)")]
    assert 'getattr(self, "_about_window", None)' in block
    assert 'self._raise_toplevel_above_dwm(existing' in block
    assert 'self._raise_toplevel_above_dwm(win' in block
    assert 'self._about_window = win' in block


def test_about_actions_are_wired():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(self)")]
    assert 'text="Copy info"' in block
    assert 'command=self._check_for_updates' in block
    assert 'text="Close"' in block
    assert 'win.bind("<Escape>"' in block
