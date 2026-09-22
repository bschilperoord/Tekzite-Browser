from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FEATURES = (ROOT / 'browser_features.py').read_text(encoding='utf-8')


def test_release_version():
    assert main.BROWSER_VERSION == '10.5.54'


def test_app_owned_toplevels_use_shared_motion_factory():
    browser_block = MAIN[MAIN.index('class BrowserApp('):]
    # The only raw Toplevel in BrowserApp should be inside the shared factory.
    assert browser_block.count('tk.Toplevel(') == 1
    assert 'win = tk.Toplevel(parent or self.root)' in browser_block
    assert 'tk.Toplevel(' not in FEATURES
    assert FEATURES.count('self._new_animated_toplevel(self.root)') >= 6


def test_motion_factory_wraps_open_and_close_paths():
    block = MAIN[MAIN.index('def _new_animated_toplevel'):MAIN.index('def _animate_toplevel_in')]
    assert 'original_destroy = win.destroy' in block
    assert 'win.destroy = animated_destroy' in block
    assert 'win.after(1' in block
    assert '_animate_toplevel_out' in block


def test_dialogs_are_tekzite_owned_and_animated():
    assert 'messagebox.show' not in MAIN
    assert 'messagebox.askyesno' not in MAIN
    assert 'simpledialog.askstring' not in MAIN
    assert 'messagebox.show' not in FEATURES
    assert 'messagebox.askyesno' not in FEATURES
    assert 'simpledialog.askstring' not in FEATURES
    for name in ('_show_message', '_ask_yes_no', '_ask_string_animated'):
        assert f'def {name}' in MAIN
        block = MAIN[MAIN.index(f'def {name}'):]
        assert '_new_animated_toplevel' in block[:4000]


def test_main_shell_and_customize_pages_are_animated():
    assert 'self.root.after_idle(self._animate_main_window_in)' in MAIN
    assert '<<NotebookTabChanged>>' in MAIN
    assert 'self._animate_notebook_page(notebook)' in MAIN


def test_standard_controls_share_motion_bindings():
    block = MAIN[MAIN.index('def _install_global_motion_bindings'):MAIN.index('def _animate_loading_icon')]
    assert 'bind_class("Button", "<Enter>"' in block
    assert 'bind_class("Button", "<ButtonPress-1>"' in block
    assert 'bind_class("Entry", "<FocusIn>"' in block
    assert '_animate_widget_color' in block

