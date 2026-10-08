from unittest.mock import Mock

import pytest

import main


@pytest.mark.parametrize("line_height", [14, 23, 32, 44])
@pytest.mark.parametrize("density", ["compact", "comfortable", "spacious"])
def test_scaled_fonts_fit_inside_every_chrome_bar(monkeypatch, line_height, density):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.root = Mock()
    app.root.winfo_screenwidth.return_value = 1440
    app.root.winfo_screenheight.return_value = 900
    app._ui_font_family = "Segoe UI"
    app.customization = {"density": density, "ui_scale": 1.0}
    font = Mock()
    font.metrics.return_value = line_height
    monkeypatch.setattr(main.tkfont, "Font", Mock(return_value=font))
    for key, padding in {"app_bar_height": 14, "tab_bar_height": 18,
                         "toolbar_height": 20, "status_bar_height": 8,
                         "find_bar_height": 14}.items():
        assert app._ui_metric(key, 18) >= line_height + app._ui_padding(padding)


def test_roomy_custom_heights_and_non_chrome_metrics_are_preserved(monkeypatch):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app.root = Mock()
    app._ui_font_family = "Segoe UI"
    app.customization = {"density": "compact", "ui_scale": 1.0,
                         "status_bar_height": 60}
    font = Mock()
    font.metrics.return_value = 23
    factory = Mock(return_value=font)
    monkeypatch.setattr(main.tkfont, "Font", factory)
    assert app._ui_metric("status_bar_height", 26) == 60
    factory.reset_mock()
    assert app._ui_metric("content_corner_radius", 18) == 18
    factory.assert_not_called()
