from pathlib import Path
import inspect
import sqlite3

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.73"


def test_live_cookie_snapshot_sees_wal_commits(tmp_path):
    profile = tmp_path / "profile"
    db = profile / "Default" / "Network" / "Cookies"
    db.parent.mkdir(parents=True)

    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute(
            "CREATE TABLE cookies ("
            "host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, expires_utc INTEGER)"
        )
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        baseline = net._snapshot_google_auth_cookie_state(profile)
        assert baseline == {}

        con.execute(
            "INSERT INTO cookies(host_key, name, value, encrypted_value, expires_utc) "
            "VALUES(?, ?, ?, ?, ?)",
            (".google.com", "SID", "", b"new-auth-cookie", 999999999),
        )
        con.commit()
        assert Path(str(db) + "-wal").is_file()

        current = net._snapshot_google_auth_cookie_state(profile)
        assert current is not None
        assert (".google.com", "SID") in current

        con.execute(
            "INSERT INTO cookies(host_key, name, value, encrypted_value, expires_utc) "
            "VALUES(?, ?, ?, ?, ?)",
            (".youtube.com", "LOGIN_INFO", "", b"youtube-auth-cookie", 999999999),
        )
        con.commit()
        current = net._snapshot_google_auth_cookie_state(profile)
        assert current is not None
        assert (".youtube.com", "LOGIN_INFO") in current
    finally:
        con.close()


def test_google_auth_close_retries_without_dirty_profile_kill():
    poll_source = inspect.getsource(main.BrowserApp._poll_google_auth_window)
    close_source = inspect.getsource(net.close_standalone_auth_chromium)
    running_source = inspect.getsource(net.standalone_auth_chromium_running)

    assert "elapsed >= 1.6" in poll_source
    assert "elapsed >= 3.8" in poll_source
    assert "close_standalone_auth_chromium, handle, cooperative_escalation" in poll_source
    assert "_profile_chromium_pids(profile)" in close_source
    assert "_terminate_profile_chromium_processes(profile)" not in close_source
    assert "_profile_chromium_pids(profile)" in running_source


def test_google_auth_return_page_gets_one_shot_authenticated_refresh():
    finish_source = inspect.getsource(main.BrowserApp._finish_google_auth_handoff)
    refresh_source = inspect.getsource(main.BrowserApp._refresh_after_google_auth)
    nav_source = inspect.getsource(main.BrowserApp._poll_embedded_navigation)

    assert "self._google_auth_refresh_pending_url = return_url" in finish_source
    assert "self.navigate_to(expected_url, add_history=False, reuse_existing=False)" in refresh_source
    assert "pending_auth_refresh" in nav_source
    assert "self._google_auth_refresh_pending_url = None" in nav_source
    assert "self.root.after(650, self._refresh_after_google_auth" in nav_source
