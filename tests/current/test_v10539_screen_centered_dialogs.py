from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_is_v10539():
    assert 'BROWSER_VERSION = "10.5.73"' in MAIN


def test_shared_dialog_factory_centers_before_open_animation():
    start = MAIN.index("    def _new_animated_toplevel(")
    end = MAIN.index("    def _animate_toplevel_in(", start)
    block = MAIN[start:end]
    assert "self._center_dialog_on_screen(w)" in block
    assert block.index("self._center_dialog_on_screen(w)") < block.index("self._animate_toplevel_in(w")


def test_settings_uses_same_screen_center_geometry_helper():
    start = MAIN.index("        def fit_and_center_preferences():")
    end = MAIN.index("        win.after_idle(fit_and_center_preferences)", start)
    block = MAIN[start:end]
    assert "self._screen_center_geometry(win, dialog_w, dialog_h, 16)" in block
    assert "root_x + root_w // 2" not in block


def test_center_helper_uses_tk_screen_coordinates():
    start = MAIN.index("    def _screen_center_geometry(")
    end = MAIN.index("    def _bind_frameless_dialog_drag(", start)
    block = MAIN[start:end]
    assert "winfo_screenwidth" in block
    assert "winfo_screenheight" in block
    assert "(screen_w - width) // 2" in block
    assert "(screen_h - height) // 2" in block
