from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.54"


def test_all_animated_toplevels_are_branded_by_default():
    signature = MAIN[MAIN.index("def _new_animated_toplevel"):MAIN.index("def _animate_toplevel_in")]
    assert "branded=True" in signature
    assert "self._apply_about_style_to_dialog(w)" in signature


def test_shared_dialog_shell_matches_about_visual_language():
    block = MAIN[MAIN.index("def _apply_about_style_to_dialog"):MAIN.index("def _new_animated_toplevel")]
    assert 'logo.create_text(23, 23, text="T"' in block
    assert 'Tekzite Browser  •  v{BROWSER_VERSION}' in block
    assert 'self.ui["border_soft"]' in block
    assert '_raise_toplevel_above_dwm' in block


def test_about_keeps_its_custom_full_size_header_without_duplicate_branding():
    block = MAIN[MAIN.index("def _show_about"):MAIN.index("def navigate(")]
    assert 'branded=False' in block
    assert 'text="Tekzite Browser"' in block


def test_feature_windows_use_same_shared_toplevel_and_roomy_buttons():
    assert "win = self._new_animated_toplevel(self.root)" in FEATURES
    button = FEATURES[FEATURES.index("def _feature_button"):FEATURES.index("def _format_storage_bytes")]
    assert "padx=14, pady=7" in button
    assert "activebackground=self.ui['chrome_hover']" in button


def test_shared_header_preserves_existing_dialog_body_height():
    block = MAIN[MAIN.index("def _apply_about_style_to_dialog"):MAIN.index("def _new_animated_toplevel")]
    assert "header_h = max(1, int(shell.winfo_reqheight()))" in block
    assert "current_h + header_h" in block
    assert "target_h > current_h" in block

