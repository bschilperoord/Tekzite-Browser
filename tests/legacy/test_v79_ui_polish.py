from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_version_is_79():
    assert 'BROWSER_VERSION = "7.9"' in SRC


def test_ui_palette_has_polish_tokens():
    for token in ('"chrome_hover"', '"border_soft"', '"muted_dim"'):
        assert token in SRC


def test_tabs_use_active_indicator_not_accent_box():
    block = SRC[SRC.index('def _refresh_tab_strip'):SRC.index('def _new_tab', SRC.index('def _refresh_tab_strip'))]
    assert 'height=2' in block
    assert 'self.ui["accent"] if active' in block
    assert 'highlightbackground=self.ui["border_soft"] if active' in block


def test_tabs_have_hover_and_close_hover_states():
    block = SRC[SRC.index('def _refresh_tab_strip'):SRC.index('def _new_tab', SRC.index('def _refresh_tab_strip'))]
    assert 'def set_hover' in block
    assert 'self.ui["danger"]' in block
    assert 'self.ui["chrome_hover"]' in SRC


def test_toolbar_is_more_compact():
    assert 'height=58' in SRC
    assert 'address_shell.pack(side="left", fill="x", expand=True, padx=(10, 9), pady=9)' in SRC


def test_engine_files_not_modified_for_ui_pass():
    # v7.9 is deliberately a shell-only change; engine/net remains present and
    # DWM/input APIs are still imported by main.py.
    assert (ROOT / 'engine' / 'net.py').exists()
    assert 'get_embedded_chromium_input_zoom_factor' in SRC
    assert 'dispatch_embedded_chromium_mouse' in SRC
