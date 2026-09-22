from pathlib import Path

import main
from test_v10541_default_browser_detection import FakeWinreg, _url_path, _file_path


def test_release_version_is_10542():
    assert main.BROWSER_VERSION == "10.5.47"


def test_windows_applications_progid_is_recognized_as_tekzite():
    reg = FakeWinreg({
        _url_path("http"): r"Applications\\TekziteBrowser.exe",
        _url_path("https"): r"Applications\\TekziteBrowser.exe",
    })
    status = main._tekzite_default_browser_status(
        winreg_module=reg,
        executable_resolver=lambda _association: None,
        executable=r"C:\\Program Files\\Tekzite Browser\\TekziteBrowser.exe",
    )
    assert status["is_default"] is True


def test_versioned_release_executable_is_recognized_from_effective_shell_handler():
    reg = FakeWinreg({
        _url_path("http"): "SomeWindowsGeneratedProgId",
        _url_path("https"): "SomeWindowsGeneratedProgId",
    })
    def resolver(association):
        if association in {"http", "https"}:
            return r"C:\\Users\\Bas\\Downloads\\Tekzite-Browser-v10.5.41-Windows-x64.exe"
        return None
    status = main._tekzite_default_browser_status(
        winreg_module=reg,
        executable_resolver=resolver,
        executable=r"C:\\Users\\Bas\\Downloads\\Tekzite-Browser-v10.5.47-Windows-x64.exe",
    )
    assert status["http_default"] is True
    assert status["https_default"] is True
    assert status["is_default"] is True


def test_non_tekzite_effective_handler_wins_over_unrelated_progid():
    reg = FakeWinreg({
        _url_path("http"): "MSEdgeHTM",
        _url_path("https"): "MSEdgeHTM",
    })
    status = main._tekzite_default_browser_status(
        winreg_module=reg,
        executable_resolver=lambda _association: r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        executable=r"C:\\Program Files\\Tekzite Browser\\TekziteBrowser.exe",
    )
    assert status["is_default"] is False


def test_settings_copy_describes_effective_windows_shell_handler():
    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "asks the Windows Shell which app actually handles HTTP/HTTPS" in source
    assert "_windows_effective_association_executable" in source
