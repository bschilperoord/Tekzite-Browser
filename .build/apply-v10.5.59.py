from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / ".build" / "apply-v10.5.58.py"), run_name="__main__")

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"Could not find {label}")
    return text.replace(old, new, 1)

# -------------------------------------------------------------------------
# engine/net.py: keep the standalone auth browser on-screen and track the
# actual profile-owning Chromium process rather than a short-lived launcher.
# -------------------------------------------------------------------------
engine = read("engine/net.py")

start = engine.index("def start_standalone_auth_chromium(url: str):")
end = engine.index("def _pick_devtools_page(port, session=None, target_id=None):", start)

replacement = r'''def _standalone_auth_window_geometry():
    """Return a centered, guaranteed-visible rectangle on the primary work area."""
    default = (80, 80, 1200, 820)
    if os.name != "nt":
        return default
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        SPI_GETWORKAREA = 0x0030
        if not ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        ):
            return default

        work_w = max(640, int(rect.right - rect.left))
        work_h = max(480, int(rect.bottom - rect.top))
        width = min(1280, max(900, work_w - 120))
        height = min(900, max(650, work_h - 120))
        width = min(width, work_w)
        height = min(height, work_h)
        x = int(rect.left + max(0, (work_w - width) // 2))
        y = int(rect.top + max(0, (work_h - height) // 2))
        return (x, y, width, height)
    except Exception:
        return default


def _force_standalone_auth_window_onscreen(pids, geometry):
    """Move Chromium's real top-level auth window into the visible work area."""
    if os.name != "nt":
        return False
    pid_set = {int(pid) for pid in (pids or []) if int(pid or 0) > 0}
    if not pid_set:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        GW_OWNER = 4
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        HWND_TOP = wintypes.HWND(0)
        x, y, width, height = map(int, geometry)
        moved = []

        @EnumWindowsProc
        def callback(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pid_set:
                return True
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, GW_OWNER):
                return True
            if user32.SetWindowPos(
                hwnd, HWND_TOP, x, y, width, height,
                SWP_NOACTIVATE | SWP_SHOWWINDOW,
            ):
                moved.append(int(hwnd))
            return True

        user32.EnumWindows(callback, 0)
        return bool(moved)
    except Exception:
        return False


def start_standalone_auth_chromium(url: str):
    """Launch a normal, visible Chromium window for authentication.

    The window shares Tekzite's persistent web profile but deliberately has no
    remote-debugging port, no CDP controller and no --app mode.  The returned
    handle tracks the actual profile-owning browser PID(s), so a launcher handoff
    cannot make Tekzite restart its embedded helper while auth is still open.
    """
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
        profile = str(session.get("profile") or _persistent_edge_profile_dir())
        if not executable:
            executable = next(iter(_chromium_candidates()), "")
        if not executable or not os.path.isfile(executable):
            raise RuntimeError("No Chromium executable is available for authentication")

        _close_embedded_chromium_unlocked(clear_profile=False)

        # Never let the old off-screen DWM helper still own this profile.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if not _profile_chromium_pids(profile):
                break
            time.sleep(0.05)
        if _profile_chromium_pids(profile):
            _terminate_profile_chromium_processes(profile)

        _clear_devtools_active_port(profile)
        _clear_chromium_profile_locks(profile)

        x, y, width, height = _standalone_auth_window_geometry()
        command = [
            executable,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
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

        # Chromium may keep this launcher as the browser process or hand the
        # command to another process. Wait for the stable profile owner(s).
        launched_at = time.monotonic()
        browser_pids = []
        stable_rounds = 0
        last_pids = []
        while time.monotonic() - launched_at < 4.0:
            current = sorted(set(_profile_chromium_pids(profile)))
            if current:
                if current == last_pids:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_pids = list(current)
                browser_pids = list(current)

                launcher_alive = process.poll() is None
                # If the launcher handed off, require the replacement PID list
                # to settle. If it stayed alive, a couple of stable samples are
                # enough to know the real browser PID.
                if stable_rounds >= (2 if launcher_alive else 3):
                    break
            elif process.poll() is not None and time.monotonic() - launched_at > 1.0:
                # Give a handoff a little time to publish the replacement process.
                pass
            time.sleep(0.10)

        if not browser_pids and process.poll() is None:
            browser_pids = [int(process.pid)]

        # Command-line geometry normally wins, but the shared profile remembers
        # Tekzite's historical -32000 DWM source placement. Force the actual
        # top-level window on-screen after Chromium has created it as well.
        for _ in range(8):
            if _force_standalone_auth_window_onscreen(browser_pids, (x, y, width, height)):
                break
            time.sleep(0.10)

        return {
            "process": process,
            "launch_pid": int(process.pid),
            "browser_pids": list(browser_pids),
            "profile": profile,
            "executable": executable,
            "url": target_url,
            "window_geometry": (x, y, width, height),
            "command_flags": [arg for arg in command[1:] if str(arg).startswith("--")],
            "remote_debugging": False,
            "cdp_control": False,
        }


def standalone_auth_chromium_running(handle):
    """Return True while the real auth browser, not merely its launcher, exists."""
    if not isinstance(handle, dict):
        return False

    pids = []
    for pid in handle.get("browser_pids") or []:
        try:
            if _pid_is_alive(int(pid)):
                pids.append(int(pid))
        except Exception:
            pass
    if pids:
        handle["browser_pids"] = pids
        return True

    process = handle.get("process")
    try:
        if process is not None and process.poll() is None:
            return True
    except Exception:
        pass

    return False


def wait_for_standalone_auth_chromium_release(handle, timeout: float = 6.0):
    """Wait for auth Chromium to release Tekzite's shared profile completely."""
    if not isinstance(handle, dict):
        return True

    profile = str(handle.get("profile") or "")
    deadline = time.monotonic() + max(1.0, float(timeout))
    while time.monotonic() < deadline:
        if standalone_auth_chromium_running(handle):
            time.sleep(0.08)
            continue
        if profile and _profile_chromium_pids(profile):
            time.sleep(0.08)
            continue
        # Chromium can exit a fraction before its singleton files disappear.
        if profile and _profile_recovery_needed(profile):
            time.sleep(0.08)
            continue
        return True

    # If no live browser owns the profile anymore, stale singleton crumbs are
    # safe to remove. Never delete them while a tracked process is alive.
    if profile and not _profile_chromium_pids(profile):
        _clear_chromium_profile_locks(profile)
        return not _profile_recovery_needed(profile)
    return False


'''

