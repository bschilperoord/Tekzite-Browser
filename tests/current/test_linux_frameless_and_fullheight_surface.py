from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_linux_root_uses_tekzite_frameless_shell():
    assert 'self.root.overrideredirect(True)' in MAIN
    assert 'self.root.overrideredirect(os.name == "nt")' not in MAIN


def test_window_controls_are_repacked_on_linux_too():
    start = MAIN.index("def _repack_browser_chrome")
    end = MAIN.index("\n    def ", start + 10)
    block = MAIN[start:end]
    assert 'if self._custom("show_window_controls", True):' in block
    assert 'show_window_controls", True) and os.name == "nt"' not in block


def test_linux_minimize_temporarily_returns_window_to_wm():
    start = MAIN.index("def _minimize_window")
    end = MAIN.index("\n    def ", start + 10)
    block = MAIN[start:end]
    assert 'if os.name != "nt":' in block
    assert 'self.root.overrideredirect(False)' in block
    assert 'self._schedule_taskbar_restore_check(120)' in block


def test_software_viewport_self_heals_missed_configure_gap():
    start = MAIN.index("def _current_chromium_software_viewport")
    end = MAIN.index("\n    def ", start + 10)
    block = MAIN[start:end]
    assert "actual = (w, h)" in block
    assert "self._chromium_pending_viewport_size = actual" in block
    assert "self._commit_chromium_software_viewport" in block


def test_root_configure_reconciles_software_canvas_height():
    start = MAIN.index("def _on_root_configure_native_overlay")
    end = MAIN.index("\n    def ", start + 10)
    block = MAIN[start:end]
    assert "if self._chromium_software_mode:" in block
    assert "self.chromium_surface.winfo_height()" in block
    assert "self._chromium_pending_viewport_size = candidate" in block
