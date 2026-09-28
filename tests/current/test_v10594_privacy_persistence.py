from pathlib import Path
from unittest.mock import Mock
import inspect

import main
from browser_state import load_session, write_json


def _app(tmp_path):
    app = main.BrowserApp.__new__(main.BrowserApp)
    app._state_directory = Path(tmp_path)
    app.preferences = {
        "restore_tabs": True,
        "privacy_lockdown": True,
        "clear_browsing_data_on_exit": False,
        "adblock_enabled": True,
        "adblock_sites": [],
        "tracker_blocking_enabled": True,
        "strip_referrer": True,
        "https_first": True,
    }
    app._private_mode = False
    app.root = Mock()
    app.status_var = Mock()
    app._init_features()
    app.tabs = [{
        "id": 1,
        "url": "https://example.test/",
        "title": "Example",
        "ready_state": "complete",
    }]
    app.active_tab_id = 1
    return app


def test_privacy_core_loads_existing_history(tmp_path):
    write_json(tmp_path / "history.json", [{
        "url": "https://saved.test/",
        "title": "Saved",
        "visited": 1.0,
    }])
    app = _app(tmp_path)
    assert [row["url"] for row in app.visits] == ["https://saved.test/"]


def test_privacy_core_records_and_checkpoints_browser_state(tmp_path):
    app = _app(tmp_path)
    app._record_page_visit(app.tabs[0])
    assert app.visits and app.visits[0]["url"] == "https://example.test/"
    app._checkpoint_features()
    assert (tmp_path / "history.json").exists()
    session = load_session(tmp_path / "session.json")
    assert session["tabs"][0]["url"] == "https://example.test/"
    assert session["clean_exit"] is False


def test_privacy_core_can_save_clean_tab_session(tmp_path):
    app = _app(tmp_path)
    app._save_session()
    session = load_session(tmp_path / "session.json")
    assert session["tabs"][0]["url"] == "https://example.test/"
    assert session["clean_exit"] is True


def test_privacy_core_does_not_force_ephemeral_chromium_profile():
    source = inspect.getsource(main.BrowserApp.__init__)
    assert "Tekzite-Privacy-" not in source
    assert "privacy_lockdown" not in source[source.index("self._privacy_profile_dir = None"):source.index("strict_python_loopback")]


def test_clear_profile_is_controlled_by_private_or_clear_on_exit():
    source = inspect.getsource(main.BrowserApp.on_close)
    call = source[source.index("close_embedded_chromium("):source.index("graceful=True")]
    assert "privacy_lockdown" not in call
    assert "clear_browsing_data_on_exit" in call
    assert "_private_mode" in call


def test_private_mode_remains_ephemeral():
    source = inspect.getsource(main.BrowserApp.__init__)
    assert 'tempfile.mkdtemp(prefix=f"Tekzite-Private-{os.getpid()}-")' in source
