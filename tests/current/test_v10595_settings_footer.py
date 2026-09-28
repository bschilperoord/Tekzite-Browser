from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_settings_footer_is_reserved_before_scroll_body():
    block = MAIN[MAIN.index("def show_preferences(self):"):MAIN.index("def _raise_toplevel_above_dwm")]
    buttons = block.index('buttons.pack(side="bottom", fill="x"')
    scroll = block.index('scroll_host.pack(side="top", fill="both", expand=True)')
    assert buttons < scroll


def test_settings_save_button_is_visible_and_explicit():
    block = MAIN[MAIN.index("def show_preferences(self):"):MAIN.index("def _raise_toplevel_above_dwm")]
    assert 'text="Save settings"' in block
    assert 'command=save_and_close' in block
    assert 'text="Cancel"' in block
    assert 'buttons = tk.Frame(' in block
