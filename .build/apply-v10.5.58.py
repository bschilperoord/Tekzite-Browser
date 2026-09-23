from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / ".build" / "apply-v10.5.57.py"), run_name="__main__")

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"Could not find {label}")
    return text.replace(old, new, 1)

# ---- main.py -------------------------------------------------------------
main = read("main.py")
main = main.replace('BROWSER_VERSION = "10.5.57"', 'BROWSER_VERSION = "10.5.58"', 1)

main = replace_once(
    main,
    '''        self.root = tk.Tk()
        self._apply_app_icon()
        self.preferences = load_preferences()
''',
    '''        self.root = tk.Tk()
        self._apply_app_icon()
        self._taskbar_presence_guard_after_id = None
        try:
            self._taskbar_presence_guard_after_id = self.root.after(250, self._taskbar_presence_guard)
        except Exception:
            pass
        self._google_auth_handoff_active = False
        self._google_auth_launch_future = None
        self._google_auth_handle = None
        self._google_auth_return_url = None
        self._google_auth_source_url = None
        self.preferences = load_preferences()
''',
    "root identity/auth state block",
)

main = replace_once(
    main,
    '''    cleanup_abandoned_temporary_profiles, remove_profile_tree,
)
''',
    '''    cleanup_abandoned_temporary_profiles, remove_profile_tree,
    start_standalone_auth_chromium,
)
''',
    "standalone auth import",
)

