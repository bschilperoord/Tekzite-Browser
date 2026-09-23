from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / ".build" / "apply-v10.5.61.py"), run_name="__main__")

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"Could not find {label}")
    return text.replace(old, new, 1)

# ---- engine/net.py -------------------------------------------------------
engine = read("engine/net.py")

# Include auth temp profiles in normal orphan cleanup.
engine = engine.replace(
    'name.startswith("Tekzite-Private-") or name.startswith("Tekzite-Privacy-")',
    'name.startswith("Tekzite-Private-") or name.startswith("Tekzite-Privacy-") or name.startswith("Tekzite-Auth-")',
)
engine = engine.replace(
    'for prefix in ("Tekzite-Private-", "Tekzite-Privacy-"):',
    'for prefix in ("Tekzite-Private-", "Tekzite-Privacy-", "Tekzite-Auth-"):',
)

# Snapshot DB + WAL so successful-login detection sees live cookie writes.
snap_start = engine.index("def _snapshot_google_auth_cookie_state(profile):")
snap_end = engine.index("def standalone_google_auth_succeeded(", snap_start)
new_snapshot = r'''def _snapshot_google_auth_cookie_state(profile):
    """Return a stable fingerprint of Google auth cookies, including live WAL writes."""
    snapshot = {}
    for db_path in _google_cookie_db_candidates(profile):
        if not db_path.is_file():
            continue
        temp_dir = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="tekzite-google-cookie-snapshot-"))
            temp_db = temp_dir / "Cookies"
            shutil.copyfile(db_path, temp_db)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(str(db_path) + suffix)
                if sidecar.is_file():
                    try:
                        shutil.copyfile(sidecar, Path(str(temp_db) + suffix))
                    except Exception:
                        pass

            con = sqlite3.connect(str(temp_db), timeout=0.2)
            try:
                rows = con.execute(
                    "SELECT host_key, name, value, encrypted_value, expires_utc "
                    "FROM cookies "
                    "WHERE (host_key LIKE '%.google.com' OR host_key = '.google.com' "
                    "OR host_key = 'accounts.google.com')"
                ).fetchall()
            finally:
                con.close()

            for host, name, value, encrypted, expires in rows:
                name = str(name or "")
                if name not in _GOOGLE_AUTH_COOKIE_NAMES:
                    continue
                host = str(host or "")
                plain = str(value or "").encode("utf-8", "replace")
                encrypted = bytes(encrypted or b"")
                payload = (
                    host.encode("utf-8", "replace") + b"\0" +
                    name.encode("utf-8", "replace") + b"\0" +
                    plain + b"\0" + encrypted + b"\0" +
                    str(expires or "").encode("ascii", "replace")
                )
                snapshot[(host, name)] = hashlib.sha256(payload).hexdigest()
            if snapshot:
                break
        except Exception:
            continue
        finally:
            if temp_dir is not None:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
    return snapshot


'''
engine = engine[:snap_start] + new_snapshot + engine[snap_end:]

# The emergency on-screen correction must never resize the real browser.
force_start = engine.index("def _force_standalone_auth_window_onscreen(")
force_end = engine.index("def start_standalone_auth_chromium(", force_start)
force_block = engine[force_start:force_end]
force_block = force_block.replace(
    'SWP_NOACTIVATE = 0x0010\n        SWP_SHOWWINDOW = 0x0040',
    'SWP_NOSIZE = 0x0001\n        SWP_NOACTIVATE = 0x0010\n        SWP_SHOWWINDOW = 0x0040',
)
force_block = force_block.replace(
    '''                hwnd, HWND_TOP, x, y, width, height,
                SWP_NOACTIVATE | SWP_SHOWWINDOW,
''',
    '''                hwnd, HWND_TOP, x, y, 0, 0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
''',
)
force_block = force_block.replace(
    '"""Move Chromium\'s real top-level auth window into the visible work area."""',
    '"""Move Chromium on-screen without ever resizing the user-resizable window."""',
)
engine = engine[:force_start] + force_block + engine[force_end:]

