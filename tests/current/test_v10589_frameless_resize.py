from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "main.py").read_text(encoding="utf-8")


def _app(edge, origin=(100, 120, 1000, 700, 500, 400)):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.customization = {"window_min_width": 900, "window_min_height": 600}
    app._window_resize_edge = edge
    app._window_resize_origin = origin
    return app


def test_release_version_is_10589():
    assert main.BROWSER_VERSION == "10.5.125"


def test_frameless_root_is_explicitly_resizable_and_has_all_edge_grips():
    assert "self.root.resizable(True, True)" in SOURCE
    block = SOURCE[SOURCE.index("def _install_window_resize_handles"):SOURCE.index("def _refresh_window_resize_handles")]
    for edge in ('"n"', '"s"', '"w"', '"e"', '"nw"', '"ne"', '"sw"', '"se"'):
        assert edge in block


def test_east_and_south_resize_expand_from_fixed_top_left():
    app = _app("se")
    assert app._window_resize_geometry_for_pointer(650, 480) == (100, 120, 1150, 780)


def test_west_resize_moves_left_edge_and_respects_minimum_width():
    app = _app("w")
    # Dragging 400 px right would request 600 px, but minimum width is 900.
    assert app._window_resize_geometry_for_pointer(900, 400) == (200, 120, 900, 700)


def test_north_resize_moves_top_edge_and_respects_minimum_height():
    app = _app("n")
    # Bottom stays at y=820; minimum height is 600.
    assert app._window_resize_geometry_for_pointer(500, 700) == (100, 220, 1000, 600)


def test_resize_handles_hide_while_maximized_or_fullscreen():
    block = SOURCE[SOURCE.index("def _refresh_window_resize_handles"):SOURCE.index("def _start_window_resize")]
    assert "_window_maximized" in block
    assert "_fullscreen" in block
    assert "place_forget" in block


def test_resize_completion_forces_final_dwm_viewport_and_input_metrics_sync():
    block = SOURCE[SOURCE.index("def _end_window_resize"):SOURCE.index("def _get_work_area")]
    assert "resize=True" in block
    assert "refresh_input_metrics=True" in block
