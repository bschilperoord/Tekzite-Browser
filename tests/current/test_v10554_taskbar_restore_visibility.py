from pathlib import Path

import main


def test_release_version_is_10554():
    assert main.BROWSER_VERSION == "10.5.73"


def _block(name, next_name):
    src = Path(main.__file__).read_text(encoding="utf-8")
    start = src.index(f"    def {name}(")
    end = src.index(f"    def {next_name}(", start)
    return src[start:end]


def test_withdrawn_root_is_not_treated_as_successful_restore():
    block = _block("_restore_frameless_after_minimize", "_toggle_fullscreen")
    assert 'state == "withdrawn"' in block
    assert "self.root.deiconify()" in block
    assert "self._schedule_taskbar_restore_check(70)" in block


def test_transient_restore_exception_retries_instead_of_abandoning_window():
    block = _block("_restore_frameless_after_minimize", "_toggle_fullscreen")
    assert "self._schedule_taskbar_restore_check(100)" in block


def test_restore_watchdog_requires_mapped_nonwithdrawn_root_before_dwm_restore():
    block = _block("_ensure_root_visible_after_taskbar", "_minimize_window")
    assert 'state == "withdrawn" or not viewable' in block
    assert "self._taskbar_restore_pending = False" in block
    assert block.index("self._taskbar_restore_pending = False") < block.index("self._restore_dwm_host_after_taskbar()")


def test_map_event_does_not_bypass_taskbar_visibility_guard():
    src = Path(main.__file__).read_text(encoding="utf-8")
    start = src.index("    def _on_window_map(")
    end = src.index("    def normalize_url(", start)
    block = src[start:end]
    assert "if self._taskbar_restore_pending:" in block
    assert "elif self._dwm_host_suspended_for_minimize:" in block
