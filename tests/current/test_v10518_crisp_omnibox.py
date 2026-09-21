from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.42"


def test_address_keeps_real_entry_and_adds_grayscale_preview():
    block = MAIN[MAIN.index("self.url_var = tk.StringVar"):MAIN.index("self.downloads_button =") ]
    assert "self.address = tk.Entry(" in block
    assert "self.address_preview = tk.Canvas(" in block
    assert 'self.url_var.trace_add("write"' in block


def test_preview_uses_pillow_grayscale_antialias_path():
    block = MAIN[MAIN.index("def _address_preview_font"):MAIN.index("def _rounded_canvas_rect")]
    assert "ImageFont.truetype" in block
    assert "ImageDraw.Draw" in block
    assert "ImageTk.PhotoImage" in block
    assert "draw.text(" in block


def test_preview_click_restores_entry_and_caret():
    block = MAIN[MAIN.index("def _activate_address_preview"):MAIN.index("def _show_address_preview_context_menu")]
    assert "self.address.focus_set()" in block
    assert "self.address.icursor" in block

