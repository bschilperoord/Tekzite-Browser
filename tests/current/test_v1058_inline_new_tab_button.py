from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.80"


def test_new_tab_button_belongs_to_tab_items_row():
    block = MAIN[MAIN.index("# ── Browser tab strip"):MAIN.index("# ── Tekzite browser chrome")]
    assert 'self.new_tab_button = _RoundedChromeButton(' in block
    assert 'self.tab_items, "+", self._new_tab' in block
    assert 'self.tab_bar, text="+"' not in block


def test_refresh_preserves_inline_button_and_places_it_after_tabs():
    block = MAIN[MAIN.index("def _place_new_tab_button_inline"):MAIN.index("def _decode_favicon_photo")]
    assert 'siblings = [child for child in items.winfo_children() if child is not button]' in block
    assert 'opts["after"] = siblings[-1]' in block
    assert 'opts["before"] = siblings[0]' in block
    assert 'if child is not getattr(self, "new_tab_button", None):' in block
    assert 'self._place_new_tab_button_inline()' in block


def test_tab_items_still_expand_to_fill_unused_strip_space():
    assert 'self.tab_items.pack(side="left", fill="both", expand=True' in MAIN

