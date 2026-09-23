from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Could not find {label}")
    return text.replace(old, new, 1)


main = read("main.py")

helpers = '''def _set_windows_app_user_model_id():
    """Give Tekzite its own Windows taskbar/application identity before Tk maps."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        app_id = "Tekzite.Browser"
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
        return int(shell32.SetCurrentProcessExplicitAppUserModelID(app_id)) == 0
    except Exception:
        return False


def _resource_root():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base)
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            pass
    return Path(__file__).resolve().parent


def _asset_path(*parts):
    candidates = []
    primary = _resource_root()
    candidates.append(primary.joinpath(*parts))
    try:
        executable_root = Path(sys.executable).resolve().parent
        candidate = executable_root.joinpath(*parts)
        if candidate not in candidates:
            candidates.append(candidate)
    except Exception:
        pass
    script_root = Path(__file__).resolve().parent
    candidate = script_root.joinpath(*parts)
    if candidate not in candidates:
        candidates.append(candidate)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


'''
if "def _set_windows_app_user_model_id():" not in main:
    main = replace_once(main, "def _preferences_path():\n", helpers + "def _preferences_path():\n", "preferences helper anchor")

main = re.sub(r'BROWSER_VERSION = "10\.5\.\d+"', 'BROWSER_VERSION = "10.5.56"', main, count=1)

methods = '''    def _native_root_hwnd(self):
        if sys.platform != "win32":
            return 0
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            self.root.update_idletasks()
            inner = wintypes.HWND(int(self.root.winfo_id()))
            GA_ROOT = 2
            try:
                user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetAncestor.restype = wintypes.HWND
                hwnd = int(user32.GetAncestor(inner, GA_ROOT) or 0)
            except Exception:
                hwnd = 0
            if not hwnd:
                hwnd = int(user32.GetParent(inner) or int(inner.value or 0))
            return hwnd
        except Exception:
            return 0

    def _apply_native_windows_icon(self):
        """Force Tekzite's icon onto the actual frameless Win32 wrapper HWND."""
        if sys.platform != "win32":
            return False
        icon_ico = _asset_path("assets", "tekzite.ico")
        if not icon_ico.is_file():
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = int(self._native_root_hwnd() or 0)
            if not hwnd:
                return False
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = wintypes.LRESULT
            big = user32.LoadImageW(None, str(icon_ico), IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
            small = user32.LoadImageW(None, str(icon_ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if not big:
                big = user32.LoadImageW(None, str(icon_ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if not small:
                small = user32.LoadImageW(None, str(icon_ico), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            self._native_icon_handles = tuple(int(h) for h in (big, small) if h)
            if big:
                user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_BIG, int(big))
            if small:
                user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_SMALL, int(small))
            return bool(big or small)
        except Exception:
            return False

    def _apply_app_icon(self):
        """Apply the bundled Tekzite icon to Tk and the native Windows wrapper."""
        self._app_icon_photo = None
        self._native_icon_handles = ()
        icon_png = _asset_path("assets", "tekzite.png")
        icon_ico = _asset_path("assets", "tekzite.ico")
        if os.name == "nt":
            try:
                if icon_ico.is_file():
                    self.root.iconbitmap(default=str(icon_ico))
            except Exception:
                pass
        try:
            if icon_png.is_file():
                self._app_icon_photo = tk.PhotoImage(file=str(icon_png))
                self.root.iconphoto(True, self._app_icon_photo)
        except Exception:
            self._app_icon_photo = None
        if sys.platform == "win32":
            try:
                self.root.after(1, self._apply_native_windows_icon)
                self.root.after(40, self._apply_native_windows_icon)
            except Exception:
                pass

'''
if "    def _native_root_hwnd(self):" not in main:
    main = replace_once(main, "    def __init__(self):\n", methods + "    def __init__(self):\n", "BrowserApp init anchor")

old_root = '''        self._dpi_awareness_enabled = _enable_per_monitor_dpi_awareness()\n        self.root = tk.Tk()\n        self.preferences = load_preferences()\n'''
new_root = '''        self._dpi_awareness_enabled = _enable_per_monitor_dpi_awareness()\n        self._windows_app_user_model_id_set = _set_windows_app_user_model_id()\n        self.root = tk.Tk()\n        self._apply_app_icon()\n        self.preferences = load_preferences()\n'''
if "self._windows_app_user_model_id_set" not in main:
    main = replace_once(main, old_root, new_root, "Tk root creation block")

