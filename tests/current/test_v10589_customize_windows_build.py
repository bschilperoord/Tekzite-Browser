from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
BUILD = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")


def test_customize_dialog_keeps_all_five_option_pages():
    for title in ("Appearance", "Toolbar", "Tabs & Layout", "Behavior", "Advanced"):
        assert f'page("{title}")' in MAIN
    assert 'len(notebook.tabs()) == 5' in MAIN
    assert 'win._tekzite_customize_ready' in MAIN


def test_customize_pages_are_scrollable_for_windows_dpi_scaling():
    assert 'customize_page_canvases = {}' in MAIN
    assert 'canvas = tk.Canvas(' in MAIN
    assert 'ttk.Scrollbar(' in MAIN
    assert 'canvas.configure(yscrollcommand=scrollbar.set)' in MAIN
    assert 'canvas.yview_moveto(0.0)' in MAIN


def test_customize_font_enumeration_cannot_abort_dialog_construction():
    marker = 'families = sorted(set(str(x) for x in tkfont.families(self.root)), key=str.casefold)'
    assert marker in MAIN
    before = MAIN[max(0, MAIN.index(marker) - 80):MAIN.index(marker)]
    assert 'try:' in before
    assert 'families = []' in MAIN[MAIN.index(marker):MAIN.index(marker) + 520]


def test_windows_onefile_explicitly_bundles_customize_tk_modules():
    for module in (
        '"tkinter.ttk"',
        '"tkinter.font"',
        '"tkinter.colorchooser"',
        '"tkinter.filedialog"',
        '"tkinter.messagebox"',
        '"tkinter.simpledialog"',
    ):
        assert module in BUILD


def test_customize_header_uses_valid_tk_widget_padding():
    # Frame padx/pady options accept one Tk distance, unlike pack() which may
    # accept a two-value external padding tuple.  A tuple here aborts dialog
    # construction with: TclError: bad screen distance "4 10".
    assert 'tk.Frame(win, bg=self.ui["bg"], padx=18, pady=(4, 10))' not in MAIN
    assert 'tk.Frame(win, bg=self.ui["bg"], padx=18, pady=4)' in MAIN
