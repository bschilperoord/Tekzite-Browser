from pathlib import Path
import inspect

import main
import engine.net as net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.73"


def test_native_windows_identity_and_taskbar_guard_remain_present():
    assert "SetCurrentProcessExplicitAppUserModelID" in MAIN
    assert "Tekzite.Browser" in MAIN
    assert "WM_SETICON" in MAIN
    assert "def _taskbar_presence_guard(self):" in MAIN
    assert "self._apply_frameless_app_style()" in MAIN
    assert (ROOT / "assets" / "tekzite.ico").is_file()
    assert (ROOT / "assets" / "tekzite.png").is_file()


def test_google_auth_url_handoff_unwraps_rejected_continue_url():
    rejected = (
        "https://accounts.google.com/v3/signin/rejected?"
        "continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3F"
        "action_handle_signin%3Dtrue%26next%3Dhttps%253A%252F%252Fwww.youtube.com%252F"
    )
    assert main.BrowserApp._is_google_auth_url(rejected)
    launch, return_url = main.BrowserApp._google_auth_handoff_urls(
        rejected, "https://www.youtube.com/"
    )
    assert launch.startswith("https://www.youtube.com/signin")
    assert return_url == "https://www.youtube.com/"


def test_standalone_google_auth_uses_visible_non_cdp_chromium_window():
    source = inspect.getsource(net.start_standalone_auth_chromium)
    assert "--new-window" in source
    assert "--window-position=" in source
    assert "--window-size=" in source
    assert "_force_standalone_auth_window_onscreen" in source
    assert "_profile_chromium_pids(profile)" in source
    assert '"browser_pids": list(browser_pids)' in source
    assert "--remote-debugging" not in source
    assert "--app=" not in source
    assert '"remote_debugging": False' in source
    assert '"cdp_control": False' in source


def test_google_auth_auto_close_and_profile_release_helpers_exist():
    assert callable(net.standalone_google_auth_succeeded)
    assert callable(net.close_standalone_auth_chromium)
    assert callable(net.standalone_auth_chromium_running)
    assert callable(net.wait_for_standalone_auth_chromium_release)
    assert callable(net.detach_embedded_chromium_dwm_thumbnail)
    poll_source = inspect.getsource(main.BrowserApp._poll_google_auth_window)
    assert "standalone_google_auth_succeeded" in poll_source
    assert "close_standalone_auth_chromium" in poll_source
    assert "wait_for_standalone_auth_chromium_release" in poll_source