style_start = main.index("    def _apply_frameless_app_style(self):")
style_end = main.index("    def _make_window_control(", style_start)
style_block = '''    def _apply_frameless_app_style(self):
        """Keep Tekzite's real top-level Win32 wrapper permanently taskbar-eligible."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            self.root.update_idletasks()
            hwnd = int(self._current_native_root_hwnd() or self._native_root_hwnd() or 0)
            if not hwnd:
                return False

            GWL_EXSTYLE = -20
            GWLP_HWNDPARENT = -8
            GW_OWNER = 4
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = ctypes.c_long
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            set_long.restype = ctypes.c_long

            user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetWindow.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            changed = False
            exstyle = int(get_long(wintypes.HWND(hwnd), GWL_EXSTYLE)) & 0xFFFFFFFF
            wanted = (exstyle & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if wanted != exstyle:
                set_long(wintypes.HWND(hwnd), GWL_EXSTYLE, ctypes.c_long(wanted).value)
                changed = True

            # An owned top-level window can disappear from the taskbar even when
            # WS_EX_APPWINDOW is set. The real Tekzite root must stay unowned.
            owner = int(user32.GetWindow(wintypes.HWND(hwnd), GW_OWNER) or 0)
            if owner:
                set_owner = getattr(user32, "SetWindowLongPtrW", None)
                if set_owner is not None:
                    set_owner.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                    set_owner.restype = ctypes.c_void_p
                    set_owner(wintypes.HWND(hwnd), GWLP_HWNDPARENT, None)
                else:
                    user32.SetWindowLongW(wintypes.HWND(hwnd), GWLP_HWNDPARENT, 0)
                changed = True

            wrapper_changed = int(getattr(self, "_taskbar_identity_hwnd", 0) or 0) != hwnd
            if changed or wrapper_changed:
                self._taskbar_identity_hwnd = hwnd
                user32.SetWindowPos(
                    wintypes.HWND(hwnd), wintypes.HWND(0),
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                    SWP_NOACTIVATE | SWP_FRAMECHANGED,
                )
                self._window_rounding_signature = None
                self._apply_window_rounding()
                self._apply_native_windows_icon()
            return True
        except Exception:
            return False

    def _schedule_taskbar_presence_guard(self, delay=1200):
        """Continuously verify taskbar identity without changing window visibility."""
        if sys.platform != "win32":
            return
        previous = getattr(self, "_taskbar_presence_guard_after_id", None)
        if previous is not None:
            try:
                self.root.after_cancel(previous)
            except Exception:
                pass
        try:
            self._taskbar_presence_guard_after_id = self.root.after(
                max(250, int(delay)), self._taskbar_presence_guard
            )
        except Exception:
            self._taskbar_presence_guard_after_id = None

    def _taskbar_presence_guard(self):
        self._taskbar_presence_guard_after_id = None
        try:
            if not bool(self.root.winfo_exists()):
                return
            # Apply to normal, maximized and minimized roots. This does not call
            # deiconify or ShowWindow, so a minimized browser stays minimized.
            self._apply_frameless_app_style()
        except Exception:
            pass
        self._schedule_taskbar_presence_guard(1200)

'''
main = main[:style_start] + style_block + main[style_end:]

minimize_old = '''        try:
            self.root.overrideredirect(False)
            self.root.iconify()
'''
minimize_new = '''        try:
            self.root.overrideredirect(False)
            self.root.update_idletasks()
            # override-redirect(False) can create a fresh Tk wrapper. Mark that
            # wrapper as an app window before iconifying so the taskbar button
            # cannot vanish during the minimize transition.
            self._apply_frameless_app_style()
            self.root.iconify()
'''
main = replace_once(main, minimize_old, minimize_new, "taskbar-safe minimize transition")

write("main.py", main)

build = read("build_windows.ps1")
if 'assets_dir = project / "assets"' not in build:
    build = replace_once(
        build,
        '''extension_dir = project / "chromium_zoom_extension"\ndatas = []\nif extension_dir.is_dir():\n    datas.append((str(extension_dir), "chromium_zoom_extension"))\n''',
        '''extension_dir = project / "chromium_zoom_extension"\nassets_dir = project / "assets"\ndatas = []\nif extension_dir.is_dir():\n    datas.append((str(extension_dir), "chromium_zoom_extension"))\nif assets_dir.is_dir():\n    datas.append((str(assets_dir), "assets"))\n''',
        "PyInstaller datas block",
    )
write("build_windows.ps1", build)

manifest = json.loads(read("chromium_zoom_extension/manifest.json"))
manifest["version"] = "10.5.56"
write("chromium_zoom_extension/manifest.json", json.dumps(manifest, indent=2) + "\n")

installer = read("installer/TekziteBrowser.iss")
installer = re.sub(r'#define MyAppVersion "10\.5\.\d+"', '#define MyAppVersion "10.5.56"', installer, count=1)
write("installer/TekziteBrowser.iss", installer)

app_manifest = read("tekzite_browser.manifest")
app_manifest = re.sub(r'assemblyIdentity version="10\.5\.\d+\.0"', 'assemblyIdentity version="10.5.56.0"', app_manifest, count=1)
write("tekzite_browser.manifest", app_manifest)

version_info = read("tekzite_version_info.txt")
version_info = re.sub(r'filevers=\(10,\s*5,\s*\d+,\s*0\)', 'filevers=(10, 5, 56, 0)', version_info, count=1)
version_info = re.sub(r'prodvers=\(10,\s*5,\s*\d+,\s*0\)', 'prodvers=(10, 5, 56, 0)', version_info, count=1)
version_info = re.sub(r"StringStruct\(u'FileVersion', u'10\.5\.\d+'\)", "StringStruct(u'FileVersion', u'10.5.56')", version_info, count=1)
version_info = re.sub(r"StringStruct\(u'ProductVersion', u'10\.5\.\d+'\)", "StringStruct(u'ProductVersion', u'10.5.56')", version_info, count=1)
write("tekzite_version_info.txt", version_info)

write(
    "assets/README.txt",
    "Bundled Tekzite application icons:\n\n"
    "- tekzite.png  -> runtime Tk window icon source\n"
    "- tekzite.ico  -> Windows executable / installer icon\n\n"
    "The Windows build and installer both use these files automatically when present.\n",
)

print("Applied Tekzite Browser v10.5.56 native application identity/icon changes")