auth_methods = r'''    @staticmethod
    def _is_google_auth_url(url):
        try:
            parts = urlsplit(str(url or ""))
            host = (parts.hostname or "").lower()
            path = (parts.path or "").lower()
            return host == "accounts.google.com" and any(
                token in path for token in ("signin", "servicelogin", "oauth", "login")
            )
        except Exception:
            return False

    @staticmethod
    def _google_auth_handoff_urls(url, previous_url=""):
        """Return (standalone launch URL, Tekzite return URL)."""
        source = str(url or "").strip()
        launch_url = source
        return_url = str(previous_url or "").strip()
        try:
            parts = urlsplit(source)
            params = dict(parse_qsl(parts.query, keep_blank_values=True))
            continue_url = str(params.get("continue") or "").strip()
            if "rejected" in (parts.path or "").lower() and continue_url:
                cp = urlsplit(continue_url)
                if cp.scheme.lower() in {"http", "https"} and cp.hostname:
                    launch_url = continue_url
            if (not return_url) or BrowserApp._is_google_auth_url(return_url):
                candidate = continue_url
                if candidate:
                    cp = urlsplit(candidate)
                    nested = dict(parse_qsl(cp.query, keep_blank_values=True))
                    next_url = str(nested.get("next") or "").strip()
                    np = urlsplit(next_url)
                    if np.scheme.lower() in {"http", "https"} and np.hostname:
                        return_url = next_url
                    elif cp.scheme.lower() in {"http", "https"} and cp.hostname:
                        return_url = candidate
            rp = urlsplit(return_url)
            if rp.scheme.lower() not in {"http", "https"} or not rp.hostname:
                return_url = "https://www.google.com/"
        except Exception:
            if not return_url:
                return_url = "https://www.google.com/"
        return launch_url, return_url

    def _paint_google_auth_handoff(self):
        try:
            self.canvas.delete("all")
            self.canvas.configure(bg=self.ui["bg"])
            width = max(600, int(self.content_frame.winfo_width() or 900))
            self.canvas.create_text(
                width // 2, 115,
                anchor="n",
                text="Google sign-in opened in a normal Chromium window",
                width=max(460, width - 180),
                justify="center",
                fill=self.ui["text"],
                font=(self._ui_font_family, self._font_size(18), "bold"),
            )
            self.canvas.create_text(
                width // 2, 175,
                anchor="n",
                text=(
                    "Complete the sign-in there, then close that Chromium window.\n"
                    "Tekzite will reopen this tab with the same profile and cookies."
                ),
                width=max(440, width - 220),
                justify="center",
                fill=self.ui["muted"],
                font=(self._ui_font_family, self._font_size(11)),
            )
        except Exception:
            pass

    def _maybe_start_google_auth_handoff(self, url, previous_url="", tab=None):
        if os.name != "nt" or getattr(self, "_google_auth_handoff_active", False):
            return False
        if not self._is_google_auth_url(url):
            return False
        tab = tab or self._active_tab()
        if tab is None or tab.get("id") != self.active_tab_id:
            return False

        launch_url, return_url = self._google_auth_handoff_urls(url, previous_url)
        self._google_auth_handoff_active = True
        self._google_auth_return_url = return_url
        self._google_auth_source_url = str(url or "")
        self._cancel_pending_tab_switch()
        self._navigation_generation += 1
        self._stop_dwm_keyboard_poll()
        self._chromium_page_keyboard_active = False

        for item in self.tabs:
            item["chromium_target_id"] = None
            item["loaded"] = False
            item["loading"] = False
            item["ready_state"] = ""
            item.pop("presentation", None)
            if item.get("id") != self.active_tab_id:
                item["sleeping"] = True
                item["restore_pending"] = bool(item.get("url"))
        tab["sleeping"] = False
        tab["restore_pending"] = False

        try:
            if self._closed_target_retire_after_id is not None:
                self.root.after_cancel(self._closed_target_retire_after_id)
        except Exception:
            pass
        self._closed_target_retire_after_id = None
        self._closed_target_retire_queue.clear()
        self._page_state_inflight.clear()

        self._show_native_canvas()
        self._paint_google_auth_handoff()
        self.status_var.set("Google sign-in: complete authentication in the Chromium window, then close it")
        self._refresh_tab_strip()
        try:
            self._google_auth_launch_future = self._executor.submit(
                start_standalone_auth_chromium, launch_url
            )
        except Exception as exc:
            self._google_auth_handoff_active = False
            self.status_var.set(f"Could not open Google sign-in window: {exc}")
            return False
        self.root.after(40, self._poll_google_auth_launch)
        return True

    def _poll_google_auth_launch(self):
        future = getattr(self, "_google_auth_launch_future", None)
        if not getattr(self, "_google_auth_handoff_active", False) or future is None:
            return
        if not future.done():
            self.root.after(40, self._poll_google_auth_launch)
            return
        self._google_auth_launch_future = None
        try:
            self._google_auth_handle = future.result()
        except Exception as exc:
            self._google_auth_handoff_active = False
            self._google_auth_handle = None
            self.status_var.set(f"Google sign-in handoff failed: {exc}")
            return
        self.status_var.set("Google sign-in window is open; close it when authentication is finished")
        self.root.after(220, self._poll_google_auth_window)

    def _poll_google_auth_window(self):
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

    def _finish_google_auth_handoff(self, browser_closed=True):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        self._google_auth_handoff_active = False
        self._google_auth_handle = None
        self._google_auth_launch_future = None
        return_url = str(getattr(self, "_google_auth_return_url", "") or "")
        self._google_auth_return_url = None
        self._google_auth_source_url = None
        tab = self._active_tab()
        if tab is None:
            return
        if return_url:
            tab["url"] = return_url
            tab["title"] = self._tab_title_for_url(return_url)
            tab["loaded"] = False
            tab["loading"] = False
            tab["sleeping"] = False
            tab["restore_pending"] = False
            self.url_var.set(return_url)
            self._refresh_tab_strip()
            self.status_var.set("Returning from Google sign-in…")
            self.navigate_to(return_url, add_history=False, reuse_existing=False)
        else:
            self.status_var.set("Google sign-in window closed")

'''

main = replace_once(
    main,
    "    def _poll_one_tab_state(self, tab_id, target_id, include_favicon=False):\n",
    auth_methods + "    def _poll_one_tab_state(self, tab_id, target_id, include_favicon=False):\n",
    "Google auth methods anchor",
)

