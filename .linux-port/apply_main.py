from pathlib import Path

path = Path("main.py")
text = path.read_text(encoding="utf-8")

def swap(old, new, label):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    text = text.replace(old, new, 1)

swap(
    '''def _state_root_for_profile(profile=None):
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Tekzite Browser"
    profile = _profile_slug(profile or os.environ.get("TEKZITE_BROWSER_PROFILE") or "Default")
    return root if profile == "Default" else root / "Profiles" / profile''',
    '''def _state_root_for_profile(profile=None):
    """Return the platform-native persistent state root for one Tekzite profile."""
    # Preserve explicit LOCALAPPDATA overrides used by portable/test setups,
    # even when the source is being inspected on another host OS. Normal Linux
    # environments do not define it and therefore use XDG state paths below.
    if os.name == "nt" or os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Tekzite Browser"
        profiles_dir = "Profiles"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Tekzite Browser"
        profiles_dir = "Profiles"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
        root = base / "tekzite-browser"
        profiles_dir = "profiles"
    profile = _profile_slug(profile or os.environ.get("TEKZITE_BROWSER_PROFILE") or "Default")
    return root if profile == "Default" else root / profiles_dir / profile''',
    "platform state root",
)

swap(
    '''            automatic_ui_font = families.get("segoe ui variable text", families.get("segoe ui", "Segoe UI"))
            automatic_display_font = families.get("segoe ui variable display", automatic_ui_font)
            automatic_mono_font = families.get("cascadia mono", families.get("consolas", "Consolas"))''',
    '''            if os.name == "nt":
                automatic_ui_font = families.get("segoe ui variable text", families.get("segoe ui", "Segoe UI"))
                automatic_display_font = families.get("segoe ui variable display", automatic_ui_font)
                automatic_mono_font = families.get("cascadia mono", families.get("consolas", "Consolas"))
            else:
                try:
                    tk_default_family = str(tkfont.nametofont("TkDefaultFont").actual("family"))
                except Exception:
                    tk_default_family = "DejaVu Sans"
                automatic_ui_font = (families.get("noto sans") or families.get("inter") or
                                     families.get("dejavu sans") or tk_default_family)
                automatic_display_font = automatic_ui_font
                automatic_mono_font = (families.get("jetbrains mono") or families.get("noto sans mono") or
                                       families.get("dejavu sans mono") or "DejaVu Sans Mono")''',
    "Linux font selection",
)

swap(
    '        self.root.overrideredirect(True)',
    '''        # Windows uses Tekzite's custom frameless shell. Linux Preview keeps
        # the window-manager frame so taskbar/minimize/maximize behavior works
        # correctly on X11, XWayland and Wayland compositors.
        self.root.overrideredirect(os.name == "nt")''',
    "window manager frame",
)

swap(
    '''        self.edge_host.bind("<MouseWheel>", self._on_chromium_surface_wheel)
        self.edge_host.bind("<KeyPress>", self._on_chromium_surface_key)''',
    '''        self.edge_host.bind("<MouseWheel>", self._on_chromium_surface_wheel)
        if sys.platform.startswith("linux"):
            self.edge_host.bind("<Button-4>", self._on_chromium_surface_linux_wheel)
            self.edge_host.bind("<Button-5>", self._on_chromium_surface_linux_wheel)
        self.edge_host.bind("<KeyPress>", self._on_chromium_surface_key)''',
    "edge-host Linux wheel",
)

swap(
    '''        self.chromium_surface.bind("<MouseWheel>", self._on_chromium_surface_wheel)
        self.chromium_surface.bind("<KeyPress>", self._on_chromium_surface_key)''',
    '''        self.chromium_surface.bind("<MouseWheel>", self._on_chromium_surface_wheel)
        if sys.platform.startswith("linux"):
            self.chromium_surface.bind("<Button-4>", self._on_chromium_surface_linux_wheel)
            self.chromium_surface.bind("<Button-5>", self._on_chromium_surface_linux_wheel)
        self.chromium_surface.bind("<KeyPress>", self._on_chromium_surface_key)''',
    "surface Linux wheel",
)

