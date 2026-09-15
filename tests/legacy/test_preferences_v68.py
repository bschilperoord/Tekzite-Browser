from pathlib import Path
MAIN=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')

def test_version():
    assert 'BROWSER_VERSION = "6.8"' in MAIN

def test_preferences_is_built_hidden_not_one_pixel():
    assert 'win.withdraw()' in MAIN
    assert 'win.geometry(f"{dialog_width}x1")' not in MAIN

def test_preferences_measures_content_before_showing():
    assert 'outer.winfo_reqheight()' in MAIN
    assert 'outer.winfo_reqwidth()' in MAIN
    assert 'win.update_idletasks()' in MAIN

def test_preferences_has_safe_monitor_fallback():
    assert 'self._monitor_work_area_for_window(self.root)' in MAIN
    assert 'win.winfo_screenwidth()' in MAIN
    assert 'win.winfo_screenheight()' in MAIN

def test_preferences_is_explicitly_shown_and_focused():
    assert 'win.deiconify()' in MAIN
    assert 'win.lift()' in MAIN
    assert 'win.grab_set()' in MAIN
    assert 'win.focus_force()' in MAIN