profile_helpers = r'''def _sqlite_clone_database(source, destination):
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tekzite-copy")
    try:
        temp.unlink(missing_ok=True)
    except Exception:
        pass
    src = dst = None
    try:
        src = sqlite3.connect(str(source), timeout=1.0)
        dst = sqlite3.connect(str(temp), timeout=1.0)
        src.backup(dst)
        dst.commit()
    finally:
        if dst is not None:
            try:
                dst.close()
            except Exception:
                pass
        if src is not None:
            try:
                src.close()
            except Exception:
                pass
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            Path(str(destination) + suffix).unlink(missing_ok=True)
        except Exception:
            pass
    os.replace(temp, destination)
    return True


def _first_cookie_db(profile):
    return next((path for path in _google_cookie_db_candidates(profile) if path.is_file()), None)


def _prepare_standalone_auth_profile(persistent_profile):
    """Create a clean normal-window profile with only identity/session material."""
    persistent = Path(str(persistent_profile or ""))
    auth = Path(tempfile.mkdtemp(prefix=f"Tekzite-Auth-{os.getpid()}-"))

    local_state = persistent / "Local State"
    if local_state.is_file():
        try:
            shutil.copy2(local_state, auth / "Local State")
        except Exception:
            pass

    source_db = _first_cookie_db(persistent)
    cookie_relative = Path("Default") / "Network" / "Cookies"
    if source_db is not None:
        try:
            cookie_relative = source_db.relative_to(persistent)
        except Exception:
            pass
        _sqlite_clone_database(source_db, auth / cookie_relative)

    # Intentionally do NOT copy Preferences / window placement. Chromium builds
    # a fresh normal-browser state, so Tekzite's historical off-screen app-mode
    # geometry and DWM lifecycle cannot leak into the login window.
    return str(auth), str(cookie_relative)


def _sync_standalone_auth_profile(handle):
    """Copy the closed auth profile's cookie DB back into Tekzite's profile."""
    if not isinstance(handle, dict):
        return False
    auth = Path(str(handle.get("profile") or ""))
    persistent = Path(str(handle.get("persistent_profile") or ""))
    if not auth or not persistent:
        return False

    relative = Path(str(handle.get("cookie_relative_path") or "Default/Network/Cookies"))
    source_db = auth / relative
    if not source_db.is_file():
        source_db = _first_cookie_db(auth)
    if source_db is None or not source_db.is_file():
        return True

    try:
        if source_db.is_relative_to(auth):
            relative = source_db.relative_to(auth)
    except Exception:
        pass
    destination = persistent / relative
    return bool(_sqlite_clone_database(source_db, destination))


def _cleanup_standalone_auth_profile(handle):
    if not isinstance(handle, dict):
        return True
    auth = str(handle.get("profile") or "")
    persistent = str(handle.get("persistent_profile") or "")
    if not auth or os.path.normcase(os.path.abspath(auth)) == os.path.normcase(os.path.abspath(persistent or auth)):
        return True
    return bool(remove_profile_tree(auth, retries=10, delay=0.06))


'''
start_idx = engine.index("def start_standalone_auth_chromium(url: str):")
engine = engine[:start_idx] + profile_helpers + engine[start_idx:]

start_idx = engine.index("def start_standalone_auth_chromium(url: str):")
end_idx = engine.index("def standalone_auth_chromium_running(handle):", start_idx)
new_start = r'''def start_standalone_auth_chromium(url: str):
    """Launch Google auth in a clean, normal, independently resizable Chromium profile."""
    if os.name != "nt":
        raise RuntimeError(
            "Standalone authentication handoff is currently implemented for Windows"
        )

    target_url = str(url or "").strip()
    parts = urlsplit(target_url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Authentication handoff requires a normal http/https URL")

    with _EDGE_SESSION_LOCK:
        session = _EDGE_SESSION or {}
        executable = str(session.get("executable") or "")
        persistent_profile = str(session.get("profile") or _persistent_edge_profile_dir())
        if not executable:
            executable = next(iter(_chromium_candidates()), "")
        if not executable or not os.path.isfile(executable):
            raise RuntimeError("No Chromium executable is available for authentication")

        _close_embedded_chromium_unlocked(clear_profile=False)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not _profile_chromium_pids(persistent_profile):
                break
            time.sleep(0.05)
        if _profile_chromium_pids(persistent_profile):
            _terminate_profile_chromium_processes(persistent_profile)

        _clear_devtools_active_port(persistent_profile)
        _clear_chromium_profile_locks(persistent_profile)

        auth_profile, cookie_relative = _prepare_standalone_auth_profile(persistent_profile)
        google_auth_cookie_baseline = _snapshot_google_auth_cookie_state(auth_profile)

        x, y, width, height = _standalone_auth_window_geometry()
        command = [
            executable,
            f"--user-data-dir={auth_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-background-mode",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-features=CalculateNativeWinOcclusion",
            f"--window-position={x},{y}",
            f"--window-size={width},{height}",
            "--new-window",
            target_url,
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=None,
        )

        launched_at = time.monotonic()
        browser_pids = []
        stable_rounds = 0
        last_pids = []
        while time.monotonic() - launched_at < 4.0:
            current = sorted(set(_profile_chromium_pids(auth_profile)))
            if current:
                if current == last_pids:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_pids = list(current)
                browser_pids = list(current)
                launcher_alive = process.poll() is None
                if stable_rounds >= (2 if launcher_alive else 3):
                    break
            time.sleep(0.10)

        if not browser_pids and process.poll() is None:
            browser_pids = [int(process.pid)]

        # Only correct location. Never force size after Chromium has created its
        # normal top-level window, so user resizing remains entirely native.
        for _ in range(8):
            if _force_standalone_auth_window_onscreen(
                browser_pids, (x, y, width, height)
            ):
                break
            time.sleep(0.10)

        return {
            "process": process,
            "launch_pid": int(process.pid),
            "browser_pids": list(browser_pids),
            "profile": auth_profile,
            "persistent_profile": persistent_profile,
            "cookie_relative_path": cookie_relative,
            "auth_profile_isolated": True,
            "executable": executable,
            "url": target_url,
            "window_geometry": (x, y, width, height),
            "google_auth_cookie_baseline": dict(google_auth_cookie_baseline),
            "google_auth_cookie_last_snapshot": dict(google_auth_cookie_baseline),
            "google_auth_cookie_change_at": None,
            "auto_close_requested": False,
            "command_flags": [arg for arg in command[1:] if str(arg).startswith("--")],
            "remote_debugging": False,
            "cdp_control": False,
        }


'''
engine = engine[:start_idx] + new_start + engine[end_idx:]

