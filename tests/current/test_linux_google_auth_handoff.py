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


def test_linux_google_auth_launch_uses_one_initial_window():
    source = inspect.getsource(net.start_standalone_auth_chromium)
    linux_comment = "On Linux, do not force --new-window."
    assert linux_comment in source
    # The switch must be Windows-only.
    conditional = source[source.index('if os.name == "nt":'):source.index("command.append(target_url)")]
    assert 'command.append("--new-window")' in conditional
    assert 'else:' not in conditional


def test_linux_google_auth_close_is_cooperative_only():
    helper = inspect.getsource(net._request_linux_process_terminate)
    close = inspect.getsource(net.close_standalone_auth_chromium)
    embedded = inspect.getsource(net._close_embedded_chromium_cleanly_for_auth_unlocked)

    assert "signal.SIGTERM" in helper
    assert "SIGKILL" not in helper
    assert "taskkill" not in helper
    assert "_profile_chromium_pids(profile)" in close
    assert "_request_linux_process_terminate(verified)" in close
    close_code = "\n".join(
        line for line in close.splitlines()
        if not line.lstrip().startswith("#") and '"""' not in line
    )
    assert "signal.SIGKILL" not in close_code
    assert "_terminate_profile_chromium_processes" not in close_code
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


def test_linux_auth_window_snapshot_uses_ewmh_title_and_pid():
    source = inspect.getsource(net._linux_x11_auth_window_snapshot)
    assert '"_NET_CLIENT_LIST"' in source
    assert '"_NET_WM_PID"' in source
    assert '"_NET_WM_NAME"' in source
    assert '"UTF8_STRING"' in source
    assert "handle[\"auth_xids\"]" in source


def test_linux_youtube_window_title_completes_auth_immediately(monkeypatch):
    handle = {
        "profile": "/tmp/tekzite-profile",
        "return_url": "https://www.youtube.com/",
        "url": "https://accounts.google.com/signin/v2/identifier",
        "launched_monotonic": 0.0,
    }
    monkeypatch.setattr(
        net,
        "_standalone_auth_window_snapshot",
        lambda _handle: [{
            "xid": 0x1234,
            "pid": 4321,
            "class": "X11",
            "title": "YouTube",
        }],
    )
    monkeypatch.setattr(
        net,
        "_snapshot_google_auth_cookie_state",
        lambda profile: (_ for _ in ()).throw(AssertionError("disk fallback should not run")),
    )

    assert net.standalone_google_auth_succeeded(handle) is True
    assert handle["google_auth_return_xid"] == 0x1234
    assert handle["google_auth_return_title"] == "YouTube"
    assert handle["google_auth_success_signal"][0] == "window"


def test_google_auth_return_remembers_exact_tekzite_tab():
    start = MAIN.index("def _maybe_start_google_auth_handoff")
    end = MAIN.index("def _poll_google_auth_launch", start)
    block = MAIN[start:end]
    assert "self._google_auth_return_tab_id = tab.get(\"id\")" in block


def test_google_auth_close_reopens_and_refreshes_original_youtube_tab():
    finish = inspect.getsource(main.BrowserApp._finish_google_auth_handoff)
    refresh = inspect.getsource(main.BrowserApp._refresh_after_google_auth)
    poll = inspect.getsource(main.BrowserApp._poll_embedded_navigation)
    release = inspect.getsource(main.BrowserApp._poll_google_auth_profile_release)

    assert "return_tab_id = getattr(self, \"_google_auth_return_tab_id\", None)" in finish
    assert "item.get(\"id\") == return_tab_id" in finish
    assert "self.active_tab_id = tab.get(\"id\")" in finish
    assert "Google sign-in complete; refreshing YouTube in Tekzite" in finish
    assert "self.navigate_to(return_url, add_history=False, reuse_existing=False)" in finish

    assert "pending_auth_tab_id == self.active_tab_id" in poll
    assert "self._refresh_after_google_auth" in poll
    assert "pending_auth_tab_id" in poll

    assert "item.get(\"id\") == expected_tab_id" in refresh
    assert "self.navigate_to(expected_url, add_history=False, reuse_existing=False)" in refresh

    # The return path must start only after the external Chromium profile has
    # been fully released.
    assert "if not released:" in release
    assert "self._finish_google_auth_handoff" in release
    assert release.index("if not released:") < release.index("self._finish_google_auth_handoff")
