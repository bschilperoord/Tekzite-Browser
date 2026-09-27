import inspect

import main


def test_shutdown_removes_dwm_surface_before_chromium_flush():
    source = inspect.getsource(main.BrowserApp.on_close)
    assert "self._prepare_visual_shutdown()" in source
    assert source.index("self._prepare_visual_shutdown()") < source.index("close_embedded_chromium(")


def test_visual_shutdown_detaches_thumbnail_and_withdraws_shell():
    source = inspect.getsource(main.BrowserApp._prepare_visual_shutdown)
    assert "detach_embedded_chromium_dwm_thumbnail()" in source
    assert "self._destroy_dwm_host_for_taskbar()" in source
    assert "self.root.withdraw()" in source


def test_final_dwm_cleanup_remains_idempotent():
    source = inspect.getsource(main.BrowserApp.on_close)
    assert "if self._dwm_host is not None:" in source
    assert "self._destroy_dwm_host_for_taskbar()" in source
