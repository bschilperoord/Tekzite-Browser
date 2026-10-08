import io
from unittest.mock import Mock

import pytest

import main
from browser_features import BrowserFeatures, DEFAULT_UPDATE_REPOSITORY


@pytest.mark.parametrize("saved", [{}, {"update_repository": ""}, {"update_repository": "   "}, {"update_repository": None}])
def test_new_and_existing_empty_preferences_use_official_repository(monkeypatch, saved):
    monkeypatch.setattr(main, "read_json", lambda *args: saved)
    assert main.load_preferences()["update_repository"] == DEFAULT_UPDATE_REPOSITORY


def test_existing_custom_repository_is_preserved(monkeypatch):
    monkeypatch.setattr(main, "read_json", lambda *args: {"update_repository": "  other/fork  "})
    assert main.load_preferences()["update_repository"] == "other/fork"


@pytest.mark.parametrize("repository,expected", [("", DEFAULT_UPDATE_REPOSITORY), ("   ", DEFAULT_UPDATE_REPOSITORY), ("https://github.com/other/fork.git", "other/fork")])
def test_update_checker_requests_selected_release_without_setup(monkeypatch, repository, expected):
    requests = []
    def open_request(request, timeout):
        requests.append(request.full_url)
        assert timeout == 10
        return io.BytesIO(b'{"tag_name": "v10.5.126"}')
    monkeypatch.setattr("browser_features.urllib.request.urlopen", open_request)
    app = Mock()
    app.preferences = {"update_repository": repository}
    app._feature_async.side_effect = lambda fetch, done: fetch()
    assert BrowserFeatures._check_for_updates(app) == "break"
    assert requests == [f"https://api.github.com/repos/{expected}/releases/latest"]
    app._show_message.assert_not_called()
