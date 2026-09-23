from __future__ import annotations

import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / ".build" / "apply-v10.5.59.py"), run_name="__main__")

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

detach = r'''def detach_embedded_chromium_dwm_thumbnail():
    """Synchronously unregister Tekzite's DWM thumbnail without killing Chromium."""
    session = _EDGE_SESSION
    if not session or os.name != "nt":
        return False
    thumb = session.get("dwm_thumbnail_handle")
    if not thumb:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwmapi.DwmUnregisterThumbnail.argtypes = [wintypes.HANDLE]
        dwmapi.DwmUnregisterThumbnail.restype = HRESULT
        dwmapi.DwmUnregisterThumbnail(wintypes.HANDLE(_hwnd_int(thumb)))
    except Exception:
        pass
    session["dwm_thumbnail_handle"] = None
    session["dwm_thumbnail_registered"] = False
    session["dwm_thumbnail_source"] = None
    session["dwm_thumbnail_destination"] = None
    session["dwm_thumbnail_visible"] = False
    return True


'''
engine = replace_once(
    engine,
    "def request_embedded_chromium_dwm_recrop():\n",
    detach + "def request_embedded_chromium_dwm_recrop():\n",
    "DWM detach helper anchor",
)
write("engine/net.py", engine)

# ---- main.py -------------------------------------------------------------
main = read("main.py")
main = main.replace('BROWSER_VERSION = "10.5.59"', 'BROWSER_VERSION = "10.5.60"', 1)

main = replace_once(
    main,
    '''    request_embedded_chromium_dwm_recrop, request_embedded_chromium_dwm_reregister, network_engine_debug, privacy_stats,
''',
    '''    request_embedded_chromium_dwm_recrop, request_embedded_chromium_dwm_reregister, detach_embedded_chromium_dwm_thumbnail, network_engine_debug, privacy_stats,
''',
    "DWM detach import",
)

suspend_methods = r'''    def _suspend_chromium_for_external_auth(self):
        """Quiesce every Chromium/DWM callback before the helper process is retired."""
        self._navigation_generation += 1
        self._chromium_frame_generation += 1
        self._cancel_pending_tab_switch()
        self._stop_dwm_keyboard_poll()
        self._chromium_page_keyboard_active = False
        try:
            self._cancel_embedded_surface_wakes()
        except Exception:
            pass

        # Cancel Chromium-only Tk callbacks that could otherwise fire against
        # the just-retired renderer/source HWND.
        for attr in (
            "_dwm_pointer_after_id",
            "_dwm_geometry_after_id",
            "_dwm_reveal_after_id",
            "_dwm_restore_recovery_after_id",
            "_chromium_viewport_after_id",
            "_chromium_motion_after_id",
            "_chromium_drag_after_id",
            "_chromium_wheel_after_id",
        ):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
                try:
                    setattr(self, attr, None)
                except Exception:
                    pass

        # Unregister the DWM thumbnail while its source HWND is still alive,
        # then destroy the transient destination HWND on the Tk/UI thread.
        try:
            detach_embedded_chromium_dwm_thumbnail()
        except Exception:
            pass
        try:
            self._show_native_canvas()
        except Exception:
            self._embedded_mode = False
            self._chromium_software_mode = False
            self._chromium_dwm_mode = False
        try:
            self._destroy_dwm_host_for_taskbar()
        except Exception:
            pass

        self._dwm_surface_ready = False
        self._dwm_reveal_pending = False
        self._dwm_host_visible = False
        self._dwm_pending_resize = False
        self._chromium_frame_target_id = None
        self._chromium_pending_motion = None
        self._chromium_pending_wheel = None
        self._chromium_pending_drag = None
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        return True

    def _launch_google_auth_worker(self, launch_url):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        try:
            self._google_auth_launch_future = self._executor.submit(
                start_standalone_auth_chromium, launch_url
            )
        except Exception as exc:
            self._google_auth_handoff_active = False
            self.status_var.set(f"Could not open Google sign-in window: {exc}")
            return
        self.root.after(40, self._poll_google_auth_launch)

'''

main = replace_once(
    main,
    "    def _maybe_start_google_auth_handoff(self, url, previous_url=\"\", tab=None):\n",
    suspend_methods + "    def _maybe_start_google_auth_handoff(self, url, previous_url=\"\", tab=None):\n",
    "auth suspension methods anchor",
)

old = '''        self._cancel_pending_tab_switch()
        self._navigation_generation += 1
        self._stop_dwm_keyboard_poll()
        self._chromium_page_keyboard_active = False

        for item in self.tabs:
'''
new = '''        self._suspend_chromium_for_external_auth()

        for item in self.tabs:
'''
main = replace_once(main, old, new, "auth quiesce block")

old_launch = '''        self._show_native_canvas()
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
'''
new_launch = '''        self._paint_google_auth_handoff()
        self.status_var.set("Google sign-in: complete authentication in the Chromium window, then close it")
        self._refresh_tab_strip()

        # Let Tk finish destroying/hiding every native DWM surface before the
        # worker terminates Chromium. This avoids a source-HWND teardown racing
        # callbacks still running on the UI thread.
        try:
            self.root.after(90, self._launch_google_auth_worker, launch_url)
        except Exception:
            self._launch_google_auth_worker(launch_url)
        return True
'''
main = replace_once(main, old_launch, new_launch, "deferred auth launch")

write("main.py", main)

# ---- metadata ------------------------------------------------------------
manifest = json.loads(read("chromium_zoom_extension/manifest.json"))
manifest["version"] = "10.5.60"
write("chromium_zoom_extension/manifest.json", json.dumps(manifest, indent=2) + "\n")

installer = read("installer/TekziteBrowser.iss")
installer = re.sub(r'#define MyAppVersion "10\.5\.\d+"', '#define MyAppVersion "10.5.60"', installer, count=1)
write("installer/TekziteBrowser.iss", installer)

app_manifest = read("tekzite_browser.manifest")
app_manifest = re.sub(r'assemblyIdentity version="10\.5\.\d+\.0"', 'assemblyIdentity version="10.5.60.0"', app_manifest, count=1)
write("tekzite_browser.manifest", app_manifest)

version_info = read("tekzite_version_info.txt")
version_info = version_info.replace("10.5.59", "10.5.60")
version_info = re.sub(r'filevers=\(10,\s*5,\s*\d+,\s*0\)', 'filevers=(10, 5, 60, 0)', version_info, count=1)
version_info = re.sub(r'prodvers=\(10,\s*5,\s*\d+,\s*0\)', 'prodvers=(10, 5, 60, 0)', version_info, count=1)
write("tekzite_version_info.txt", version_info)

print("Applied Tekzite Browser v10.5.60 auth handoff teardown stabilization")