swap(
    '''        mode = str(getattr(self, "preferences", DEFAULT_PREFERENCES).get(
            "chromium_presentation", "native"
        )).strip().lower()''',
    '''        # Linux Preview intentionally uses the existing CDP software compositor
        # as its primary renderer. Chromium itself runs headless, so this works
        # under X11, XWayland and native Wayland without unsafe cross-process
        # window reparenting. Windows keeps the user-selectable DWM/software path.
        if os.name != "nt":
            return True
        mode = str(getattr(self, "preferences", DEFAULT_PREFERENCES).get(
            "chromium_presentation", "native"
        )).strip().lower()''',
    "software renderer selection",
)

marker = '''    def _on_chromium_surface_wheel(self, event):
        if not self._chromium_input_surface_active():'''
replacement = '''    def _on_chromium_surface_linux_wheel(self, event):
        """Translate X11/XWayland Button-4/5 wheel events into Tk wheel deltas."""
        try:
            num = int(getattr(event, "num", 0) or 0)
        except Exception:
            num = 0
        if num not in (4, 5):
            return None
        try:
            event.delta = 120 if num == 4 else -120
        except Exception:
            pass
        return self._on_chromium_surface_wheel(event)

''' + marker
swap(marker, replacement, "Linux wheel handler")

swap(
    '        parent_hwnd = int(self._ensure_dwm_host())',
    '        parent_hwnd = int(self._ensure_dwm_host()) if not software_presentation else 0',
    "headless parent handle",
)

swap(
    '''    def _minimize_window(self):
        # Tk cannot iconify an override-redirect window directly on Windows.
        # Retire the transient DWM destination first, then temporarily expose a
        # normal Tk wrapper for the taskbar. v10.5.54 explicitly tracks the
        # entire round-trip so a transient withdrawn state cannot strand the app.
        self._suspend_dwm_host_for_minimize()''',
    '''    def _minimize_window(self):
        # Keep the historical ordering guarantee: if a DWM destination exists,
        # retire it before any iconify call. On Linux this is effectively a cheap
        # no-op cleanup before the native window manager handles minimization.
        self._suspend_dwm_host_for_minimize()
        if os.name != "nt":
            self._dwm_host_suspended_for_minimize = False
            try:
                self.root.iconify()
            except Exception:
                pass
            return
        # Tk cannot iconify an override-redirect window directly on Windows.
        # Retire the transient DWM destination first, then temporarily expose a
        # normal Tk wrapper for the taskbar. v10.5.54 explicitly tracks the
        # entire round-trip so a transient withdrawn state cannot strand the app.''',
    "Linux minimize",
)

swap(
    '''    def _apply_chromium_zoom(self, target_id=None):
        """Apply Chromium page zoom and keep DWM on a 1:1 presentation contract."""
        if target_id is None:''',
    '''    def _apply_chromium_zoom(self, target_id=None):
        """Apply Chromium page zoom and keep DWM on a 1:1 presentation contract."""
        if os.name != "nt" and self._page_zoom_percent() == 100:
            return True
        if target_id is None:''',
    "Linux default zoom",
)

swap(
    '''    def _apply_chromium_zoom_to_all_tabs(self):
        """Push the authoritative zoom to every known page and active CDP target."""
        applied = False''',
    '''    def _apply_chromium_zoom_to_all_tabs(self):
        """Push the authoritative zoom to every known page and active CDP target."""
        if os.name != "nt" and self._page_zoom_percent() == 100:
            return True
        applied = False''',
    "Linux all-tab zoom",
)

marker = '''        for delay in (120, 350, 900, 1800, 3500, 6000):
            try:'''
replacement = '''        if os.name != "nt":
            if self._page_zoom_percent() == 100:
                return
            def apply_linux_zoom():
                try:
                    if all_tabs:
                        self._executor.submit(self._apply_chromium_zoom_to_all_tabs)
                    else:
                        self._executor.submit(self._apply_chromium_zoom, target_id)
                except Exception:
                    pass
            try:
                self.root.after(300, apply_linux_zoom)
            except Exception:
                pass
            return
''' + marker
swap(marker, replacement, "Linux deferred zoom")

swap(
    '            if self._custom("show_window_controls", True):',
    '            if self._custom("show_window_controls", True) and os.name == "nt":',
    "native Linux window controls",
)

swap(
    '        combo(chromium_presentation, ["native", "software"])',
    '        combo(chromium_presentation, ["native", "software"] if os.name == "nt" else ["software"])',
    "presentation settings",
)

path.write_text(text, encoding="utf-8")
print("main.py Linux shell transformations applied")
