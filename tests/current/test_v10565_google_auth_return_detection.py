from pathlib import Path
import inspect
import json
import sqlite3
import time

import main
import engine.net as net


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.73"  # sync_version updates this pin for the release


def test_clean_exit_repair_heals_old_crash_marker(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    default = profile / "Default"
    default.mkdir(parents=True)
    prefs = default / "Preferences"
    prefs.write_text(
        json.dumps({"profile": {"exit_type": "Crashed", "exited_cleanly": False}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(net, "_profile_chromium_pids", lambda _profile: [])

    assert net._mark_chromium_profile_exited_cleanly(profile)
    healed = json.loads(prefs.read_text(encoding="utf-8"))
    assert healed["profile"]["exit_type"] == "Normal"
    assert healed["profile"]["exited_cleanly"] is True


def test_live_history_snapshot_sees_return_navigation_in_wal(tmp_path):
    profile = tmp_path / "profile"
    db = profile / "Default" / "History"
    db.parent.mkdir(parents=True)

    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
        con.execute(
            "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)"
        )
        con.execute(
            "INSERT INTO urls(id, url) VALUES(1, ?)",
            ("https://www.youtube.com/signin?action_handle_signin=true",),
        )
        con.execute("INSERT INTO visits(id, url, visit_time) VALUES(1, 1, 100)")
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        baseline = net._snapshot_chromium_latest_visit(profile)
        assert baseline == (
            "https://www.youtube.com/signin?action_handle_signin=true",
            100,
            1,
        )

        con.execute("INSERT INTO urls(id, url) VALUES(2, ?)", ("https://www.youtube.com/",))
        con.execute("INSERT INTO visits(id, url, visit_time) VALUES(2, 2, 200)")
        con.commit()
        assert Path(str(db) + "-wal").is_file()

        latest = net._snapshot_chromium_latest_visit(profile)
        assert latest == ("https://www.youtube.com/", 200, 2)

        handle = {
            "profile": str(profile),
            "url": "https://www.youtube.com/signin?action_handle_signin=true",
            "return_url": "https://www.youtube.com/",
            "history_visit_baseline": baseline,
        }
        assert net._auth_navigation_has_returned(handle)
        assert handle["google_auth_return_visit"] == latest
    finally:
        con.close()


def test_signin_endpoint_itself_is_not_a_completed_return(tmp_path):
    profile = tmp_path / "profile"
    db = profile / "Default" / "History"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    try:
        con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
        con.execute(
            "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)"
        )
        con.execute("INSERT INTO urls(id, url) VALUES(1, ?)", ("https://www.youtube.com/",))
        con.execute("INSERT INTO visits(id, url, visit_time) VALUES(1, 1, 100)")
        con.execute(
            "INSERT INTO urls(id, url) VALUES(2, ?)",
            ("https://www.youtube.com/signin?action_handle_signin=true",),
        )
        con.execute("INSERT INTO visits(id, url, visit_time) VALUES(2, 2, 200)")
        con.commit()
        handle = {
            "profile": str(profile),
            "url": "https://www.youtube.com/signin?action_handle_signin=true",
            "return_url": "https://www.youtube.com/",
            "history_visit_baseline": ("https://www.youtube.com/", 100, 1),
        }
        assert not net._auth_navigation_has_returned(handle)
    finally:
        con.close()


def test_already_signed_in_return_can_complete_without_cookie_delta(monkeypatch):
    unchanged = {(".google.com", "SID"): "same-cookie"}
    handle = {
        "profile": "profile",
        "google_auth_cookie_baseline": dict(unchanged),
        "google_auth_cookie_last_snapshot": dict(unchanged),
        "google_auth_return_visit": ("https://www.youtube.com/", 200, 2),
    }
    monkeypatch.setattr(net, "_snapshot_google_auth_cookie_state", lambda _profile: dict(unchanged))
    monkeypatch.setattr(net, "_auth_navigation_has_returned", lambda _handle: True)

    signal = ("return", tuple(handle["google_auth_return_visit"]))
    handle["google_auth_success_signal"] = signal
    handle["google_auth_cookie_change_at"] = time.monotonic() - 2.0
    assert net.standalone_google_auth_succeeded(handle, 1.0)


def test_auth_launcher_repairs_crash_state_and_suppresses_legacy_bubble():
    source = inspect.getsource(net.start_standalone_auth_chromium)
    worker = inspect.getsource(main.BrowserApp._launch_google_auth_worker)
    assert "_mark_chromium_profile_exited_cleanly(profile)" in source
    assert '"--disable-session-crashed-bubble"' in source
    assert '"history_visit_baseline"' in source
    assert '"return_url"' in source
    assert "start_standalone_auth_chromium, launch_url, return_url" in worker
