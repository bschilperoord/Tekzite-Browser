from unittest.mock import Mock

import main


def test_menu_labels_and_shortcuts_use_shared_columns():
    app = Mock()
    app._ui_font_family = "Segoe UI"
    app._font_size.return_value = 10
    app._ui_padding.side_effect = lambda size: size
    app.ui = main.UI_COLOR_DEFAULTS
    menu = main._AnimatedPopupMenu(app)
    for icon, label in [("↓", "Downloads"), ("⚙", "Settings"), ("</>", "Inspector"), ("", "Plain")]:
        menu.add_command(label=main.BrowserApp._menu_item_text(label, icon), accelerator="F8")
    menu.add_cascade(label=main.BrowserApp._menu_item_text("More", "→"), accelerator="F9")
    menu._width = 400
    menu._height = 200
    menu._rows = [(i, i * 32, (i + 1) * 32) for i in range(5)]
    menu._canvas = Mock()
    menu._draw()
    calls = menu._canvas.create_text.call_args_list
    labels = [c for c in calls if c.kwargs["text"] in {"Downloads", "Settings", "Inspector", "Plain", "More"}]
    assert len(labels) == 5
    assert len({c.args[0] for c in labels}) == 1
    shortcuts = [c for c in calls if c.kwargs["text"] in {"F8", "F9"}]
    assert len(shortcuts) == 5
    assert len({c.args[0] for c in shortcuts}) == 1
