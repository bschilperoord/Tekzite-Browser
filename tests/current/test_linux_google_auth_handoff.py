from pathlib import Path
import inspect

import main
import engine.net as net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_linux_google_auth_trigger_is_enabled():
    source = inspect.getsource(main.BrowserApp._maybe_start_google_auth_handoff)
    assert 'sys.platform.startswith("linux")' in source
    assert 'os.name != "nt" and not sys.platform.startswith("linux")' in source
    assert "start_standalone_auth_chromium" not in source
    assert "self._launch_google_auth_worker" in source


def test_linux_profile_owner_detection_matches_exact_user_data_dir(tmp_path):
    proc = tmp_path / "proc"
    profile = tmp_path / "tekzite-profile"
    profile.mkdir()

    matching = proc / "1234"
    matching.mkdir(parents=True)
    (matching / "cmdline").write_bytes(
        b"/usr/bin/chromium\0--type=browser\0--user-data-dir=" +
        str(profile).encode("utf-8") + b"\0"
    )

    other = proc / "2345"
    other.mkdir(parents=True)
    (other / "cmdline").write_bytes(
        b"/usr/bin/chromium\0--user-data-dir=/tmp/not-tekzite\0"
    )

    unrelated = proc / "3456"
    unrelated.mkdir(parents=True)
    (unrelated / "cmdline").write_bytes(
        b"/usr/bin/python\0--user-data-dir=" +
        str(profile).encode("utf-8") + b"\0"
    )

    assert net._linux_profile_chromium_pids(profile, proc_root=str(proc)) == [1234]


def test_linux_auth_window_is_normal_visible_chromium_without_cdp():
    source = inspect.getsource(net.start_standalone_auth_chromium)
    assert 'sys.platform.startswith("linux")' in source
    assert '"--new-window"' in source
    assert '"--window-position=' in source
    assert '"--window-size=' in source
    assert 'start_new_session=sys.platform.startswith("linux")' in source
    assert "--headless" not in source
    assert "--remote-debugging" not in source
    assert "--app=" not in source
    assert '"remote_debugging": False' in source
    assert '"cdp_control": False' in source


def test_linux_google_auth_close_is_cooperative_only():
    helper = inspect.getsource(net._request_linux_process_terminate)
    close = inspect.getsource(net.close_standalone_auth_chromium)
    embedded = inspect.getsource(net._close_embedded_chromium_cleanly_for_auth_unlocked)

    assert "signal.SIGTERM" in helper
    assert "SIGKILL" not in helper
    assert "taskkill" not in helper
    assert "_profile_chromium_pids(profile)" in close
    assert "_request_linux_process_terminate(verified)" in close
    assert "SIGKILL" not in close
    assert "_terminate_profile_chromium_processes" not in close
    assert '"Browser.close"' in embedded
    assert "_request_linux_process_terminate(retry_pids)" in embedded


def test_google_auth_completion_keeps_cookie_and_history_fallbacks_on_linux():
    source = inspect.getsource(net.standalone_google_auth_succeeded)
    assert "_snapshot_google_auth_cookie_state(profile)" in source
    assert "_auth_navigation_has_returned(handle)" in source
    assert "_auth_window_title_has_returned(handle)" in source


def test_auth_profile_release_wait_is_shared_across_platforms():
    source = inspect.getsource(net.wait_for_standalone_auth_chromium_release)
    assert "standalone_auth_chromium_running(handle)" in source
    assert "_profile_chromium_pids(profile)" in source
    assert "_profile_recovery_needed(profile)" in source
