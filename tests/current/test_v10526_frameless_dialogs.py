from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.38"


def test_all_animated_toplevels_hide_native_title_bar():
    block = MAIN[MAIN.index("def _new_animated_toplevel"):MAIN.index("def _animate_toplevel_in")]
    assert "win = tk.Toplevel(parent or self.root)" in block
    assert "win.overrideredirect(True)" in block


def test_shared_dialog_header_has_close_button_and_drag_handles():
    block = MAIN[MAIN.index("def _apply_about_style_to_dialog"):MAIN.index("def _new_animated_toplevel")]
    assert 'text="×", command=win.destroy' in block
    assert "self._bind_frameless_dialog_drag(" in block
    assert "title_label" in block
    assert "version_label" in block


def test_frameless_drag_moves_window_from_header():
    block = MAIN[MAIN.index("def _bind_frameless_dialog_drag"):MAIN.index("def _apply_about_style_to_dialog")]
    assert 'widget.bind("<ButtonPress-1>", start_drag' in block
    assert 'widget.bind("<B1-Motion>", move_drag' in block
    assert 'win.geometry(f"+{x}+{y}")' in block


def test_about_uses_same_frameless_header_controls():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(")]
    assert 'text="×", command=win.destroy' in block
    assert "self._bind_frameless_dialog_drag(" in block

