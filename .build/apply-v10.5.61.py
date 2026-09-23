from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / ".build" / "apply-v10.5.60.py"), run_name="__main__")

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

# stdlib-only cookie snapshot support.
engine = replace_once(
    engine,
    "import json\n",
    "import json\nimport hashlib\nimport shutil\nimport sqlite3\nimport tempfile\n",
    "engine stdlib auth cookie imports",
)

auth_cookie_helpers = r'''_GOOGLE_AUTH_COOKIE_NAMES = frozenset({
    "SID", "HSID", "SSID", "APISID", "SAPISID", "LSID",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
})


def _google_cookie_db_candidates(profile):
    root = Path(str(profile or ""))
    return (
        root / "Default" / "Network" / "Cookies",
        root / "Default" / "Cookies",
        root / "Network" / "Cookies",
        root / "Cookies",
    )


def _snapshot_google_auth_cookie_state(profile):
    """Return a stable fingerprint of Google auth cookies in a Chromium profile."""
    snapshot = {}
    for db_path in _google_cookie_db_candidates(profile):
        if not db_path.is_file():
            continue
        temp_path = None
        try:
            fd, temp_name = tempfile.mkstemp(prefix="tekzite-google-cookies-", suffix=".db")
            os.close(fd)
            temp_path = Path(temp_name)
            shutil.copyfile(db_path, temp_path)
            con = sqlite3.connect(str(temp_path))
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
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass
    return snapshot


def standalone_google_auth_succeeded(handle, settle_seconds: float = 1.35):
    """Detect a real Google-session cookie change and require it to settle."""
    if not isinstance(handle, dict):
        return False
    profile = str(handle.get("profile") or "")
    if not profile:
        return False

    baseline = handle.get("google_auth_cookie_baseline") or {}
    current = _snapshot_google_auth_cookie_state(profile)
    if not current:
        handle["google_auth_cookie_change_at"] = None
        return False

    changed = any(
        baseline.get(key) != value
        for key, value in current.items()
        if key[1] in _GOOGLE_AUTH_COOKIE_NAMES
    )
    if not changed:
        handle["google_auth_cookie_change_at"] = None
        return False

    now = time.monotonic()
    changed_at = handle.get("google_auth_cookie_change_at")
    last_snapshot = handle.get("google_auth_cookie_last_snapshot")
    if last_snapshot != current:
        handle["google_auth_cookie_last_snapshot"] = dict(current)
        handle["google_auth_cookie_change_at"] = now
        return False
    if changed_at is None:
        handle["google_auth_cookie_change_at"] = now
        return False
    return (now - float(changed_at)) >= max(0.8, float(settle_seconds))


def close_standalone_auth_chromium(handle):
    """Request a normal WM_CLOSE for the standalone auth browser window."""
    if not isinstance(handle, dict) or os.name != "nt":
        return False
    pids = {
        int(pid) for pid in (handle.get("browser_pids") or [])
        if int(pid or 0) > 0
    }
    launch_pid = int(handle.get("launch_pid") or 0)
    if launch_pid:
        pids.add(launch_pid)
    if not pids:
        return False

    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        WM_CLOSE = 0x0010
        GW_OWNER = 4
        closed = []

        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.PostMessageW.restype = wintypes.BOOL

        @EnumWindowsProc
        def callback(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids:
                return True
            if user32.GetWindow(hwnd, GW_OWNER):
                return True
            if user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
                closed.append(int(hwnd))
            return True

        user32.EnumWindows(callback, 0)
        if closed:
            handle["auto_close_requested"] = True
            handle["auto_close_requested_at"] = time.monotonic()
            return True
    except Exception:
        return False
    return False


'''

engine = replace_once(
    engine,
    "def _standalone_auth_window_geometry():\n",
    auth_cookie_helpers + "def _standalone_auth_window_geometry():\n",
    "Google auth cookie helper anchor",
)

# Capture baseline after embedded Chromium has fully released the shared profile,
# immediately before launching the standalone auth browser.
old_baseline_anchor = '''        _clear_devtools_active_port(profile)
        _clear_chromium_profile_locks(profile)

        x, y, width, height = _standalone_auth_window_geometry()
'''
new_baseline_anchor = '''        _clear_devtools_active_port(profile)
        _clear_chromium_profile_locks(profile)
        google_auth_cookie_baseline = _snapshot_google_auth_cookie_state(profile)

        x, y, width, height = _standalone_auth_window_geometry()
'''
engine = replace_once(
    engine, old_baseline_anchor, new_baseline_anchor, "auth cookie baseline"
)

old_return = '''            "window_geometry": (x, y, width, height),
            "command_flags": [arg for arg in command[1:] if str(arg).startswith("--")],
            "remote_debugging": False,
'''
new_return = '''            "window_geometry": (x, y, width, height),
            "google_auth_cookie_baseline": dict(google_auth_cookie_baseline),
            "google_auth_cookie_last_snapshot": dict(google_auth_cookie_baseline),
            "google_auth_cookie_change_at": None,
            "auto_close_requested": False,
            "command_flags": [arg for arg in command[1:] if str(arg).startswith("--")],
            "remote_debugging": False,
'''
engine = replace_once(engine, old_return, new_return, "auth handle cookie state")
write("engine/net.py", engine)

