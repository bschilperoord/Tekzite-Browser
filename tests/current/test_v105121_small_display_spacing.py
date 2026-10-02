import inspect

import main


class _FakeRoot:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def winfo_screenwidth(self):
        return self._width

    def winfo_screenheight(self):
        return self._height


def _app(width, height, *, density="comfortable", ui_scale=1.0):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.root = _FakeRoot(width, height)
    app.customization = {
        "density": density,
        "ui_scale": ui_scale,
        "toolbar_height": 62,
    }
    return app


def test_small_display_spacing_profiles_are_roomier():
    padding, chrome = main._small_display_spacing_factors(1366, 768)
    assert padding == 1.16
    assert chrome == 1.06

    padding, chrome = main._small_display_spacing_factors(1600, 900)
    assert padding == 1.10
    assert chrome == 1.04

    assert main._small_display_spacing_factors(1920, 1080) == (1.0, 1.0)
    assert main._small_display_spacing_factors(3440, 1440) == (1.0, 1.0)


def test_default_comfortable_layout_uses_small_display_breathing_room():
    app = _app(1366, 768)
    assert app._display_spacing_factors() == (1.16, 1.06)
    assert app._ui_padding(10) == 12
    assert app._ui_metric("toolbar_height", 62) == 66


def test_explicit_density_and_scale_choices_remain_authoritative():
    assert _app(1366, 768, density="compact")._display_spacing_factors() == (1.0, 1.0)
    assert _app(1366, 768, density="spacious")._display_spacing_factors() == (1.0, 1.0)
    assert _app(1366, 768, ui_scale=1.15)._display_spacing_factors() == (1.0, 1.0)


def test_adaptive_spacing_only_touches_chrome_metrics_not_general_sizes():
    app = _app(1366, 768)
    assert app._ui_metric("toolbar_height", 62) == 66
    assert app._ui_metric("window_width", 1440) == 1440

    source = inspect.getsource(main.BrowserApp._ui_metric)
    assert "app_bar_height" in source
    assert "toolbar_height" in source
    assert "window_width" not in source
