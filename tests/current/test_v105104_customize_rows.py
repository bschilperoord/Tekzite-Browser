import inspect

import main


CUSTOMIZE_SOURCE = inspect.getsource(main.BrowserApp._show_customize_browser)


def test_customize_explanatory_text_is_inline_not_stacked_under_labels():
    assert "visible_header = tk.Frame" in CUSTOMIZE_SOURCE
    assert 'label(visible_header, "Ctrl+L reveals a hidden address bar.", muted=True).pack(side="right")' in CUSTOMIZE_SOURCE
    assert "homepage_row = tk.Frame" in CUSTOMIZE_SOURCE
    assert "search_template_row = tk.Frame" in CUSTOMIZE_SOURCE
    assert '"Use {query} • local SearXNG supported"' in CUSTOMIZE_SOURCE
    assert "recovery_row = tk.Frame" in CUSTOMIZE_SOURCE


def test_customize_old_stacked_helper_copy_is_gone():
    assert "Tip: hiding the address bar is safe." not in CUSTOMIZE_SOURCE
    assert "Choose a provider above, or use Custom with {query}." not in CUSTOMIZE_SOURCE
    assert 'label(advanced_page, "Ctrl+Shift+Alt+R resets the interface only."' not in CUSTOMIZE_SOURCE


def test_customize_pages_use_tighter_padding():
    assert 'header = tk.Frame(win, bg=self.ui["bg"], padx=14, pady=3)' in CUSTOMIZE_SOURCE
    assert 'notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))' in CUSTOMIZE_SOURCE
    assert 'frame = tk.Frame(canvas, bg=self.ui["bg"], padx=14, pady=10)' in CUSTOMIZE_SOURCE
