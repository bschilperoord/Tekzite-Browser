from types import SimpleNamespace
from unittest.mock import Mock

import main


class _Widget:
    def __init__(self, *, x=100, y=50, width=500, height=48):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self.cursor = None

    def update_idletasks(self):
        pass

    def winfo_rootx(self):
        return self._x

    def winfo_rooty(self):
        return self._y

    def winfo_width(self):
        return self._width

    def winfo_height(self):
        return self._height

    def configure(self, **kwargs):
        if "cursor" in kwargs:
            self.cursor = kwargs["cursor"]


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def _event(x_root, y_root):
    return SimpleNamespace(x_root=x_root, y_root=y_root)


def test_release_version_and_window_position_parser():
    assert main.BROWSER_VERSION == "10.5.105"
    assert main._requested_window_position(["--window-position=123,-45"]) == (123, -45)
    assert main._requested_window_position(["--window-position=nope"]) is None
    assert main._requested_window_position([]) is None


def test_tab_only_becomes_tearoff_outside_expanded_strip():
    app = SimpleNamespace(tab_items=_Widget(), _tab_tearoff_margin_px=28)
    assert main.BrowserApp._tab_pointer_outside_strip(app, 250, 70) is False
    assert main.BrowserApp._tab_pointer_outside_strip(app, 250, 140) is True
    assert main.BrowserApp._tab_pointer_outside_strip(app, 40, 70) is True


def test_tab_drag_below_threshold_remains_click():
    widget = _Widget()
    app = SimpleNamespace(
        tabs=[{"id": 7}],
        tab_items=widget,
        _tab_drag_state=None,
        _tab_drag_threshold_px=9,
        _tab_tearoff_margin_px=28,
        status_var=_Status(),
    )
    main.BrowserApp._begin_tab_drag(app, 7, _event(200, 70), widget)
    result = main.BrowserApp._finish_tab_drag(app, 7, _event(205, 74))
    assert result == "click"


def test_drag_outside_strip_detaches_exact_tab():
    widget = _Widget()
    tear = Mock(return_value=True)
    app = SimpleNamespace(
        tabs=[{"id": 7}],
        tab_items=widget,
        _tab_drag_state=None,
        _tab_drag_threshold_px=9,
        _tab_tearoff_margin_px=28,
        status_var=_Status(),
        _tear_off_tab=tear,
    )
    main.BrowserApp._begin_tab_drag(app, 7, _event(200, 70), widget)
    main.BrowserApp._update_tab_drag(app, 7, _event(200, 150))
    result = main.BrowserApp._finish_tab_drag(app, 7, _event(200, 150))
    assert result == "detached"
    tear.assert_called_once_with(7, x_root=200, y_root=150)


def test_tearoff_spawns_new_window_then_moves_not_closes_tab():
    spawn = Mock(return_value=object())
    close = Mock()
    app = SimpleNamespace(
        tabs=[{"id": 4, "url": "https://example.test/page", "title": "Example"}],
        customization={"window_width": 1200},
        _private_mode=False,
        _profile_name="Default",
        _spawn_browser_process=spawn,
        _close_tab=close,
        status_var=_Status(),
    )
    assert main.BrowserApp._tear_off_tab(app, 4, x_root=700, y_root=240) is True
    kwargs = spawn.call_args.kwargs
    assert kwargs["target_url"] == "https://example.test/page"
    assert kwargs["private"] is False
    assert kwargs["profile"] == "Default"
    assert kwargs["window_position"] == (550, 216)
    close.assert_called_once_with(4, remember_closed=False)


def test_spawn_browser_process_carries_target_and_drop_position(monkeypatch):
    seen = {}

    def fake_popen(command, **kwargs):
        seen["command"] = list(command)
        seen["kwargs"] = dict(kwargs)
        return "proc"

    monkeypatch.setattr(main.subprocess, "Popen", fake_popen)
    app = SimpleNamespace(_profile_name="Default")
    result = main.BrowserApp._spawn_browser_process(
        app,
        private=False,
        target_url="https://example.test/",
        window_position=(321, 222),
    )
    assert result == "proc"
    assert "--window-position=321,222" in seen["command"]
    assert seen["command"][-1] == "https://example.test/"


def test_tab_context_menu_exposes_manual_move_to_new_window():
    source = open(main.__file__, encoding="utf-8").read()
    block = source[source.index("def _show_tab_context_menu"):source.index("def _queue_closed_target_retirement")]
    assert "Move Tab to New Window" in block
    assert "self._tear_off_tab(tab_id)" in block
