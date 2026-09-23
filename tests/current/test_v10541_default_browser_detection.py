import os
from pathlib import Path

import main


def test_release_version_is_10541():
    assert main.BROWSER_VERSION == "10.5.73"


class _Key:
    def __init__(self, path):
        self.path = path
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_READ = 0x20019
    def __init__(self, values):
        self.values = values
    def OpenKey(self, root, path, reserved, access):
        if path not in self.values:
            raise FileNotFoundError(path)
        return _Key(path)
    def QueryValueEx(self, key, name):
        assert name == "ProgId"
        return self.values[key.path], 1


def _url_path(scheme):
    return rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice"


def _file_path(ext):
    return rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice"


def test_detects_tekzite_as_default_when_http_and_https_userchoice_match():
    reg = FakeWinreg({
        _url_path("http"): "TekziteBrowserURL",
        _url_path("https"): "TekziteBrowserURL",
        _file_path(".html"): "TekziteBrowserHTML",
        _file_path(".htm"): "TekziteBrowserHTML",
    })
    status = main._tekzite_default_browser_status(winreg_module=reg)
    assert status["is_default"] is True
    assert status["http_default"] is True
    assert status["https_default"] is True
    assert status["html_default"] is True
    assert status["htm_default"] is True


def test_detects_partial_and_non_default_windows_associations():
    reg = FakeWinreg({
        _url_path("http"): "TekziteBrowserURL",
        _url_path("https"): "MSEdgeHTM",
    })
    status = main._tekzite_default_browser_status(winreg_module=reg)
    assert status["is_default"] is False
    assert status["http_default"] is True
    assert status["https_default"] is False
    assert status["html"] is None
    assert status["htm"] is None


def test_userchoice_reader_is_read_only_and_rejects_unknown_association():
    reg = FakeWinreg({_url_path("https"): "TekziteBrowserURL"})
    assert main._windows_user_choice_progid("https", winreg_module=reg) == "TekziteBrowserURL"
    try:
        main._windows_user_choice_progid("ftp", winreg_module=reg)
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported associations must raise ValueError")


def test_settings_has_live_default_browser_refresh_loop():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "refresh_default_browser_status" in source
    assert 'win.bind("<FocusIn>"' in source
    assert "win.after(1200, poll_default_browser_status)" in source
    assert "Tekzite is your default browser for HTTP and HTTPS" in source