main = replace_once(
    main,
    '''            live_url = str(info.get("url") or "").strip()
            if live_url and live_url != "about:blank" and live_url != tab.get("url"):
                tab["url"] = live_url
                if tab.get("id") == self.active_tab_id and not self._address_focus_active:
                    self.url_var.set(live_url)
                changed = True
''',
    '''            live_url = str(info.get("url") or "").strip()
            if live_url and live_url != "about:blank" and live_url != tab.get("url"):
                previous_url = str(tab.get("url") or "")
                if self._maybe_start_google_auth_handoff(live_url, previous_url, tab):
                    return
                tab["url"] = live_url
                if tab.get("id") == self.active_tab_id and not self._address_focus_active:
                    self.url_var.set(live_url)
                changed = True
''',
    "live Google auth redirect hook",
)

main = replace_once(
    main,
    '''        active = self._active_tab()
        if reuse_existing and self.preferences.get("reuse_open_tabs", True):
''',
    '''        active = self._active_tab()
        previous_url = str(active.get("url") or "") if active is not None else ""
        if self._maybe_start_google_auth_handoff(url, previous_url, active):
            return
        if reuse_existing and self.preferences.get("reuse_open_tabs", True):
''',
    "direct Google auth navigation hook",
)
write("main.py", main)

# ---- engine/net.py -------------------------------------------------------
engine = read("engine/net.py")
auth_helper = r'''def start_standalone_auth_chromium(url: str):
    """Launch a normal Chromium window with Tekzite's profile for authentication.

    This handoff deliberately has no remote-debugging port, no CDP control,
    no --app mode and no command-line Tekzite extension injection.
    """
    if os.name != "nt":
        raise RuntimeError("Standalone authentication handoff is currently implemented for Windows")
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
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            if not _profile_chromium_pids(profile):
                break
            time.sleep(0.05)
        if _profile_chromium_pids(profile):
            _terminate_profile_chromium_processes(profile)
        _clear_devtools_active_port(profile)
        _clear_chromium_profile_locks(profile)

        command = [
            executable,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
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
        return {
            "process": process,
            "pid": int(process.pid),
            "profile": profile,
            "executable": executable,
            "url": target_url,
            "command_flags": [arg for arg in command[1:] if str(arg).startswith("--")],
            "remote_debugging": False,
            "cdp_control": False,
        }


'''
engine = replace_once(
    engine,
    "def _pick_devtools_page(port, session=None, target_id=None):\n",
    auth_helper + "def _pick_devtools_page(port, session=None, target_id=None):\n",
    "standalone auth engine anchor",
)
write("engine/net.py", engine)

# ---- release metadata ---------------------------------------------------
manifest = json.loads(read("chromium_zoom_extension/manifest.json"))
manifest["version"] = "10.5.58"
write("chromium_zoom_extension/manifest.json", json.dumps(manifest, indent=2) + "\n")

installer = read("installer/TekziteBrowser.iss")
installer = re.sub(r'#define MyAppVersion "10\.5\.\d+"', '#define MyAppVersion "10.5.58"', installer, count=1)
write("installer/TekziteBrowser.iss", installer)

app_manifest = read("tekzite_browser.manifest")
app_manifest = re.sub(r'assemblyIdentity version="10\.5\.\d+\.0"', 'assemblyIdentity version="10.5.58.0"', app_manifest, count=1)
write("tekzite_browser.manifest", app_manifest)

version_info = read("tekzite_version_info.txt")
version_info = re.sub(r'filevers=\(10,\s*5,\s*\d+,\s*0\)', 'filevers=(10, 5, 58, 0)', version_info, count=1)
version_info = re.sub(r'prodvers=\(10,\s*5,\s*\d+,\s*0\)', 'prodvers=(10, 5, 58, 0)', version_info, count=1)
version_info = re.sub(r"StringStruct\(u'FileVersion', u'10\.5\.\d+'\)", "StringStruct(u'FileVersion', u'10.5.58')", version_info, count=1)
version_info = re.sub(r"StringStruct\(u'ProductVersion', u'10\.5\.\d+'\)", "StringStruct(u'ProductVersion', u'10.5.58')", version_info, count=1)
write("tekzite_version_info.txt", version_info)

print("Applied Tekzite Browser v10.5.58 Google authentication handoff")
