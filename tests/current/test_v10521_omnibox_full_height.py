from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.33"


def test_address_text_host_is_not_squeezed_by_large_vertical_padding():
    block = MAIN[MAIN.index("self.address_text_host = tk.Frame"):MAIN.index("self.address = tk.Entry")]
    assert 'pady=self._ui_padding(1)' in block
    assert 'pady=self._ui_padding(9)' not in block


def test_preview_uses_actual_canvas_background():
    block = MAIN[MAIN.index("def _render_address_preview"):MAIN.index("def _activate_address_preview")]
    assert 'fill = str(preview.cget("bg") or self.ui["field"])' in block


def test_generic_entry_focus_animation_skips_omnibox():
    block = MAIN[MAIN.index("def _install_global_motion_bindings"):MAIN.index("def _animate_loading_icon")]
    assert 'if w is getattr(self, "address", None):' in block