engine = engine[:start] + replacement + engine[end:]
write("engine/net.py", engine)

# -------------------------------------------------------------------------
# main.py: poll the real browser PID(s), then wait for profile release on a
# worker before restarting the embedded CDP/DWM browser.
# -------------------------------------------------------------------------
main = read("main.py")
main = main.replace('BROWSER_VERSION = "10.5.58"', 'BROWSER_VERSION = "10.5.59"', 1)

main = replace_once(
    main,
    '''    start_standalone_auth_chromium,
)
''',
    '''    start_standalone_auth_chromium,
    standalone_auth_chromium_running, wait_for_standalone_auth_chromium_release,
)
''',
    "standalone auth lifecycle imports",
)

main = replace_once(
    main,
    '''        self._google_auth_launch_future = None
        self._google_auth_handle = None
        self._google_auth_return_url = None
''',
    '''        self._google_auth_launch_future = None
        self._google_auth_release_future = None
        self._google_auth_handle = None
        self._google_auth_return_url = None
''',
    "Google auth release state",
)

old_poll = '''    def _poll_google_auth_window(self):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        handle = getattr(self, "_google_auth_handle", None) or {}
        process = handle.get("process") if isinstance(handle, dict) else None
        if process is None:
            self._finish_google_auth_handoff(False)
            return
        try:
            running = process.poll() is None
        except Exception:
            running = False
        if running:
            self.root.after(250, self._poll_google_auth_window)
            return
        self.root.after(260, self._finish_google_auth_handoff, True)

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

    def _poll_google_auth_profile_release(self):
        future = getattr(self, "_google_auth_release_future", None)
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        if future is None:
            self.root.after(250, self._poll_google_auth_window)
            return
        if not future.done():
            self.root.after(50, self._poll_google_auth_profile_release)
            return
        self._google_auth_release_future = None
        try:
            released = bool(future.result())
        except Exception:
            released = False
        if not released:
            self.status_var.set(
                "Google sign-in window is still releasing its profile; waiting…"
            )
            self.root.after(350, self._poll_google_auth_window)
            return
        self.root.after(80, self._finish_google_auth_handoff, True)

'''
main = replace_once(main, old_poll, new_poll, "Google auth process tracking")

main = replace_once(
    main,
    '''        self._google_auth_handle = None
        self._google_auth_launch_future = None
        return_url = str(getattr(self, "_google_auth_return_url", "") or "")
''',
    '''        self._google_auth_handle = None
        self._google_auth_launch_future = None
        self._google_auth_release_future = None
        return_url = str(getattr(self, "_google_auth_return_url", "") or "")
''',
    "Google auth release cleanup",
)

write("main.py", main)

# -------------------------------------------------------------------------
# Release metadata
# -------------------------------------------------------------------------
manifest = json.loads(read("chromium_zoom_extension/manifest.json"))
manifest["version"] = "10.5.59"
write("chromium_zoom_extension/manifest.json", json.dumps(manifest, indent=2) + "\n")

installer = read("installer/TekziteBrowser.iss")
installer = re.sub(r'#define MyAppVersion "10\\.5\\.\\d+"', '#define MyAppVersion "10.5.59"', installer, count=1)
write("installer/TekziteBrowser.iss", installer)

app_manifest = read("tekzite_browser.manifest")
app_manifest = re.sub(
    r'assemblyIdentity version="10\\.5\\.\\d+\\.0"',
    'assemblyIdentity version="10.5.59.0"',
    app_manifest,
    count=1,
)
write("tekzite_browser.manifest", app_manifest)

version_info = read("tekzite_version_info.txt")
version_info = re.sub(r'filevers=\\(10,\\s*5,\\s*\\d+,\\s*0\\)', 'filevers=(10, 5, 59, 0)', version_info, count=1)
version_info = re.sub(r'prodvers=\\(10,\\s*5,\\s*\\d+,\\s*0\\)', 'prodvers=(10, 5, 59, 0)', version_info, count=1)
version_info = re.sub(
    r"StringStruct\\(u'FileVersion', u'10\\.5\\.\\d+'\\)",
    "StringStruct(u'FileVersion', u'10.5.59')",
    version_info,
    count=1,
)
version_info = re.sub(
    r"StringStruct\\(u'ProductVersion', u'10\\.5\\.\\d+'\\)",
    "StringStruct(u'ProductVersion', u'10.5.59')",
    version_info,
    count=1,
)
write("tekzite_version_info.txt", version_info)

print("Applied Tekzite Browser v10.5.59 visible/stable Google auth handoff fix")