# ---- main.py -------------------------------------------------------------
main = read("main.py")
main = main.replace('BROWSER_VERSION = "10.5.60"', 'BROWSER_VERSION = "10.5.61"', 1)

main = replace_once(
    main,
    '''    standalone_auth_chromium_running, wait_for_standalone_auth_chromium_release,
)
''',
    '''    standalone_auth_chromium_running, wait_for_standalone_auth_chromium_release,
    standalone_google_auth_succeeded, close_standalone_auth_chromium,
)
''',
    "Google auth success imports",
)

main = replace_once(
    main,
    '''        self._google_auth_release_future = None
        self._google_auth_handle = None
''',
    '''        self._google_auth_release_future = None
        self._google_auth_success_future = None
        self._google_auth_close_future = None
        self._google_auth_handle = None
''',
    "Google auth success state",
)

old_poll = '''    def _poll_google_auth_window(self):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        handle = getattr(self, "_google_auth_handle", None) or {}
        try:
            running = bool(standalone_auth_chromium_running(handle))
        except Exception:
            running = False
        if running:
            self.root.after(250, self._poll_google_auth_window)
            return

        # Do not relaunch embedded Chromium until the standalone browser has
        # flushed cookies/storage and released its profile singleton files.
        try:
            self._google_auth_release_future = self._executor.submit(
                wait_for_standalone_auth_chromium_release, handle, 6.0
            )
        except Exception:
            self._google_auth_release_future = None
            self.root.after(500, self._poll_google_auth_window)
            return
        self.root.after(40, self._poll_google_auth_profile_release)
'''

new_poll = '''    def _poll_google_auth_window(self):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        handle = getattr(self, "_google_auth_handle", None) or {}
        try:
            running = bool(standalone_auth_chromium_running(handle))
        except Exception:
            running = False

        if running:
            # Check the shared profile off the Tk thread. A successful Google
            # login updates one or more authentication cookies. Once that
            # change is stable, close the standalone window gracefully.
            if not bool(handle.get("auto_close_requested")):
                future = getattr(self, "_google_auth_success_future", None)
                if future is None:
                    try:
                        self._google_auth_success_future = self._executor.submit(
                            standalone_google_auth_succeeded, handle, 1.35
                        )
                    except Exception:
                        self._google_auth_success_future = None
                elif future.done():
                    self._google_auth_success_future = None
                    try:
                        succeeded = bool(future.result())
                    except Exception:
                        succeeded = False
                    if succeeded:
                        self.status_var.set(
                            "Google sign-in successful; closing authentication window…"
                        )
                        try:
                            self._google_auth_close_future = self._executor.submit(
                                close_standalone_auth_chromium, handle
                            )
                        except Exception:
                            self._google_auth_close_future = None
            self.root.after(220, self._poll_google_auth_window)
            return

        self._google_auth_success_future = None
        self._google_auth_close_future = None

        # Do not relaunch embedded Chromium until the standalone browser has
        # flushed cookies/storage and released its profile singleton files.
        try:
            self._google_auth_release_future = self._executor.submit(
                wait_for_standalone_auth_chromium_release, handle, 6.0
            )
        except Exception:
            self._google_auth_release_future = None
            self.root.after(500, self._poll_google_auth_window)
            return
        self.root.after(40, self._poll_google_auth_profile_release)
'''
main = replace_once(main, old_poll, new_poll, "Google auth auto-close polling")

main = replace_once(
    main,
    '''        self._google_auth_launch_future = None
        self._google_auth_release_future = None
        return_url = str(getattr(self, "_google_auth_return_url", "") or "")
''',
    '''        self._google_auth_launch_future = None
        self._google_auth_release_future = None
        self._google_auth_success_future = None
        self._google_auth_close_future = None
        return_url = str(getattr(self, "_google_auth_return_url", "") or "")
''',
    "Google auth auto-close cleanup",
)

write("main.py", main)

# ---- metadata ------------------------------------------------------------
manifest = json.loads(read("chromium_zoom_extension/manifest.json"))
manifest["version"] = "10.5.61"
write("chromium_zoom_extension/manifest.json", json.dumps(manifest, indent=2) + "\n")

installer = read("installer/TekziteBrowser.iss")
installer = re.sub(r'#define MyAppVersion "10\.5\.\d+"', '#define MyAppVersion "10.5.61"', installer, count=1)
write("installer/TekziteBrowser.iss", installer)

app_manifest = read("tekzite_browser.manifest")
app_manifest = re.sub(
    r'assemblyIdentity version="10\.5\.\d+\.0"',
    'assemblyIdentity version="10.5.61.0"',
    app_manifest,
    count=1,
)
write("tekzite_browser.manifest", app_manifest)

version_info = read("tekzite_version_info.txt")
version_info = version_info.replace("10.5.60", "10.5.61")
version_info = re.sub(r'filevers=\(10,\s*5,\s*\d+,\s*0\)', 'filevers=(10, 5, 61, 0)', version_info, count=1)
version_info = re.sub(r'prodvers=\(10,\s*5,\s*\d+,\s*0\)', 'prodvers=(10, 5, 61, 0)', version_info, count=1)
write("tekzite_version_info.txt", version_info)

print("Applied Tekzite Browser v10.5.61 successful Google auth auto-close")