wait_start = engine.index("def wait_for_standalone_auth_chromium_release(handle, timeout: float = 6.0):")
wait_end = engine.index("def _pick_devtools_page(", wait_start)
new_wait = r'''def wait_for_standalone_auth_chromium_release(handle, timeout: float = 6.0):
    """Wait for auth Chromium to close, sync cookies, then remove its temp profile."""
    if not isinstance(handle, dict):
        return True

    profile = str(handle.get("profile") or "")
    deadline = time.monotonic() + max(1.0, float(timeout))
    released = False
    while time.monotonic() < deadline:
        if standalone_auth_chromium_running(handle):
            time.sleep(0.08)
            continue
        if profile and _profile_chromium_pids(profile):
            time.sleep(0.08)
            continue
        if profile and _profile_recovery_needed(profile):
            time.sleep(0.08)
            continue
        released = True
        break

    if not released and profile and not _profile_chromium_pids(profile):
        _clear_chromium_profile_locks(profile)
        released = not _profile_recovery_needed(profile)

    if not released:
        return False

    synced = False
    try:
        synced = bool(_sync_standalone_auth_profile(handle))
        handle["cookie_sync_succeeded"] = synced
    except Exception as exc:
        handle["cookie_sync_succeeded"] = False
        handle["cookie_sync_error"] = f"{type(exc).__name__}: {exc}"
        synced = False

    if not synced:
        return False

    try:
        handle["auth_profile_cleanup_succeeded"] = bool(
            _cleanup_standalone_auth_profile(handle)
        )
    except Exception:
        handle["auth_profile_cleanup_succeeded"] = False
    return True


'''
engine = engine[:wait_start] + new_wait + engine[wait_end:]
write("engine/net.py", engine)

# ---- main.py -------------------------------------------------------------
main = read("main.py")
main = main.replace('BROWSER_VERSION = "10.5.61"', 'BROWSER_VERSION = "10.5.62"', 1)
main = main.replace(
    "Google sign-in window is open; close it when authentication is finished",
    "Google sign-in window is open; it will close automatically after sign-in",
)
write("main.py", main)

# ---- release metadata ----------------------------------------------------
manifest = json.loads(read("chromium_zoom_extension/manifest.json"))
manifest["version"] = "10.5.62"
write("chromium_zoom_extension/manifest.json", json.dumps(manifest, indent=2) + "\n")

installer = read("installer/TekziteBrowser.iss")
installer = re.sub(r'#define MyAppVersion "10\.5\.\d+"', '#define MyAppVersion "10.5.62"', installer, count=1)
write("installer/TekziteBrowser.iss", installer)

app_manifest = read("tekzite_browser.manifest")
app_manifest = re.sub(
    r'assemblyIdentity version="10\.5\.\d+\.0"',
    'assemblyIdentity version="10.5.62.0"',
    app_manifest,
    count=1,
)
write("tekzite_browser.manifest", app_manifest)

version_info = read("tekzite_version_info.txt")
version_info = version_info.replace("10.5.61", "10.5.62")
version_info = re.sub(r'filevers=\(10,\s*5,\s*\d+,\s*0\)', 'filevers=(10, 5, 62, 0)', version_info, count=1)
version_info = re.sub(r'prodvers=\(10,\s*5,\s*\d+,\s*0\)', 'prodvers=(10, 5, 62, 0)', version_info, count=1)
write("tekzite_version_info.txt", version_info)

print("Applied Tekzite Browser v10.5.62 isolated resizable auth profile fix")
