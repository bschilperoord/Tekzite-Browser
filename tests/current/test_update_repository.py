import io
import hashlib
import json
from concurrent.futures import Future
from unittest.mock import Mock

import pytest

import main
from browser_features import BrowserFeatures, DEFAULT_UPDATE_REPOSITORY, update_release_asset


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


def asset(name, digest=None):
    return {"name": name, "browser_download_url": f"https://github.com/example/releases/download/v1/{name}", "digest": digest}


@pytest.mark.parametrize("platform,expected", [("win32", "Tekzite-Windows-x64.exe"), ("linux", "Tekzite-Linux-x86_64"), ("darwin", None)])
def test_matching_platform_prefers_direct_executable(platform, expected):
    assets = [asset("Tekzite-Linux-x86_64.tar.gz"), asset("Tekzite-Windows-x64.zip"), asset("Tekzite-Windows-x64.exe"), asset("Tekzite-Linux-x86_64"), asset("SHA256SUMS-Linux.txt")]
    chosen = update_release_asset(assets, platform)
    assert (chosen["name"] if chosen else None) == expected


def run_update_dialog(monkeypatch, tmp_path, tag="v10.5.127", digest=None, fail_download=False, platform="win32"):
    import browser_features as module
    content = b"test executable contents"
    name = "Tekzite-Linux-x86_64" if platform == "linux" else "Tekzite-Windows-x64.exe"
    release = {"tag_name": tag, "assets": [asset(name, digest)], "html_url": "https://github.com/example/releases/tag/v1"}
    requests = []
    def open_request(request, timeout):
        requests.append(request.full_url)
        if "/releases/latest" in request.full_url:
            return io.BytesIO(json.dumps(release).encode())
        if fail_download:
            raise OSError("Download interrupted")
        return io.BytesIO(content)
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    labels = []
    def label(*args, **kwargs):
        labels.append(kwargs.get("text", ""))
        return Mock()
    monkeypatch.setattr(module.tk, "Label", label)
    monkeypatch.setattr(module.tk, "Frame", Mock())
    app = Mock()
    app.preferences = {}
    app.browser_version = "10.5.126"
    app._parse_release_version = BrowserFeatures._parse_release_version
    app.ui = {"bg": "white", "text": "black"}
    buttons = {}
    app._feature_button.side_effect = lambda parent, name, callback: buttons.update({name: callback})
    app._feature_async.side_effect = lambda work, done, *args: done(work())
    BrowserFeatures._check_for_updates(app)
    return app, buttons, labels, requests, content


@pytest.mark.parametrize("tag,message,download", [("v10.5.127", "Update available.", True), ("v10.5.126", "Up to date.", False), ("v10.5.125", "Installed build is newer.", False)])
def test_update_dialog_compares_version_and_only_offers_newer_download(monkeypatch, tmp_path, tag, message, download):
    app, buttons, labels, requests, content = run_update_dialog(monkeypatch, tmp_path, tag)
    assert any(message in text for text in labels)
    assert ("Download update" in buttons) == download
    buttons["Open release page"]()
    app._new_tab.assert_called_once_with(url="https://github.com/example/releases/tag/v1")


def test_download_verifies_digest_and_preserves_existing_file(monkeypatch, tmp_path):
    digest = "sha256:" + hashlib.sha256(b"test executable contents").hexdigest()
    app, buttons, _, _, content = run_update_dialog(monkeypatch, tmp_path, digest=digest)
    folder = tmp_path / "Downloads"
    folder.mkdir()
    original = folder / "Tekzite-Windows-x64.exe"
    original.write_bytes(b"existing file")
    buttons["Download update"]()
    assert original.read_bytes() == b"existing file"
    assert (folder / "Tekzite-Windows-x64 (1).exe").read_bytes() == content
    assert not list(folder.glob("*.part"))
    assert "Verified." in app._show_message.call_args.args[2]


def test_linux_download_is_executable_and_reports_missing_digest(monkeypatch, tmp_path):
    app, buttons, _, _, content = run_update_dialog(monkeypatch, tmp_path, platform="linux")
    buttons["Download update"]()
    target = tmp_path / "Downloads" / "Tekzite-Linux-x86_64"
    assert target.read_bytes() == content
    assert target.stat().st_mode & 0o111 == 0o111
    assert "No published digest." in app._show_message.call_args.args[2]


@pytest.mark.parametrize("fail_download", [False, True])
def test_bad_digest_or_interrupted_download_leaves_no_executable(monkeypatch, tmp_path, fail_download):
    app, buttons, _, _, _ = run_update_dialog(monkeypatch, tmp_path, digest="sha256:" + "0" * 64, fail_download=fail_download)
    with pytest.raises((RuntimeError, OSError)):
        buttons["Download update"]()
    assert not list((tmp_path / "Downloads").iterdir())
    app._show_message.assert_not_called()


def test_async_network_failure_is_shown_to_user():
    app = Mock()
    app._closing = False
    future = Future()
    future.set_exception(OSError("Network unavailable"))
    app._executor.submit.return_value = future
    done = Mock()
    BrowserFeatures._feature_async(app, Mock(), done)
    app.root.after.call_args.args[1]()
    done.assert_not_called()
    app.status_var.set.assert_called_with("Network unavailable")
    app._show_message.assert_called_with("error", "Tekzite", "Network unavailable", parent=app.root)
