import time
import re
import os
import sys
import subprocess
import json
import base64
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageGrab
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode

from engine.net import (
    open_embedded_chromium,
    attach_embedded_chromium, resize_embedded_chromium,
    focus_embedded_chromium, wake_embedded_chromium, close_embedded_chromium,
    embedded_chromium_debug_report, get_embedded_chromium_html,
    get_embedded_chromium_layout_snapshot,
    create_embedded_chromium_target, activate_embedded_chromium_target,
    close_embedded_chromium_target,
    capture_embedded_chromium_frame, dispatch_embedded_chromium_mouse,
    dispatch_embedded_chromium_key, get_embedded_chromium_context, get_embedded_chromium_cursor, focus_embedded_chromium_point,
    get_embedded_chromium_dwm_input_offset, get_embedded_chromium_input_zoom_factor,
    get_embedded_chromium_page_state, find_embedded_chromium_text,
    set_embedded_chromium_presentation, set_embedded_chromium_zoom, check_embedded_chromium_zoom,
    validate_and_recover_embedded_chromium_frame, record_embedded_surface_probe, record_embedded_native_recovery, sync_embedded_chromium_native_geometry,
)



START_URL = "https://www.startpage.com/"

DEFAULT_PREFERENCES = {
    "homepage": START_URL,
    "startup": "homepage",
    "new_tab": "blank",
    "renderer": "chromium",
    "reuse_open_tabs": True,
    "show_status_bar": True,
    # v4.68: real native Chromium interaction is the default. The CDP
    # screenshot surface remains available only as an explicit diagnostic mode.
    "chromium_presentation": "native",
    # v4.56 privacy-first defaults.
    "network_diagnostics": "off",
    "clear_browsing_data_on_exit": True,
    "page_zoom_percent": 100,
    "adblock_enabled": True,
}

def _preferences_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Tekzite Browser"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path(__file__).resolve().parent
    return base / "preferences.json"

def _normalized_zoom_percent(value, default=100):
    try:
        value = int(str(value).rstrip("%"))
    except Exception:
        value = int(default)
    return max(50, min(300, value))

def load_preferences():
    prefs = dict(DEFAULT_PREFERENCES)
    try:
        data = json.loads(_preferences_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in prefs:
                if key in data:
                    prefs[key] = data[key]
    except Exception:
        pass
    # Keep zoom canonical in memory. Older builds could leave a string value
    # behind; normalizing it here prevents a later dialog save from silently
    # restoring 100%.
    prefs["page_zoom_percent"] = _normalized_zoom_percent(
        prefs.get("page_zoom_percent", 100)
    )
    return prefs

def save_preferences(prefs):
    """Atomically save preferences and verify that the committed file is readable.

    Antivirus/indexers can briefly race an atomic replace on Windows. Retry the
    tiny commit and verify the zoom value so a successful Save really survives
    the next Tekzite launch.
    """
    path = _preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(prefs)
    payload["page_zoom_percent"] = _normalized_zoom_percent(
        payload.get("page_zoom_percent", 100)
    )
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    last_error = None
    for attempt in range(3):
        tmp = path.with_name(path.name + f".tmp.{os.getpid()}.{attempt}")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(encoded)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            os.replace(tmp, path)
            check = json.loads(path.read_text(encoding="utf-8"))
            if _normalized_zoom_percent(check.get("page_zoom_percent", 100)) != payload["page_zoom_percent"]:
                raise OSError("saved zoom preference did not verify")
            return path
        except Exception as exc:
            last_error = exc
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(0.04 * (attempt + 1))
    raise OSError(f"Could not persist preferences: {last_error}")



BROWSER_VERSION = "8.2"


def _enable_per_monitor_dpi_awareness():
    """Put Tk and native Chromium embedding in the same pixel coordinate space.

    Without explicit DPI awareness Windows can virtualize Tk coordinates while
    Chromium remains per-monitor DPI aware.  A 1280px Tk host can then represent
    a materially larger physical client area, leaving an embedded Chromium
    surface occupying only part of the browser window.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        # PER_MONITOR_AWARE_V2.  This must happen before tk.Tk() creates HWNDs.
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        fn = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if fn is not None:
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_bool
            if fn(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return True
        # Windows 8.1 fallback.
        try:
            shcore = ctypes.WinDLL("shcore", use_last_error=True)
            fn2 = getattr(shcore, "SetProcessDpiAwareness", None)
            if fn2 is not None:
                fn2.argtypes = [ctypes.c_int]
                fn2.restype = ctypes.c_long
                if int(fn2(2)) in (0, -2147024891):  # S_OK / already set
                    return True
        except Exception:
            pass
        # Vista/7 fallback.
        fn3 = getattr(user32, "SetProcessDPIAware", None)
        if fn3 is not None:
            fn3.restype = ctypes.c_bool
            return bool(fn3())
    except Exception:
        pass
    return False





class BrowserApp:
    def __init__(self):
        self._dpi_awareness_enabled = _enable_per_monitor_dpi_awareness()
        self.root = tk.Tk()
        # v7.3: prefer Windows' variable UI font for Tekzite chrome.  This keeps
        # the shell visually closer to modern native Windows/Firefox typography
        # without touching web-page CSS or changing site layout.
        self._ui_font_family = "Segoe UI"
        self._ui_display_font_family = "Segoe UI"
        try:
            import tkinter.font as tkfont
            families = {str(name).casefold(): str(name) for name in tkfont.families(self.root)}
            self._ui_font_family = families.get("segoe ui variable text", families.get("segoe ui", "Segoe UI"))
            self._ui_display_font_family = families.get("segoe ui variable display", self._ui_font_family)
            for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkCaptionFont", "TkSmallCaptionFont"):
                try:
                    tkfont.nametofont(named).configure(family=self._ui_font_family)
                except Exception:
                    pass
            try:
                tkfont.nametofont("TkHeadingFont").configure(family=self._ui_display_font_family, weight="bold")
            except Exception:
                pass
        except Exception:
            pass
        self.root.title(f"Tekzite Browser v{BROWSER_VERSION}")
        self.root.geometry("1280x840")
        self.root.minsize(900, 600)
        self.root.overrideredirect(True)
        self._window_restore_geometry = None
        self._window_maximized = False
        self._window_drag_offset = (0, 0)
        self._fullscreen = False
        # v8.1: lightweight Tk-side animation state. Animations are intentionally
        # confined to Tekzite chrome; Chromium/DWM remains completely untouched.
        self._ui_animation_serial = 0
        self._ui_animation_jobs = {}
        self._loading_spinner_frames = ("◐", "◓", "◑", "◒")
        self.preferences = load_preferences()
        self._zoom_watchdog_after_id = None
        self._zoom_watchdog_interval_ms = 5000
        self._zoom_watchdog_checks = 0
        self._zoom_watchdog_corrections = 0
        self._zoom_watchdog_last_status = None
        # Privacy settings are exported before the first network/Chromium
        # process is started, so the helper inherits a privacy-first policy.
        os.environ["TEKZITE_NETWORK_LOG_LEVEL"] = str(self.preferences.get("network_diagnostics", "off"))
        os.environ["TEKZITE_ADBLOCK_ENABLED"] = "1" if self.preferences.get("adblock_enabled", True) else "0"

        # v4.28 visual shell: OLED-friendly, compact and intentionally distinct
        # from the embedded Chromium content surface.
        # v7.9: tighter OLED chrome.  Keep the shell low-clutter, but give
        # active/hover states a clearer hierarchy so the interface reads as one
        # coherent browser rather than a collection of Tk controls.
        self.ui = {
            "bg": "#090b10",
            "chrome": "#0f131b",
            "chrome_2": "#151a24",
            "chrome_hover": "#1b2230",
            "field": "#181e29",
            "field_focus": "#202838",
            "border": "#2a3242",
            "border_soft": "#1d2430",
            "border_focus": "#7c68ff",
            "text": "#f3f5fa",
            "muted": "#929caf",
            "muted_dim": "#6f788a",
            "accent": "#7965ff",
            "accent_hover": "#8c7aff",
            "danger": "#ff6078",
        }
        self.root.configure(bg=self.ui["bg"])

        # v4.31 is fully frameless. Keep Tekzite as a normal taskbar/Alt-Tab
        # application even though the native Windows title bar is removed.
        self.root.after(20, self._apply_frameless_app_style)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Tekzite.Vertical.TScrollbar",
            background=self.ui["chrome_2"],
            troughcolor=self.ui["bg"],
            bordercolor=self.ui["bg"],
            arrowcolor=self.ui["muted"],
            lightcolor=self.ui["chrome_2"],
            darkcolor=self.ui["chrome_2"],
        )

        self.history = []
        # v4.40: Tekzite-owned browser tabs. Each tab keeps its own history,
        # cached native document, and Chromium DevTools target so switching
        # tabs never has to fetch an already-open page again.
        self.tabs = []
        self._next_tab_id = 1
        self.active_tab_id = None
        self.tab_bar = None
        # v8.0 browser UX state. Closed tabs are cheap snapshots (the Chromium
        # target itself is still closed), while page-state polling keeps titles,
        # load indicators and favicons fresh without reloading anything.
        self._closed_tabs = []
        self._page_state_after_id = None
        self._page_state_poll_ms = 700
        self._page_state_inflight = set()
        self._favicon_images = {}
        self._find_bar_visible = False
        # v6.0: Chromium is the only web engine.  Tekzite owns browser UI,
        # while all page parsing/layout/JS/media/storage live in Chromium.
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tekzite-chromium")
        self.font_manager = None
        self.js_runtime = None
        self.css_diagnostics = None
        self.history_index = -1
        self._embedded_mode = False
        self._chromium_dwm_mode = False
        self._dwm_host = None
        self._dwm_host_size = (1, 1)
        self._dwm_host_wndproc = None
        self._dwm_host_original_wndproc = None
        # v6.1: keep the raw DWM destination hidden until Chromium has a
        # verified frame, and coalesce move/resize traffic while the user drags
        # the Tekzite window.
        self._dwm_surface_ready = False
        self._dwm_host_visible = False
        self._dwm_host_rect = None
        self._dwm_geometry_after_id = None
        self._dwm_pending_resize = False
        self._dwm_last_chromium_viewport = None
        self._embedded_future = None
        # v4.80: Tk chrome and the embedded Chromium child are separate native
        # focus domains. Delayed Chromium wake retries must never steal focus
        # back after the user has entered the omnibox.
        self._address_focus_active = False
        self._chromium_page_keyboard_active = False
        self._embedded_wake_after_ids = []
        # v4.83: native Chromium lives in a foreign Win32 child window, so Tk
        # does not receive its mouse events. Track the physical left-button
        # transition while the pointer is over the embedded host and hand
        # keyboard ownership to Chromium explicitly. This prevents a clicked
        # web form from showing a caret while keystrokes still land in the
        # Tekzite omnibox.
        self._embedded_pointer_button_down = False
        # v4.89: a native Chromium press is allowed to complete before Tekzite
        # touches cross-thread keyboard focus. Popup/menu triggers commonly
        # depend on an uninterrupted mouse-down -> mouse-up sequence.
        self._embedded_pointer_focus_pending = False
        self._embedded_focus_watch_after_id = None

        # Navigation work happens off the Tk thread. Each navigation gets a
        # monotonically increasing generation so stale completions can never
        # replace a newer page.
        self._navigation_generation = 0
        self._last_navigation_stage_times = {}
        self._lazy_font_future = None
        self._navigation_future = None
        self._navigation_progress = {}
        self._navigation_started_at = 0.0
        self._navigation_add_history = True
        self._navigation_url = None

        # Current prepared document is retained so viewport resizes can trigger
        # a true responsive reflow without downloading/parsing the page again.
        self._current_document = None
        self._last_layout_viewport = None
        self._resize_after_id = None
        self._resize_debounce_ms = 120
        self._layout_in_progress = False
        self._pending_reflow = False
        self._last_layout_ui_yield = 0.0

        # ── Frameless application bar + full browser menus ───────────────────
        app_bar = tk.Frame(
            self.root,
            bg=self.ui["bg"],
            height=34,
            highlightthickness=0,
        )
        app_bar.pack(fill="x")
        app_bar.pack_propagate(False)
        app_bar.bind("<ButtonPress-1>", self._start_window_drag)
        app_bar.bind("<B1-Motion>", self._drag_window)
        app_bar.bind("<Double-Button-1>", lambda event: self._toggle_maximize())

        app_brand = tk.Frame(app_bar, bg=self.ui["bg"])
        app_brand.pack(side="left", padx=(12, 10), fill="y")
        app_brand.bind("<ButtonPress-1>", self._start_window_drag)
        app_brand.bind("<B1-Motion>", self._drag_window)
        tk.Label(
            app_brand,
            text="T",
            fg="#ffffff",
            bg=self.ui["accent"],
            font=(self._ui_font_family, 9, "bold"),
            width=2,
            padx=1,
            pady=2,
        ).pack(side="left", pady=5)
        title_label = tk.Label(
            app_brand,
            text=f"TEKZITE  v{BROWSER_VERSION}",
            fg=self.ui["text"],
            bg=self.ui["bg"],
            font=(self._ui_font_family, 9, "bold"),
        )
        title_label.pack(side="left", padx=(7, 0))
        title_label.bind("<ButtonPress-1>", self._start_window_drag)
        title_label.bind("<B1-Motion>", self._drag_window)

        menu_strip = tk.Frame(app_bar, bg=self.ui["bg"])
        menu_strip.pack(side="left", fill="y")
        self._build_browser_menus(menu_strip)

        window_controls = tk.Frame(app_bar, bg=self.ui["bg"])
        window_controls.pack(side="right", fill="y")
        self._make_window_control(window_controls, "—", self._minimize_window).pack(side="left", fill="y")
        self._make_window_control(window_controls, "□", self._toggle_maximize).pack(side="left", fill="y")
        self._make_window_control(window_controls, "×", self.on_close, close=True).pack(side="left", fill="y")

        # ── Browser tab strip ───────────────────────────────────────────────
        self.tab_bar = tk.Frame(self.root, bg=self.ui["bg"], height=40, highlightthickness=0)
        self.tab_bar.pack(fill="x")
        self.tab_bar.pack_propagate(False)
        self.tab_items = tk.Frame(self.tab_bar, bg=self.ui["bg"])
        self.tab_items.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=(5, 4))
        self.new_tab_button = tk.Button(
            self.tab_bar, text="+", command=self._new_tab, bg=self.ui["bg"],
            fg=self.ui["muted"], activebackground=self.ui["chrome_hover"],
            activeforeground="#ffffff", relief="flat", bd=0, highlightthickness=0,
            font=(self._ui_font_family, 13), cursor="hand2", width=3,
        )
        self.new_tab_button.pack(side="right", padx=(2, 10), pady=(5, 4))
        self.new_tab_button.bind("<Enter>", lambda e: (
            self._animate_widget_color(self.new_tab_button, "bg", self.ui["chrome_hover"], 110),
            self._animate_widget_color(self.new_tab_button, "fg", self.ui["text"], 110),
        ))
        self.new_tab_button.bind("<Leave>", lambda e: (
            self._animate_widget_color(self.new_tab_button, "bg", self.ui["bg"], 130),
            self._animate_widget_color(self.new_tab_button, "fg", self.ui["muted"], 130),
        ))

        # ── Tekzite browser chrome ──────────────────────────────────────────
        toolbar = tk.Frame(
            self.root,
            bg=self.ui["chrome"],
            height=58,
            highlightthickness=0,
        )
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        def chrome_button(parent, text, command, *, accent=False, width=None):
            bg = self.ui["accent"] if accent else self.ui["chrome_2"]
            hover = self.ui["accent_hover"] if accent else self.ui["field_focus"]
            button = tk.Button(
                parent,
                text=text,
                command=command,
                bg=bg,
                fg="#ffffff" if accent else self.ui["text"],
                activebackground=hover,
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=(self._ui_font_family, 10, "bold" if accent else "normal"),
                cursor="hand2",
                padx=11,
                pady=6,
                width=width,
            )
            button.bind("<Enter>", lambda e, b=button, c=hover: self._animate_widget_color(b, "bg", c, 105))
            button.bind("<Leave>", lambda e, b=button, c=bg: self._animate_widget_color(b, "bg", c, 135))
            return button

        nav = tk.Frame(toolbar, bg=self.ui["chrome"])
        nav.pack(side="left", pady=8)

        self.back_button = chrome_button(nav, "‹", self.go_back, width=2)
        self.back_button.pack(side="left", padx=(0, 5))
        self.forward_button = chrome_button(nav, "›", self.go_forward, width=2)
        self.forward_button.pack(side="left")

        self.url_var = tk.StringVar(value=self._homepage_url())

        address_shell = tk.Frame(
            toolbar,
            bg=self.ui["field"],
            highlightbackground=self.ui["border"],
            highlightcolor=self.ui["border_focus"],
            highlightthickness=1,
        )
        address_shell.pack(side="left", fill="x", expand=True, padx=(10, 9), pady=9)

        tk.Label(
            address_shell,
            text="⌁",
            fg=self.ui["muted"],
            bg=self.ui["field"],
            font=("Segoe UI Symbol", 12),
        ).pack(side="left", padx=(12, 4))

        self.address = tk.Entry(
            address_shell,
            textvariable=self.url_var,
            bg=self.ui["field"],
            fg=self.ui["text"],
            insertbackground="#ffffff",
            selectbackground=self.ui["accent"],
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(self._ui_font_family, 10),
        )
        self.address.pack(side="left", fill="both", expand=True, padx=(2, 10), pady=7)
        self.address.bind("<Return>", lambda event: self.navigate())
        self.address.bind(
            "<FocusIn>",
            lambda event: (
                self._animate_widget_color(address_shell, "highlightbackground", self.ui["border_focus"], 135),
                self._animate_widget_color(self.address, "bg", self.ui["field_focus"], 135),
                self._animate_widget_color(address_shell, "bg", self.ui["field_focus"], 135),
            ),
        )
        self.address.bind(
            "<FocusOut>",
            lambda event: (
                self._animate_widget_color(address_shell, "highlightbackground", self.ui["border"], 150),
                self._animate_widget_color(self.address, "bg", self.ui["field"], 150),
                self._animate_widget_color(address_shell, "bg", self.ui["field"], 150),
            ),
        )
        # v4.80: claim Tekzite UI focus before the default Entry binding runs.
        # The visual FocusIn/FocusOut bindings above stay unchanged; these
        # additive handlers only arbitrate Tk-vs-Chromium keyboard ownership.
        self.address.bind("<Button-1>", self._on_address_pointer_down, add="+")
        self.address.bind("<FocusIn>", self._on_address_focus_in, add="+")
        self.address.bind("<FocusOut>", self._on_address_focus_out, add="+")
        self.address.bind("<Button-3>", self._show_address_context_menu)
        self.address.bind("<Control-Shift-v>", lambda event: self._paste_and_go())

        go_button = chrome_button(toolbar, "Go", self.navigate, accent=True)
        go_button.pack(side="right", padx=(4, 12), pady=8)

        # Keep the exact debug button labels because they are useful landmarks
        # in automated regression tests, while visually demoting them from the
        # primary browsing controls.
        debug_group = tk.Frame(toolbar, bg=self.ui["chrome"])
        debug_group.pack(side="right", pady=8)
        chrome_button(
            debug_group,
            text="Copy Full Debug",
            command=self.copy_full_debug,
        ).pack(side="right", padx=(5, 0))
        chrome_button(
            debug_group,
            text="Copy All Debug",
            command=self.copy_all_debug,
        ).pack(side="right")

        # v8.0 find-in-page bar. It lives in Tekzite chrome and uses Chromium's
        # own live DOM selection, so no site CSS/HTML is modified.
        self.find_bar = tk.Frame(self.root, bg=self.ui["chrome"], height=0, highlightthickness=0)
        self.find_bar.pack_propagate(False)
        self.find_var = tk.StringVar()
        self.find_entry = tk.Entry(
            self.find_bar, textvariable=self.find_var, bg=self.ui["field"], fg=self.ui["text"],
            insertbackground=self.ui["text"], selectbackground=self.ui["accent"], selectforeground="#ffffff",
            relief="flat", bd=0, highlightthickness=1, highlightbackground=self.ui["border"],
            font=(self._ui_font_family, 9),
        )
        self.find_entry.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=6)
        self.find_entry.bind("<Return>", lambda event: self._find_in_page(False))
        self.find_entry.bind("<Shift-Return>", lambda event: self._find_in_page(True))
        self.find_entry.bind("<Escape>", lambda event: self._hide_find_bar())
        for text, cmd in (("↑", lambda: self._find_in_page(True)), ("↓", lambda: self._find_in_page(False)), ("×", self._hide_find_bar)):
            b = tk.Button(self.find_bar, text=text, command=cmd, bg=self.ui["chrome_2"], fg=self.ui["text"],
                          activebackground=self.ui["field_focus"], activeforeground="#ffffff", relief="flat", bd=0,
                          highlightthickness=0, cursor="hand2", padx=10, pady=3, font=(self._ui_font_family, 9))
            b.pack(side="left", padx=(0, 5), pady=5)

        separator = tk.Frame(self.root, bg=self.ui["border_soft"], height=1)
        separator.pack(fill="x")

        canvas_frame = tk.Frame(self.root, bg=self.ui["bg"], highlightthickness=0)
        canvas_frame.pack(fill="both", expand=True)
        self.content_frame = canvas_frame

        # Native host used when a modern-JavaScript compatibility page is
        # rendered by the persistent Chromium helper. On Windows the Chromium
        # app window is re-parented into this frame, so it is physically inside
        # Tekzite rather than appearing as a second browser window.
        self.edge_host = tk.Frame(
            canvas_frame,
            bg=self.ui["bg"],
            highlightthickness=0,
            takefocus=1,
        )
        self.edge_host.bind("<Configure>", self._on_edge_host_configure)
        # v5.32: DWM thumbnails are presentation-only. The raw Win32 DWM host
        # is hit-test transparent, so edge_host is the real interactive plane
        # beneath it. Bind the same CDP input path used by software presentation
        # so click-to-focus, typing, wheel, hover and browser context menus work
        # while Chromium itself remains parked off-screen.
        self.edge_host.bind("<ButtonPress-1>", self._on_chromium_surface_press)
        self.edge_host.bind("<ButtonRelease-1>", self._on_chromium_surface_release)
        self.edge_host.bind("<Motion>", self._on_chromium_surface_motion)
        self.edge_host.bind("<B1-Motion>", self._on_chromium_surface_drag)
        self.edge_host.bind("<Leave>", self._on_chromium_surface_leave)
        self.edge_host.bind("<MouseWheel>", self._on_chromium_surface_wheel)
        self.edge_host.bind("<KeyPress>", self._on_chromium_surface_key)
        self.edge_host.bind("<Button-3>", self._on_chromium_surface_context_menu)
        self.root.bind("<KeyPress>", self._on_root_chromium_key, add="+")

        # Software Chromium presentation surface.  Some Windows/DWM builds can
        # accept the native Chromium child HWND yet present only a black frame.
        # For those pages Tekzite can display CDP-rendered frames itself and
        # forward input back to Chromium, bypassing the fragile compositor HWND.
        self.chromium_surface = tk.Canvas(
            canvas_frame, bg=self.ui["bg"], highlightthickness=0, takefocus=1
        )
        self._chromium_software_mode = False
        self._chromium_frame_photo = None
        self._chromium_frame_item = None
        self._chromium_frame_future = None
        # v5.09: input has its own ordered worker so clicks/keys/wheel never
        # sit behind an expensive screenshot/decode job in the general loader.
        self._chromium_input_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-cdp-input")
        self._chromium_frame_generation = 0
        self._chromium_frame_target_id = None
        # Input coordinates must follow the exact bitmap-to-canvas transform.
        # On Windows DPI scaling the CDP screenshot can be in a different pixel
        # space than Tk pointer events, even when both nominally describe the
        # same viewport. Keep both sizes from the last presented frame and map
        # pointer coordinates back into Chromium CSS/surface coordinates.
        self._chromium_frame_source_size = None
        self._chromium_frame_display_size = None
        # v4.59 visual-performance software surface. Keep Chromium responsive by
        # decoupling input from capture, rendering slowly while idle and
        # briefly bursting after interaction. Mouse motion is coalesced so a
        # fast pointer sweep cannot flood the CDP queue.
        self._chromium_interaction_until = 0.0
        self._chromium_last_frame_signature = None
        self._chromium_pending_motion = None
        self._chromium_motion_after_id = None
        # v7.7: track a real left-button drag so Chromium can create native
        # text selections through the DWM input plane.
        self._chromium_left_button_down = False
        self._chromium_drag_selecting = False
        self._chromium_press_point = None
        # v5.08: software presentation can sustain a noticeably smoother
        # interaction cadence now that the viewport contract and Tk image are
        # reused between frames. 33 ms targets ~30 FPS without queueing captures.
        self._chromium_active_frame_ms = 24
        self._chromium_idle_frame_ms = 750
        # Hover is coalesced, but at ~80 Hz so menus/tooltips feel immediate.
        self._chromium_motion_interval_ms = 12
        # v6.8: mirror the webpage's effective CSS cursor on Tekzite's DWM
        # input plane. Only one cursor probe may be in flight at a time; rapid
        # mouse movement is naturally coalesced by the existing hover lane.
        self._chromium_cursor_future = None
        self._chromium_cursor_name = "arrow"
        self._chromium_cursor_point = None
        # v4.66: keep the CDP software viewport stable. Tk can emit a burst of
        # transient <Configure> sizes during layout/DPI changes. Reapplying each
        # one to Emulation.setDeviceMetricsOverride makes responsive pages visibly
        # zoom/reflow in and out. Latch the last sane viewport and only commit a
        # resize after the candidate has remained stable for a short debounce.
        self._chromium_viewport_size = None
        self._chromium_pending_viewport_size = None
        self._chromium_viewport_after_id = None
        self._chromium_viewport_debounce_ms = 300
        self._chromium_viewport_min_width = 240
        self._chromium_viewport_min_height = 160
        # v5.04: a visible-surface fallback is not permanent.  If the
        # window later settles at a new sane size (maximize/fullscreen/restore),
        # use that stable resize as a chance to retry native Chromium.
        self._native_recovery_after_id = None
        self.chromium_surface.bind("<Configure>", self._on_chromium_surface_configure)
        self.chromium_surface.bind("<ButtonPress-1>", self._on_chromium_surface_press)
        self.chromium_surface.bind("<ButtonRelease-1>", self._on_chromium_surface_release)
        self.chromium_surface.bind("<Motion>", self._on_chromium_surface_motion)
        self.chromium_surface.bind("<B1-Motion>", self._on_chromium_surface_drag)
        self.chromium_surface.bind("<Leave>", self._on_chromium_surface_leave)
        self.chromium_surface.bind("<MouseWheel>", self._on_chromium_surface_wheel)
        self.chromium_surface.bind("<KeyPress>", self._on_chromium_surface_key)
        self.chromium_surface.bind("<Button-3>", self._on_chromium_surface_context_menu)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg=self.ui["bg"],
            highlightthickness=0,
        )

        self.scrollbar = ttk.Scrollbar(
            canvas_frame,
            orient="vertical",
            command=self._scroll_yview,
            style="Tekzite.Vertical.TScrollbar",
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-3>", self._on_native_context_menu)
        self.root.bind("<Map>", self._on_window_map, add="+")
        # v5.13: the native Chromium surface is a clipped top-level overlay.
        # Re-pin it whenever the Tekzite root moves as well as when the content
        # host itself resizes.
        self.root.bind("<Configure>", self._on_root_configure_native_overlay, add="+")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = tk.Frame(
            self.root,
            bg=self.ui["chrome"],
            height=25,
            highlightbackground=self.ui["border"],
            highlightthickness=1,
        )
        status_bar.pack(fill="x")
        self.status_bar = status_bar
        if not getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True):
            self.status_bar.pack_forget()
        status_bar.pack_propagate(False)
        tk.Label(
            status_bar,
            text="●",
            fg="#45d483",
            bg=self.ui["chrome"],
            font=(self._ui_font_family, 7),
        ).pack(side="left", padx=(12, 6))
        tk.Label(
            status_bar,
            textvariable=self.status_var,
            anchor="w",
            fg=self.ui["muted"],
            bg=self.ui["chrome"],
            font=(self._ui_font_family, 9),
        ).pack(side="left", fill="x", expand=True)
        tk.Label(
            status_bar,
            text=f"v{BROWSER_VERSION}",
            fg=self.ui["muted"],
            bg=self.ui["chrome"],
            font=(self._ui_font_family, 8),
        ).pack(side="right", padx=(8, 12))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-l>", lambda event: self._focus_address())
        self.root.bind("<Control-t>", lambda event: self._new_tab())
        self.root.bind("<Control-w>", lambda event: self._close_active_tab())
        self.root.bind("<Control-Shift-T>", lambda event: self._restore_closed_tab())
        self.root.bind("<Control-f>", lambda event: self._show_find_bar())
        self.root.bind("<Control-Tab>", lambda event: self._cycle_tab(1))
        self.root.bind("<Control-Shift-Tab>", lambda event: self._cycle_tab(-1))
        self.root.bind("<Control-r>", lambda event: self._reload_current())
        self.root.bind("<Control-u>", lambda event: self.inspect_html())
        self.root.bind("<Control-comma>", lambda event: self.show_preferences())
        self.root.bind("<F5>", lambda event: self._reload_current())
        self.root.bind("<Alt-Left>", lambda event: self.go_back())
        self.root.bind("<Alt-Right>", lambda event: self.go_forward())
        self.root.bind("<F11>", lambda event: self._toggle_fullscreen())
        for _n in range(1, 9):
            self.root.bind(f"<Control-Key-{_n}>", lambda event, n=_n: self._switch_tab_by_index(n - 1))
        self.root.bind("<Control-Key-9>", lambda event: self._switch_tab_by_index(-1))

        # Foreign Chromium child windows bypass Tk's event bindings. Keep a
        # tiny Win32 pointer-focus bridge alive for native embedded pages.
        self._schedule_embedded_pointer_focus_watch()

        # v6.0: no Tekzite document painter exists anymore.  The canvas remains
        # only as an empty/new-tab backing surface; all actual pages use Chromium.
        self.painter = None
        self.status_var.set("Chromium engine ready")

        # Create the initial tab before startup navigation.
        self._new_tab(switch=True, navigate=False)

        # Let Tk map and paint the chrome before startup navigation begins.
        self._schedule_zoom_watchdog(initial=True)
        self._schedule_page_state_poll(initial=True)

        startup_mode = getattr(self, "preferences", DEFAULT_PREFERENCES).get("startup", "homepage")
        startup_action = (
            (lambda: self.navigate_to(self._homepage_url(), add_history=True))
            if startup_mode == "homepage" else self._focus_address
        )
        self.root.after(
            250,
            startup_action,
        )

    # ── Tabs ──────────────────────────────────────────────────────────────
    # ── v8.1 UI animation helpers ────────────────────────────────────────
    @staticmethod
    def _hex_rgb(value):
        value = str(value or "").strip()
        if value.startswith("#") and len(value) == 7:
            try:
                return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
            except Exception:
                return None
        return None

    @staticmethod
    def _rgb_hex(rgb):
        return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)

    def _animate_widget_color(self, widget, option, target, duration=120, steps=8):
        """Ease a Tk color option without blocking the UI thread.

        A new animation for the same widget/option cancels the previous one, so
        rapid pointer movement never builds an after() queue.
        """
        try:
            if not widget.winfo_exists():
                return
            start = self._hex_rgb(widget.cget(option))
            end = self._hex_rgb(target)
        except Exception:
            return
        if start is None or end is None or start == end:
            try:
                widget.configure(**{option: target})
            except Exception:
                pass
            return
        key = (str(widget), str(option))
        self._ui_animation_serial += 1
        token = self._ui_animation_serial
        self._ui_animation_jobs[key] = token
        steps = max(2, int(steps))
        interval = max(8, int(duration) // steps)

        def frame(i=1):
            if self._ui_animation_jobs.get(key) != token:
                return
            try:
                if not widget.winfo_exists():
                    return
                t = min(1.0, i / float(steps))
                # cubic ease-out: responsive at the start, soft at the end.
                eased = 1.0 - (1.0 - t) ** 3
                rgb = tuple(a + (b - a) * eased for a, b in zip(start, end))
                widget.configure(**{option: self._rgb_hex(rgb)})
            except Exception:
                return
            if i < steps:
                self.root.after(interval, lambda: frame(i + 1))
            else:
                self._ui_animation_jobs.pop(key, None)

        frame()

    def _animate_widget_height(self, widget, start, end, duration=150, on_done=None):
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        self._ui_animation_serial += 1
        token = self._ui_animation_serial
        key = (str(widget), "height")
        self._ui_animation_jobs[key] = token
        steps = max(3, min(14, int(duration // 12)))
        interval = max(8, int(duration) // steps)
        start, end = int(start), int(end)

        def frame(i=1):
            if self._ui_animation_jobs.get(key) != token:
                return
            try:
                if not widget.winfo_exists():
                    return
                t = min(1.0, i / float(steps))
                eased = 1.0 - (1.0 - t) ** 3
                value = int(round(start + (end - start) * eased))
                widget.configure(height=max(0, value))
            except Exception:
                return
            if i < steps:
                self.root.after(interval, lambda: frame(i + 1))
            else:
                self._ui_animation_jobs.pop(key, None)
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        frame()

    def _animate_toplevel_in(self, win, duration=140):
        """Small native fade for dialogs; silently degrades if unsupported."""
        try:
            win.attributes("-alpha", 0.0)
        except Exception:
            return
        steps = 9
        interval = max(10, duration // steps)
        def frame(i=1):
            try:
                if not win.winfo_exists():
                    return
                t = min(1.0, i / float(steps))
                eased = 1.0 - (1.0 - t) ** 3
                win.attributes("-alpha", eased)
                if i < steps:
                    win.after(interval, lambda: frame(i + 1))
            except Exception:
                pass
        frame()

    def _animate_loading_icon(self, label, tab_id, frame_index=0):
        try:
            if not label.winfo_exists():
                return
        except Exception:
            return
        tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if not tab or not tab.get("loading") or tab.get("favicon_photo"):
            return
        try:
            label.configure(text=self._loading_spinner_frames[frame_index % len(self._loading_spinner_frames)])
            label.after(115, lambda: self._animate_loading_icon(label, tab_id, frame_index + 1))
        except Exception:
            pass

    def _active_tab(self):
        for tab in self.tabs:
            if tab.get("id") == self.active_tab_id:
                return tab
        return None

    def _canonical_tab_url(self, url):
        """Canonical comparison key used only for tab de-duplication."""
        try:
            value = self.apply_site_compatibility(self.normalize_url(str(url or "")))
            parts = urlsplit(value)
            host = (parts.hostname or "").lower()
            netloc = host
            if parts.port and not ((parts.scheme == "https" and parts.port == 443) or (parts.scheme == "http" and parts.port == 80)):
                netloc += f":{parts.port}"
            path = parts.path or "/"
            if path != "/":
                path = path.rstrip("/") or "/"
            return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))
        except Exception:
            return str(url or "").strip()

    def _tab_title_for_url(self, url):
        try:
            parts = urlsplit(str(url or ""))
            host = (parts.hostname or "").lower()
            if host:
                if host.startswith("www."):
                    host = host[4:]
                return host[:28]
        except Exception:
            pass
        return "New Tab"

    def _refresh_tab_strip(self):
        if self.tab_items is None:
            return
        for child in self.tab_items.winfo_children():
            child.destroy()

        for tab in self.tabs:
            active = tab.get("id") == self.active_tab_id
            normal_bg = self.ui["chrome"] if active else self.ui["bg"]
            hover_bg = self.ui["chrome_hover"]
            normal_fg = self.ui["text"] if active else self.ui["muted"]

            # v7.9: tabs use a quiet surface plus a 2px active indicator rather
            # than a bright rectangular border. This keeps many-tab layouts
            # calmer while the current tab remains immediately obvious.
            frame = tk.Frame(
                self.tab_items,
                bg=normal_bg,
                highlightthickness=1,
                highlightbackground=self.ui["border_soft"] if active else self.ui["bg"],
            )
            frame.pack(side="left", padx=(0, 3), fill="y")

            body = tk.Frame(frame, bg=normal_bg)
            body.pack(side="top", fill="both", expand=True)

            # v8.0: favicon/loading glyph and live page title. Keep the icon in
            # its own label so the title remains compact as tabs get narrower.
            icon_photo = tab.get("favicon_photo")
            icon = tk.Label(
                body,
                image=icon_photo if icon_photo else "",
                text="" if icon_photo else ("◌" if tab.get("loading") else "◇"),
                compound="left", bg=normal_bg, fg=self.ui["accent_hover"] if tab.get("loading") else self.ui["muted_dim"],
                font=(self._ui_font_family, 9), padx=7, pady=4, cursor="hand2",
            )
            icon.pack(side="left")
            title = str(tab.get("title") or "New Tab")
            label = tk.Label(
                body,
                text=title[:28],
                bg=normal_bg,
                fg=normal_fg,
                font=(self._ui_font_family, 9),
                padx=(2 if icon_photo else 0),
                pady=4,
                cursor="hand2",
            )
            label.pack(side="left")
            for click_widget in (frame, body, icon, label):
                click_widget.bind("<Button-1>", lambda event, tid=tab["id"]: self._switch_tab(tid))
                click_widget.bind("<Button-2>", lambda event, tid=tab["id"]: self._close_tab(tid))

            close = tk.Button(
                body,
                text="×",
                command=lambda tid=tab["id"]: self._close_tab(tid),
                bg=normal_bg,
                fg=self.ui["muted_dim"],
                activebackground=self.ui["danger"],
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=(self._ui_font_family, 9),
                cursor="hand2",
                padx=5,
                pady=0,
            )
            close.pack(side="right", fill="y")

            indicator = tk.Frame(frame, bg=self.ui["accent"] if active else normal_bg, height=2)
            indicator.pack(side="bottom", fill="x")

            def set_hover(_event=None, *, inside=True, fr=frame, bd=body, ic=icon, lb=label, cl=close, ind=indicator,
                          is_active=active, base=normal_bg, base_fg=normal_fg):
                bg = hover_bg if inside and not is_active else base
                for w in (fr, bd, ic, lb, cl):
                    self._animate_widget_color(w, "bg", bg, 105 if inside else 145)
                self._animate_widget_color(lb, "fg", self.ui["text"] if inside else base_fg, 105 if inside else 145)
                self._animate_widget_color(cl, "fg", self.ui["muted"] if inside else self.ui["muted_dim"], 105 if inside else 145)
                if not is_active:
                    self._animate_widget_color(ind, "bg", bg, 105 if inside else 145)

            for widget in (frame, body, icon, label):
                widget.bind("<Enter>", lambda e, fn=set_hover: fn(inside=True))
                widget.bind("<Leave>", lambda e, fn=set_hover: fn(inside=False))
            close.bind("<Enter>", lambda e, c=close: (
                self._animate_widget_color(c, "bg", self.ui["danger"], 90),
                self._animate_widget_color(c, "fg", "#ffffff", 90),
            ))
            close.bind("<Leave>", lambda e, fn=set_hover: fn(inside=False))

            if active:
                # Give the newly-active tab a short accent settle rather than a hard flash.
                try:
                    indicator.configure(bg=self.ui["chrome_hover"])
                    self._animate_widget_color(indicator, "bg", self.ui["accent"], 150)
                except Exception:
                    pass
            if tab.get("loading") and not icon_photo:
                self._animate_loading_icon(icon, tab.get("id"), 0)

    def _decode_favicon_photo(self, data_b64):
        try:
            raw = base64.b64decode(str(data_b64 or ""), validate=False)
            if not raw or len(raw) > 524288:
                return None
            image = Image.open(BytesIO(raw)).convert("RGBA")
            image.thumbnail((16, 16), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            x = (16 - image.width) // 2
            y = (16 - image.height) // 2
            canvas.alpha_composite(image, (x, y))
            return ImageTk.PhotoImage(canvas)
        except Exception:
            return None

    def _poll_one_tab_state(self, tab_id, target_id, include_favicon=False):
        key = str(target_id or "")
        if not key or key in self._page_state_inflight:
            return
        self._page_state_inflight.add(key)
        future = self._executor.submit(
            get_embedded_chromium_page_state,
            target_id=target_id, include_favicon=bool(include_favicon), timeout=3,
        )

        def finish():
            if not future.done():
                self.root.after(35, finish)
                return
            self._page_state_inflight.discard(key)
            try:
                info = future.result() or {}
            except Exception:
                return
            tab = next((t for t in self.tabs if t.get("id") == tab_id and t.get("chromium_target_id") == target_id), None)
            if tab is None:
                return
            changed = False
            title = str(info.get("title") or "").strip()
            if title and title != tab.get("title"):
                tab["title"] = title
                changed = True
            live_url = str(info.get("url") or "").strip()
            if live_url and live_url != "about:blank" and live_url != tab.get("url"):
                tab["url"] = live_url
                if tab.get("id") == self.active_tab_id and not self._address_focus_active:
                    self.url_var.set(live_url)
                changed = True
            ready = str(info.get("readyState") or "")
            loading = ready not in ("interactive", "complete")
            if ready != tab.get("ready_state") or loading != bool(tab.get("loading")):
                tab["ready_state"] = ready
                tab["loading"] = loading
                changed = True
            fav_url = str(info.get("favicon") or "")
            if fav_url and fav_url != tab.get("favicon_url"):
                tab["favicon_url"] = fav_url
                changed = True
            fav_b64 = info.get("favicon_b64")
            if fav_b64:
                photo = self._decode_favicon_photo(fav_b64)
                if photo is not None:
                    tab["favicon_photo"] = photo
                    changed = True
            if changed:
                self._refresh_tab_strip()

        self.root.after(20, finish)

    def _page_state_tick(self):
        self._page_state_after_id = None
        live = [t for t in self.tabs if t.get("chromium_target_id")]
        active = self._active_tab()
        for tab in live:
            # Active tab gets every poll; background tabs are sampled less often.
            if tab is not active and (self._navigation_generation + tab.get("id", 0) + int(time.monotonic())) % 3:
                continue
            need_icon = not tab.get("favicon_photo") or not tab.get("favicon_url")
            self._poll_one_tab_state(tab.get("id"), tab.get("chromium_target_id"), include_favicon=need_icon)
        self._schedule_page_state_poll()

    def _schedule_page_state_poll(self, initial=False):
        try:
            if self._page_state_after_id is not None:
                self.root.after_cancel(self._page_state_after_id)
        except Exception:
            pass
        self._page_state_after_id = self.root.after(1100 if initial else self._page_state_poll_ms, self._page_state_tick)

    def _restore_closed_tab(self):
        if not self._closed_tabs:
            self.status_var.set("No recently closed tab")
            return "break"
        snap = self._closed_tabs.pop()
        url = str(snap.get("url") or "")
        tab = self._new_tab(url=url or None, switch=True, navigate=bool(url))
        if tab is not None:
            tab["title"] = str(snap.get("title") or tab.get("title") or "New Tab")
            if isinstance(snap.get("history"), list):
                tab["history"] = list(snap["history"])
                tab["history_index"] = int(snap.get("history_index", len(tab["history"]) - 1))
            self._refresh_tab_strip()
        return "break"

    def _cycle_tab(self, direction=1):
        if len(self.tabs) < 2:
            return "break"
        ids = [t.get("id") for t in self.tabs]
        try:
            idx = ids.index(self.active_tab_id)
        except ValueError:
            idx = 0
        self._switch_tab(ids[(idx + int(direction)) % len(ids)])
        return "break"

    def _switch_tab_by_index(self, index):
        if not self.tabs:
            return "break"
        index = len(self.tabs) - 1 if int(index) < 0 else min(int(index), len(self.tabs) - 1)
        self._switch_tab(self.tabs[index]["id"])
        return "break"

    def _show_find_bar(self):
        if not self._find_bar_visible:
            self.find_bar.configure(height=0)
            self.find_bar.pack(fill="x", before=self.content_frame)
            self._find_bar_visible = True
            self._animate_widget_height(self.find_bar, 0, 40, duration=155)
        self.find_entry.focus_set()
        self.find_entry.selection_range(0, "end")
        return "break"

    def _hide_find_bar(self):
        if self._find_bar_visible:
            self._find_bar_visible = False
            def finish():
                try:
                    if self.find_bar.winfo_exists() and not self._find_bar_visible:
                        self.find_bar.pack_forget()
                        self.find_bar.configure(height=0)
                except Exception:
                    pass
            try:
                current = max(1, int(self.find_bar.winfo_height()))
            except Exception:
                current = 40
            self._animate_widget_height(self.find_bar, current, 0, duration=130, on_done=finish)
        try:
            self.root.focus_set()
        except Exception:
            pass
        return "break"

    def _find_in_page(self, backwards=False):
        query = self.find_var.get()
        tab = self._active_tab()
        target_id = tab.get("chromium_target_id") if tab else None
        if not query or not target_id:
            return "break"
        future = self._executor.submit(
            find_embedded_chromium_text, query, target_id=target_id, backwards=bool(backwards), timeout=3
        )
        def done():
            if not future.done():
                self.root.after(25, done)
                return
            try:
                found = bool(future.result())
            except Exception:
                found = False
            self.status_var.set(("Found: " if found else "Not found: ") + query)
        self.root.after(20, done)
        return "break"

    def _paste_and_go(self):
        try:
            value = self.root.clipboard_get().strip()
        except Exception:
            value = ""
        if value:
            self.url_var.set(value)
            self._release_address_focus_for_navigation()
            self.navigate_to(value, add_history=True)
        return "break"

    def _show_address_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0, bg=self.ui["chrome"], fg=self.ui["text"],
                       activebackground=self.ui["accent"], activeforeground="#ffffff", bd=0)
        menu.add_command(label="Cut", command=lambda: self.address.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: self.address.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: self.address.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Paste and Go", command=self._paste_and_go)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except Exception: pass
        return "break"

    def _new_tab(self, url=None, switch=True, navigate=True):
        tab = {
            "id": self._next_tab_id,
            "url": "",
            "title": "New Tab",
            "engine": "chromium",
            "document": None,
            "history": [],
            "history_index": -1,
            "scroll_fraction": 0.0,
            "chromium_target_id": None,
            "loaded": False,
            "loading": False,
            "ready_state": "",
            "favicon_url": "",
            "favicon_photo": None,
        }
        self._next_tab_id += 1
        self.tabs.append(tab)
        if switch:
            self._capture_active_tab_state()
            self.active_tab_id = tab["id"]
            self.history = tab["history"]
            self.history_index = tab["history_index"]
            self._current_document = None
            self._show_native_canvas()
            try:
                self.canvas.delete("all")
                self.canvas.configure(scrollregion=(0, 0, 1, 1))
            except Exception:
                pass
            self.url_var.set(url or "")
        self._refresh_tab_strip()
        if switch and navigate and url:
            self.navigate_to(url)
        elif switch and navigate and not url:
            if getattr(self, "preferences", DEFAULT_PREFERENCES).get("new_tab") == "homepage":
                self.navigate_to(self._homepage_url())
            else:
                self._focus_address()
        return tab

    def _capture_active_tab_state(self):
        tab = self._active_tab()
        if tab is None:
            return
        tab["url"] = self.url_var.get().strip()
        tab["history"] = list(self.history)
        tab["history_index"] = int(self.history_index)
        tab["engine"] = "chromium"
        tab["document"] = None
        if not self._embedded_mode:
            try:
                tab["scroll_fraction"] = float(self.canvas.yview()[0])
            except Exception:
                pass

    def _find_open_tab_by_url(self, url, exclude_id=None):
        key = self._canonical_tab_url(url)
        if not key:
            return None
        for tab in self.tabs:
            if exclude_id is not None and tab.get("id") == exclude_id:
                continue
            if tab.get("loaded") and self._canonical_tab_url(tab.get("url")) == key:
                return tab
        return None

    def _switch_tab(self, tab_id):
        if tab_id == self.active_tab_id:
            return True
        target = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if target is None:
            return False
        self._capture_active_tab_state()
        self._navigation_generation += 1
        self.active_tab_id = tab_id
        self.history = list(target.get("history") or [])
        target["history"] = self.history
        self.history_index = int(target.get("history_index", -1))
        self.url_var.set(target.get("url") or "")
        self.update_history_buttons()
        self._refresh_tab_strip()

        if target.get("engine") == "chromium" and target.get("chromium_target_id"):
            try:
                if activate_embedded_chromium_target(target["chromium_target_id"]):
                    self._current_document = None
                    presentation = target.get("presentation") or (
                        "software" if self._use_chromium_software_surface_for_url(target.get("url", "")) else "native"
                    )
                    if target.get("software_fallback_reason") == "visible-surface":
                        presentation = "software"
                        target["presentation"] = "software"
                    # v7.5: hot-switch existing native Chromium tabs without
                    # rebuilding the already-live DWM presentation. The old path
                    # hid/revealed DWM, forced Tk idle processing and resized the
                    # Chromium source on every tab click, even though the viewport
                    # geometry had not changed.
                    fast_native_switch = bool(
                        presentation == "native"
                        and self._embedded_mode
                        and self._chromium_dwm_mode
                        and self._dwm_surface_ready
                        and self.edge_host.winfo_ismapped()
                    )
                    if presentation == "software":
                        set_embedded_chromium_presentation("software", target["chromium_target_id"])
                        self._show_chromium_software_surface(target["chromium_target_id"])
                    elif fast_native_switch:
                        self._chromium_frame_target_id = target["chromium_target_id"]
                        self._chromium_software_mode = False
                        # Native Chromium zoom is already maintained by the local
                        # extension/watchdog. Do not synchronously re-apply zoom to
                        # every tab during the visual switch. Verify this tab later.
                        self.root.after(90, lambda tid=target["chromium_target_id"]: self._apply_chromium_zoom(tid))
                    else:
                        set_embedded_chromium_presentation("native", target["chromium_target_id"])
                        self._show_embedded_host()
                        self._schedule_embedded_surface_wake()
                        self._schedule_chromium_zoom_apply(target_id=target["chromium_target_id"])
                    self.status_var.set(f"Switched to existing tab | {target.get('url','')}")
                    return True
            except Exception:
                pass

        # Blank/unloaded tab: no network work until the user navigates.
        self._show_native_canvas()
        self._current_document = None
        try:
            self.canvas.delete("all")
        except Exception:
            pass
        self.status_var.set("Ready")
        return True

    def _close_tab(self, tab_id):
        tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if tab is None:
            return
        # v8.0: keep a cheap restore snapshot before destroying the Chromium
        # target. Ctrl+Shift+T recreates the page with normal Chromium state.
        if tab.get("url") or tab.get("loaded"):
            snap = {k: tab.get(k) for k in ("url", "title", "history", "history_index")}
            self._closed_tabs.append(snap)
            if len(self._closed_tabs) > 20:
                self._closed_tabs = self._closed_tabs[-20:]
        if tab.get("chromium_target_id"):
            try:
                close_embedded_chromium_target(tab["chromium_target_id"])
            except Exception:
                pass
        index = self.tabs.index(tab)
        was_active = tab_id == self.active_tab_id
        self.tabs.remove(tab)
        if not self.tabs:
            self._new_tab(switch=True, navigate=False)
            self._refresh_tab_strip()
            return
        if was_active:
            replacement = self.tabs[min(index, len(self.tabs) - 1)]
            self.active_tab_id = None
            self._switch_tab(replacement["id"])
        else:
            self._refresh_tab_strip()

    def _close_active_tab(self):
        tab = self._active_tab()
        if tab is not None:
            self._close_tab(tab["id"])

    def _sync_fixed_after_scroll(self):
        try:
            self.painter.sync_fixed_to_viewport()
            self.painter.sync_sticky_to_viewport()
        except Exception:
            pass

        if self.js_runtime is not None:
            try:
                self.js_runtime.set_scroll_offset(
                    self.canvas.canvasx(0),
                    self.canvas.canvasy(0),
                )
            except Exception:
                pass

    def _scroll_page_to(self, x=0.0, y=0.0):
        try:
            region = self.canvas.cget("scrollregion")
            parts = [float(v) for v in str(region).split()] if region else []
            if len(parts) == 4:
                left, top, right, bottom = parts
                width = max(1.0, right-left)
                height = max(1.0, bottom-top)
                self.canvas.xview_moveto(max(0.0, min(1.0, float(x)/width)))
                self.canvas.yview_moveto(max(0.0, min(1.0, float(y)/height)))
                self._sync_fixed_after_scroll()
        except Exception:
            pass

    def _scroll_yview(self, *args):
        self.canvas.yview(*args)
        self._sync_fixed_after_scroll()

    def _on_mousewheel(self, event):
        if self._embedded_mode:
            # Native Chromium receives wheel input directly. Software Chromium
            # has its own canvas binding and forwards the event through CDP.
            return None
        self.canvas.yview_scroll(
            int(-event.delta / 120),
            "units",
        )
        self._sync_fixed_after_scroll()
        return "break"

    def _is_embedded_compat_url(self, url):
        """v6.0: every navigable page is Chromium-backed."""
        try:
            scheme = (urlsplit(str(url)).scheme or "").lower()
        except Exception:
            return False
        return scheme in {"http", "https", "file", "data", "about"}

    def _ensure_dwm_host(self):
        """Create a raw Win32 top-level popup for DWM thumbnail presentation.

        Tk's Windows wrapper hierarchy can expose a ``TkTopLevel`` HWND that
        still carries ``WS_CHILD``.  DwmRegisterThumbnail rejects that handle,
        so the DWM destination is deliberately created outside Tk as a genuine
        WS_POPUP owned by Tekzite's real root HWND.
        """
        if os.name != "nt":
            return 0
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if self._dwm_host:
                try:
                    if user32.IsWindow(wintypes.HWND(int(self._dwm_host))):
                        return int(self._dwm_host)
                except Exception:
                    pass

            self.root.update_idletasks()
            inner = int(self.root.winfo_id())
            GA_ROOT = 2
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            owner = int(user32.GetAncestor(wintypes.HWND(inner), GA_ROOT) or inner)

            WS_POPUP = 0x80000000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            hwnd = user32.CreateWindowExW(
                WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                "STATIC", "Tekzite DWM Surface", WS_POPUP,
                0, 0, 1, 1,
                wintypes.HWND(owner), None, None, None,
            )
            hwnd_i = int(hwnd or 0)
            if not hwnd_i:
                raise OSError(ctypes.get_last_error(), "CreateWindowExW failed for Tekzite DWM host")

            # Make only the presentation popup hit-test transparent.  Mouse
            # input then lands on the existing Tk Chromium surface beneath it,
            # where Tekzite's CDP forwarding bindings already live.
            GWLP_WNDPROC = -4
            WM_NCHITTEST = 0x0084
            WM_MOUSEACTIVATE = 0x0021
            HTTRANSPARENT = -1
            MA_NOACTIVATE = 3
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.CallWindowProcW.restype = LRESULT
            old_proc = int(user32.GetWindowLongPtrW(wintypes.HWND(hwnd_i), GWLP_WNDPROC))

            @WNDPROC
            def _dwm_host_proc(h, msg, wp, lp):
                if msg == WM_NCHITTEST:
                    return HTTRANSPARENT
                if msg == WM_MOUSEACTIVATE:
                    return MA_NOACTIVATE
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc), h, msg, wp, lp)

            user32.SetWindowLongPtrW(
                wintypes.HWND(hwnd_i), GWLP_WNDPROC,
                ctypes.cast(_dwm_host_proc, ctypes.c_void_p).value,
            )
            self._dwm_host_wndproc = _dwm_host_proc
            self._dwm_host_original_wndproc = old_proc
            self._dwm_host = hwnd_i
            self._dwm_host_size = (1, 1)
            self._dwm_host_visible = False
            self._dwm_host_rect = None
            return hwnd_i
        except Exception:
            self._dwm_host = None
            self._dwm_host_size = (1, 1)
            raise

    def _sync_dwm_host_geometry(self, show=False, transparent=False):
        """Pin the raw DWM destination over Tekzite's content viewport.

        v6.1 keeps this operation cheap during window dragging: geometry-only
        moves never touch Chromium, z-order is preserved, and ShowWindow is
        called only when the visibility state actually changes.
        """
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd = int(self._ensure_dwm_host())
            # Do not call update_idletasks() here. During an interactive window
            # drag that can recursively generate more Configure traffic and make
            # the DWM surface visibly chase the Tk window. Callers that need an
            # initial layout settle do so before scheduling this sync.
            x = int(self.content_frame.winfo_rootx())
            y = int(self.content_frame.winfo_rooty())
            w = max(1, int(self.content_frame.winfo_width()))
            h = max(1, int(self.content_frame.winfo_height()))
            rect = (x, y, w, h)
            if rect != self._dwm_host_rect:
                SWP_NOACTIVATE = 0x0010
                SWP_NOOWNERZORDER = 0x0200
                SWP_NOZORDER = 0x0004
                user32.SetWindowPos(
                    wintypes.HWND(hwnd), wintypes.HWND(0), x, y, w, h,
                    SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOZORDER,
                )
                self._dwm_host_rect = rect
            self._dwm_host_size = (w, h)

            # Startup rule: the raw DWM destination remains completely hidden
            # until _show_embedded_host marks the Chromium surface ready.
            should_show = bool(show and self._dwm_surface_ready)
            if should_show and not self._dwm_host_visible:
                SW_SHOWNOACTIVATE = 4
                user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                self._dwm_host_visible = True
            elif not should_show and not self._dwm_surface_ready and self._dwm_host_visible:
                SW_HIDE = 0
                user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
                self._dwm_host_visible = False
            return (w, h)
        except Exception:
            return None

    def _schedule_dwm_geometry_sync(self, resize=False, delay=16):
        """Coalesce DWM move/resize events to roughly one update per frame."""
        if not self._embedded_mode or not self._chromium_dwm_mode:
            return
        self._dwm_pending_resize = bool(self._dwm_pending_resize or resize)
        if self._dwm_geometry_after_id is not None:
            return

        def _flush():
            self._dwm_geometry_after_id = None
            do_resize = bool(self._dwm_pending_resize)
            self._dwm_pending_resize = False
            self._sync_dwm_host_geometry(show=True, transparent=False)
            if do_resize:
                try:
                    w = max(1, int(self.edge_host.winfo_width()))
                    h = max(1, int(self.edge_host.winfo_height()))
                    viewport = (w, h)
                    if viewport != self._dwm_last_chromium_viewport:
                        resize_embedded_chromium(w, h)
                        self._dwm_last_chromium_viewport = viewport
                except Exception:
                    pass

        try:
            self._dwm_geometry_after_id = self.root.after(max(1, int(delay)), _flush)
        except Exception:
            self._dwm_geometry_after_id = None

    def _hide_dwm_host(self):
        self._chromium_dwm_mode = False
        self._dwm_surface_ready = False
        self._dwm_host_visible = False
        if self._dwm_geometry_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_geometry_after_id)
            except Exception:
                pass
            self._dwm_geometry_after_id = None
        self._dwm_pending_resize = False
        if os.name != "nt" or not self._dwm_host:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            SW_HIDE = 0
            user32.ShowWindow(wintypes.HWND(int(self._dwm_host)), SW_HIDE)
        except Exception:
            pass

    def _show_native_canvas(self):
        if not self._embedded_mode and not self._chromium_software_mode:
            return
        self._embedded_mode = False
        self._chromium_software_mode = False
        self._hide_dwm_host()
        self._chromium_frame_generation += 1
        self._chromium_last_frame_signature = None
        self._chromium_frame_source_size = None
        self._chromium_frame_display_size = None
        self._chromium_viewport_size = None
        self._chromium_pending_viewport_size = None
        if self._chromium_viewport_after_id is not None:
            try:
                self.root.after_cancel(self._chromium_viewport_after_id)
            except Exception:
                pass
            self._chromium_viewport_after_id = None
        self._chromium_pending_motion = None
        if self._chromium_motion_after_id is not None:
            try:
                self.root.after_cancel(self._chromium_motion_after_id)
            except Exception:
                pass
            self._chromium_motion_after_id = None
        try:
            self.edge_host.pack_forget()
            self.chromium_surface.pack_forget()
        except Exception:
            pass
        if not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y")
        if not self.canvas.winfo_ismapped():
            self.canvas.pack(side="left", fill="both", expand=True)

    def _use_chromium_software_surface_for_url(self, url):
        """Return True only when the user explicitly selects diagnostic software mode.

        v4.68 stops auto-selecting the screenshot/CDP presentation for Startpage
        or any other normal site.  That path necessarily adds Python capture,
        decode and input-forwarding latency.  Native GPU-backed Chromium is the
        normal interactive presentation; software mode is retained only for
        troubleshooting systems where the native compositor cannot present.
        """
        mode = str(getattr(self, "preferences", DEFAULT_PREFERENCES).get(
            "chromium_presentation", "native"
        )).strip().lower()
        return mode == "software"

    def _show_chromium_software_surface(self, target_id=None):
        self._hide_dwm_host()
        set_embedded_chromium_presentation("software", target_id)
        self._embedded_mode = True
        self._chromium_software_mode = True
        self._chromium_frame_target_id = target_id
        self._chromium_frame_generation += 1
        generation = self._chromium_frame_generation
        try:
            self.canvas.pack_forget()
            self.scrollbar.pack_forget()
            self.edge_host.pack_forget()
        except Exception:
            pass
        if not self.chromium_surface.winfo_ismapped():
            self.chromium_surface.pack(fill="both", expand=True)
        self.chromium_surface.focus_set()
        self.root.update_idletasks()
        self._chromium_last_frame_signature = None
        self._chromium_frame_source_size = None
        self._chromium_frame_display_size = None
        self._chromium_pending_viewport_size = None
        if self._chromium_viewport_after_id is not None:
            try:
                self.root.after_cancel(self._chromium_viewport_after_id)
            except Exception:
                pass
            self._chromium_viewport_after_id = None
        initial_w = max(1, int(self.chromium_surface.winfo_width()))
        initial_h = max(1, int(self.chromium_surface.winfo_height()))
        if self._chromium_viewport_is_sane(initial_w, initial_h):
            self._chromium_viewport_size = (initial_w, initial_h)
        elif not self._chromium_viewport_size:
            # The surface can briefly report 1x1 just after packing. Do not let
            # that become Chromium's responsive viewport. The first sane
            # <Configure> event will establish the latch.
            self._chromium_viewport_size = None
        self._mark_chromium_interaction(2.0)
        self.status_var.set("Chromium light surface")
        self.root.after(0, self._request_chromium_software_frame, generation)

    def _chromium_viewport_is_sane(self, width, height):
        try:
            return (
                int(width) >= int(self._chromium_viewport_min_width)
                and int(height) >= int(self._chromium_viewport_min_height)
            )
        except Exception:
            return False

    def _current_chromium_software_viewport(self):
        """Return the stable software viewport, never a transient Tk size."""
        size = self._chromium_viewport_size
        if size and self._chromium_viewport_is_sane(*size):
            return (int(size[0]), int(size[1]))
        w = max(1, int(self.chromium_surface.winfo_width()))
        h = max(1, int(self.chromium_surface.winfo_height()))
        if self._chromium_viewport_is_sane(w, h):
            self._chromium_viewport_size = (w, h)
            return (w, h)
        # If Tk is still negotiating geometry, keep the last displayed frame's
        # sane source dimensions rather than pushing 1x1/partial metrics to CDP.
        if self._chromium_frame_source_size and self._chromium_viewport_is_sane(*self._chromium_frame_source_size):
            return tuple(map(int, self._chromium_frame_source_size))
        return None

    def _commit_chromium_software_viewport(self):
        self._chromium_viewport_after_id = None
        if not self._chromium_software_mode:
            self._chromium_pending_viewport_size = None
            return
        candidate = self._chromium_pending_viewport_size
        self._chromium_pending_viewport_size = None
        if not candidate or not self._chromium_viewport_is_sane(*candidate):
            return
        candidate = (int(candidate[0]), int(candidate[1]))
        if candidate == self._chromium_viewport_size:
            return
        self._chromium_viewport_size = candidate
        self._chromium_last_frame_signature = None
        # Do not invalidate the whole presentation loop or flip presentation
        # mode. The next capture alone applies the new stable CDP metrics.
        self._mark_chromium_interaction(0.8)
        self.root.after(0, self._request_chromium_software_frame, self._chromium_frame_generation)
        # A software fallback caused by a stalled native HWND should be
        # re-tested after a *settled* viewport change.  This is especially
        # important when the user maximizes or enters fullscreen: Chromium's
        # compositor often becomes healthy only after that real resize.
        self._schedule_native_surface_recovery(candidate)

    def _schedule_native_surface_recovery(self, viewport):
        """Retry native presentation after a stable resize of a fallback tab."""
        if not self._chromium_software_mode:
            return
        tab = self._active_tab()
        if not tab or tab.get("presentation") != "software":
            return
        if tab.get("software_fallback_reason") != "visible-surface":
            return
        target_id = tab.get("chromium_target_id")
        if not target_id:
            return
        try:
            viewport = (max(1, int(viewport[0])), max(1, int(viewport[1])))
        except Exception:
            return
        # Never retry repeatedly for the same settled dimensions.  If native
        # still fails, the next *real* resize gets another chance.
        if tuple(tab.get("native_recovery_viewport") or ()) == viewport:
            return
        tab["native_recovery_viewport"] = viewport
        if self._native_recovery_after_id is not None:
            try:
                self.root.after_cancel(self._native_recovery_after_id)
            except Exception:
                pass
        generation = self._navigation_generation
        self._native_recovery_after_id = self.root.after(450,
            self._attempt_native_surface_recovery, generation, target_id, viewport)

    def _attempt_native_surface_recovery(self, generation, target_id, viewport):
        self._native_recovery_after_id = None
        if generation != self._navigation_generation or not self._chromium_software_mode:
            return
        tab = self._active_tab()
        if (not tab or tab.get("chromium_target_id") != target_id or
                tab.get("software_fallback_reason") != "visible-surface"):
            return
        try:
            record_embedded_native_recovery(True, viewport, None)
        except Exception:
            pass
        # Keep the software frame visible until this point; only a settled
        # resize triggers the hand-back. _show_embedded_host clears any CDP
        # device metrics override before native HWND presentation resumes.
        tab["presentation"] = "native-retry"
        try:
            set_embedded_chromium_presentation("native", target_id)
            self._show_embedded_host(recovery=True)
            resize_embedded_chromium(int(viewport[0]), int(viewport[1]))
            # v5.04: a fallback tab may retain the old pre-fullscreen RWH size
            # even after its owner/host grew. During recovery only, synchronize
            # both native levels before judging pixels on screen.
            geometry_ok = sync_embedded_chromium_native_geometry(
                int(viewport[0]), int(viewport[1])
            )
            if not geometry_ok:
                raise RuntimeError("native render host did not reach recovery viewport")
            self._schedule_embedded_surface_wake()
            # Judge the pixels the user can actually see.  The existing probe
            # falls back to software again if the native surface is still flat.
            self.root.after(650, self._probe_visible_embedded_surface,
                            generation, target_id, True, 1)
        except Exception:
            tab["presentation"] = "software"
            tab["software_fallback_reason"] = "visible-surface"
            tab["native_recovery_viewport"] = tuple(viewport)
            # Keep both the tab state and the shared Chromium session on the same
            # authoritative presentation mode before exposing the fallback widget.
            try:
                set_embedded_chromium_presentation("software", target_id)
            except Exception:
                pass
            self._show_chromium_software_surface(target_id)
            try:
                record_embedded_native_recovery(True, viewport, False)
            except Exception:
                pass

    def _mark_chromium_interaction(self, seconds=1.0):
        self._chromium_interaction_until = max(
            float(self._chromium_interaction_until or 0.0),
            time.monotonic() + max(0.1, float(seconds)),
        )

    def _chromium_frame_delay(self):
        if time.monotonic() < float(self._chromium_interaction_until or 0.0):
            return int(self._chromium_active_frame_ms)
        return int(self._chromium_idle_frame_ms)

    def _request_chromium_software_frame(self, generation=None):
        if generation is None:
            generation = self._chromium_frame_generation
        if generation != self._chromium_frame_generation or not self._chromium_software_mode:
            return
        try:
            if str(self.root.state()) == "iconic":
                self.root.after(1000, self._request_chromium_software_frame, generation)
                return
        except Exception:
            pass
        if self._chromium_frame_future is not None and not self._chromium_frame_future.done():
            self.root.after(30, self._request_chromium_software_frame, generation)
            return
        target_id = self._chromium_frame_target_id
        viewport = self._current_chromium_software_viewport()
        if viewport is None:
            # Geometry is still settling. Wait for a sane <Configure> instead of
            # sending a tiny or partial viewport that makes the page reflow.
            self.root.after(40, self._request_chromium_software_frame, generation)
            return
        viewport_width, viewport_height = viewport
        self._chromium_frame_future = self._executor.submit(
            capture_embedded_chromium_frame, 4, target_id, viewport_width, viewport_height
        )
        self.root.after(15, self._poll_chromium_software_frame, generation, self._chromium_frame_future)

    def _poll_chromium_software_frame(self, generation, future):
        if generation != self._chromium_frame_generation or not self._chromium_software_mode:
            return
        if not future.done():
            self.root.after(20, self._poll_chromium_software_frame, generation, future)
            return
        try:
            png = future.result()
            # Do not decode/repaint identical screenshots. Static pages now cost
            # almost nothing between interactions even while the idle health
            # check continues.
            signature = (len(png), hash(png))
            if signature != self._chromium_last_frame_signature:
                image = Image.open(BytesIO(png))
                image.load()
                source_size = (max(1, int(image.size[0])), max(1, int(image.size[1])))
                # Present at the same latched viewport size used for CDP. Do
                # not stretch each frame to transient Tk geometry while a
                # resize is debouncing; that visual stretch was the remaining
                # source of the in/out "zoom" effect. A settled resize commits
                # once, then both Chromium and the displayed frame move together.
                display_size = self._current_chromium_software_viewport() or source_size
                w, h = display_size
                if image.size != display_size:
                    # v4.67 strict frame contract: never stretch a Chromium frame
                    # whose pixel dimensions disagree with the latched viewport.
                    # Showing it would make the page appear to zoom in/out even
                    # though the browser window itself did not resize. Keep the
                    # last known-good frame visible and retry after the CDP side
                    # has re-established the viewport contract.
                    raise RuntimeError(
                        f"rejected Chromium frame {image.size[0]}x{image.size[1]} "
                        f"for viewport {w}x{h}"
                    )
                self._chromium_frame_source_size = source_size
                self._chromium_frame_display_size = display_size
                # v5.08: keep one Tk image and one Canvas item alive while the
                # viewport size is unchanged. ImageTk.PhotoImage.paste() updates
                # the existing Tcl/Tk image in place and avoids allocating a new
                # PhotoImage plus delete/create Canvas churn for every video or
                # scrolling frame.
                reuse_photo = False
                try:
                    reuse_photo = (
                        self._chromium_frame_photo is not None
                        and int(self._chromium_frame_photo.width()) == int(image.size[0])
                        and int(self._chromium_frame_photo.height()) == int(image.size[1])
                    )
                except Exception:
                    reuse_photo = False
                if reuse_photo:
                    self._chromium_frame_photo.paste(image)
                else:
                    self._chromium_frame_photo = ImageTk.PhotoImage(image)
                    if self._chromium_frame_item is not None:
                        try:
                            self.chromium_surface.delete(self._chromium_frame_item)
                        except Exception:
                            pass
                    self._chromium_frame_item = self.chromium_surface.create_image(
                        0, 0, anchor="nw", image=self._chromium_frame_photo, tags=("frame",)
                    )
                    self.chromium_surface.tag_lower(self._chromium_frame_item)
                self._chromium_last_frame_signature = signature
        except Exception as exc:
            self.status_var.set(f"Chromium software frame retry | {exc}")
        finally:
            self._chromium_frame_future = None
        self.root.after(self._chromium_frame_delay(), self._request_chromium_software_frame, generation)

    def _on_chromium_surface_configure(self, event):
        if not self._chromium_software_mode:
            return
        width = max(1, int(getattr(event, "width", 0) or self.chromium_surface.winfo_width()))
        height = max(1, int(getattr(event, "height", 0) or self.chromium_surface.winfo_height()))
        if not self._chromium_viewport_is_sane(width, height):
            return
        candidate = (width, height)
        if candidate == self._chromium_viewport_size:
            return
        self._chromium_pending_viewport_size = candidate
        if self._chromium_viewport_after_id is not None:
            try:
                self.root.after_cancel(self._chromium_viewport_after_id)
            except Exception:
                pass
        self._chromium_viewport_after_id = self.root.after(
            int(self._chromium_viewport_debounce_ms),
            self._commit_chromium_software_viewport,
        )

    def _chromium_input_surface_active(self):
        return bool(self._chromium_software_mode or self._chromium_dwm_mode)

    def _surface_xy(self, event):
        """Translate Tk pointer coordinates into Chromium frame coordinates.

        The software surface may display a CDP frame whose source pixel/CSS
        dimensions differ from Tk's logical canvas size because of Windows DPI
        scaling or a transient resize.  Always use the same transform that was
        used to present the most recent frame so hover/click/context-menu hit
        testing lands on the pixel the user actually points at.
        """
        x = max(0.0, float(getattr(event, "x", 0)))
        y = max(0.0, float(getattr(event, "y", 0)))
        if self._chromium_dwm_mode and self._dwm_host is not None:
            try:
                dw, dh = getattr(self, "_dwm_host_size", (1, 1))
                # The DWM thumbnail is cropped from Chromium's outer app window,
                # but CDP hit testing is relative to the page renderer. v5.36
                # applies the live measured delta between those two origins.
                ox, oy = get_embedded_chromium_dwm_input_offset()
                x += float(ox)
                y += float(oy)
                x = min(max(0.0, x), max(0.0, float(dw) - 1.0))
                y = min(max(0.0, y), max(0.0, float(dh) - 1.0))

                # v7.2: DWM shows Chromium's physical page pixels, while CDP
                # pointer APIs use CSS viewport coordinates. Native browser zoom
                # makes those coordinate spaces diverge (e.g. at 150%, 600
                # visible pixels correspond to about 400 CSS px). Convert every
                # DWM pointer path here so click, focus, hover, cursor probing and
                # context menus all share exactly the same mapping.
                zoom = float(get_embedded_chromium_input_zoom_factor() or 1.0)
                if zoom > 0.0 and abs(zoom - 1.0) > 1e-6:
                    x /= zoom
                    y /= zoom
            except Exception:
                pass
            return x, y
        src = self._chromium_frame_source_size
        dst = self._chromium_frame_display_size
        if src and dst and dst[0] > 0 and dst[1] > 0:
            x *= float(src[0]) / float(dst[0])
            y *= float(src[1]) / float(dst[1])
            # Keep the point inside Chromium's viewport. elementFromPoint() and
            # Input.dispatchMouseEvent both behave better at width-1/height-1
            # than exactly on the exclusive lower/right edge.
            x = min(x, max(0.0, float(src[0]) - 1.0))
            y = min(y, max(0.0, float(src[1]) - 1.0))
        return x, y

    def _submit_chromium_input(self, func, *args, refresh=False, **kwargs):
        """Send software-surface input on a dedicated ordered lane.

        v5.09 deliberately separates input from screenshot work.  When
        ``refresh`` is requested, the Tk thread polls completion and captures a
        frame immediately after Chromium has consumed the event instead of
        relying on a fixed sleep that can race either side of the input.
        """
        try:
            future = self._chromium_input_executor.submit(func, *args, **kwargs)
        except Exception:
            return None
        if refresh:
            generation = self._chromium_frame_generation
            self.root.after(2, self._poll_chromium_input_refresh, future, generation)
        return future

    def _poll_chromium_input_refresh(self, future, generation):
        if generation != self._chromium_frame_generation or not self._chromium_software_mode:
            return
        if future is not None and not future.done():
            self.root.after(4, self._poll_chromium_input_refresh, future, generation)
            return
        # Input has reached Chromium. Request the next visual frame now; the
        # normal single-frame-in-flight guard prevents capture queue buildup.
        self.root.after(0, self._request_chromium_software_frame, generation)

    def _on_chromium_surface_press(self, event):
        if not self._chromium_input_surface_active():
            return None
        try:
            (self.edge_host if self._chromium_dwm_mode else self.chromium_surface).focus_set()
        except Exception:
            pass
        self._address_focus_active = False
        self._chromium_page_keyboard_active = True
        self._cancel_embedded_surface_wakes()
        self._mark_chromium_interaction(1.0)
        x, y = self._surface_xy(event)
        self._chromium_left_button_down = True
        self._chromium_drag_selecting = False
        self._chromium_press_point = (x, y)
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mousePressed", x, y,
            button="left", buttons=1, click_count=1,
            target_id=self._chromium_frame_target_id,
        )
        return "break"

    def _on_chromium_surface_release(self, event):
        if not self._chromium_input_surface_active():
            return None
        self._mark_chromium_interaction(1.0)
        x, y = self._surface_xy(event)
        was_drag = bool(self._chromium_drag_selecting)
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseReleased", x, y,
            button="left", buttons=0, click_count=1,
            target_id=self._chromium_frame_target_id, refresh=True,
        )
        self._chromium_left_button_down = False
        self._chromium_drag_selecting = False
        self._chromium_press_point = None
        # A plain click still gets the explicit editable-focus bridge. During a
        # drag selection, however, focusing the release point can collapse the
        # selection, especially inside input/textarea controls.
        if not was_drag:
            self._submit_chromium_input(
                focus_embedded_chromium_point, x, y,
                target_id=self._chromium_frame_target_id,
            )
        return "break"

    def _on_chromium_surface_drag(self, event):
        """Forward a held-left-button pointer drag to Chromium.

        DWM is only a visual mirror, so Windows cannot deliver Chromium's
        native selection gesture by itself. Keep the press/move/release gesture
        intact over CDP, with the v7.2 zoom-aware coordinate transform, so the
        renderer performs normal text selection and input-field selection.
        """
        if not self._chromium_input_surface_active() or not self._chromium_left_button_down:
            return None
        x, y = self._surface_xy(event)
        start = self._chromium_press_point
        if start is not None:
            dx = float(x) - float(start[0])
            dy = float(y) - float(start[1])
            if (dx * dx + dy * dy) >= 4.0:
                self._chromium_drag_selecting = True
        self._mark_chromium_interaction(0.6)
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseMoved", x, y,
            button="left", buttons=1, click_count=1,
            target_id=self._chromium_frame_target_id,
        )
        self._chromium_cursor_point = (x, y)
        return "break"

    def _on_chromium_surface_motion(self, event):
        if not self._chromium_input_surface_active():
            return None
        self._chromium_pending_motion = self._surface_xy(event)
        self._mark_chromium_interaction(0.45)
        if self._chromium_motion_after_id is None:
            self._chromium_motion_after_id = self.root.after(
                self._chromium_motion_interval_ms, self._flush_chromium_surface_motion
            )
        return None

    def _flush_chromium_surface_motion(self):
        self._chromium_motion_after_id = None
        if not self._chromium_input_surface_active():
            self._chromium_pending_motion = None
            return
        motion = self._chromium_pending_motion
        self._chromium_pending_motion = None
        if motion is None:
            return
        x, y = motion
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseMoved", x, y,
            target_id=self._chromium_frame_target_id
        )
        self._chromium_cursor_point = (x, y)
        self._request_chromium_cursor_probe()

    @staticmethod
    def _tk_cursor_for_css(css_cursor):
        value = str(css_cursor or "auto").strip().lower()
        mapping = {
            "pointer": "hand2",
            "text": "xterm",
            "vertical-text": "xterm",
            "crosshair": "crosshair",
            "move": "fleur",
            "all-scroll": "fleur",
            "col-resize": "sb_h_double_arrow",
            "ew-resize": "sb_h_double_arrow",
            "e-resize": "sb_h_double_arrow",
            "w-resize": "sb_h_double_arrow",
            "row-resize": "sb_v_double_arrow",
            "ns-resize": "sb_v_double_arrow",
            "n-resize": "sb_v_double_arrow",
            "s-resize": "sb_v_double_arrow",
            "wait": "watch",
            "progress": "watch",
            "help": "question_arrow",
            "not-allowed": "X_cursor",
            "no-drop": "X_cursor",
            "grab": "hand2",
            "grabbing": "hand2",
            "copy": "plus",
            "zoom-in": "crosshair",
            "zoom-out": "crosshair",
            "default": "arrow",
            "auto": "arrow",
        }
        return mapping.get(value, "arrow")

    def _apply_chromium_cursor(self, css_cursor):
        cursor = self._tk_cursor_for_css(css_cursor)
        if cursor == self._chromium_cursor_name:
            return
        self._chromium_cursor_name = cursor
        widget = self.edge_host if self._chromium_dwm_mode else self.chromium_surface
        try:
            widget.configure(cursor=cursor)
        except tk.TclError:
            # Some Tk builds do not expose every Windows cursor name. Fall
            # back to the regular arrow rather than letting cursor sync fail.
            self._chromium_cursor_name = "arrow"
            try:
                widget.configure(cursor="arrow")
            except Exception:
                pass

    def _request_chromium_cursor_probe(self):
        if not self._chromium_input_surface_active():
            return
        if self._chromium_cursor_future is not None and not self._chromium_cursor_future.done():
            return
        point = self._chromium_cursor_point
        if point is None:
            return
        x, y = point
        try:
            self._chromium_cursor_future = self._chromium_input_executor.submit(
                get_embedded_chromium_cursor, x, y,
                target_id=self._chromium_frame_target_id,
            )
        except Exception:
            self._chromium_cursor_future = None
            return
        self.root.after(4, self._poll_chromium_cursor_probe)

    def _poll_chromium_cursor_probe(self):
        future = self._chromium_cursor_future
        if future is None:
            return
        if not future.done():
            self.root.after(4, self._poll_chromium_cursor_probe)
            return
        self._chromium_cursor_future = None
        try:
            value = future.result() or "auto"
        except Exception:
            value = "auto"
        self._apply_chromium_cursor(value)
        # If the pointer moved while this probe was running, immediately probe
        # the latest coalesced point rather than replaying every intermediate one.
        if self._chromium_pending_motion is not None:
            return

    def _on_chromium_surface_leave(self, _event=None):
        self._chromium_cursor_point = None
        self._apply_chromium_cursor("default")
        return None

    def _on_chromium_surface_wheel(self, event):
        if not self._chromium_input_surface_active():
            return None
        self._mark_chromium_interaction(1.0)
        x, y = self._surface_xy(event)
        delta = -float(getattr(event, "delta", 0) or 0)
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseWheel", x, y,
            delta_y=delta, target_id=self._chromium_frame_target_id,
            refresh=True,
        )
        return "break"

    def _on_root_chromium_key(self, event):
        """Fallback keyboard lane for DWM presentation.

        Tk can leave focus on the toplevel after a click through the transparent
        DWM host. When the last pointer click belonged to the page, keep routing
        keys to Chromium unless Tekzite's address bar is actively editing.
        """
        if not (self._chromium_dwm_mode and self._chromium_page_keyboard_active):
            return None
        try:
            if self._address_focus_active or self.root.focus_get() is self.address:
                return None
            if self.root.focus_get() is self.edge_host:
                # edge_host's own binding already handles this event.
                return None
        except Exception:
            if self._address_focus_active:
                return None
        return self._on_chromium_surface_key(event)

    def _on_chromium_surface_key(self, event):
        if not self._chromium_input_surface_active():
            return None
        self._mark_chromium_interaction(1.0)
        char = getattr(event, "char", "") or ""
        keysym = getattr(event, "keysym", "") or ""
        state = int(getattr(event, "state", 0) or 0)

        # Tk modifier masks -> CDP Input modifier bits.
        shift = bool(state & 0x0001)
        control = bool(state & 0x0004)
        alt = bool(state & 0x0008)
        modifiers = (8 if shift else 0) | (2 if control else 0) | (1 if alt else 0)

        # Ordinary text goes through Input.insertText so IME/layout differences
        # between Tk and Chromium do not corrupt what the user typed. Modified
        # printable keys are dispatched as real key events for Ctrl+C/V/A etc.
        if char and char.isprintable() and not (control or alt):
            self._submit_chromium_input(
                dispatch_embedded_chromium_key, text=char, event_type="insertText",
                target_id=self._chromium_frame_target_id, refresh=True,
            )
            return "break"

        mapping = {
            "Return": ("Enter", "Enter", 13), "BackSpace": ("Backspace", "Backspace", 8),
            "Tab": ("Tab", "Tab", 9), "Escape": ("Escape", "Escape", 27),
            "Delete": ("Delete", "Delete", 46), "Left": ("ArrowLeft", "ArrowLeft", 37),
            "Up": ("ArrowUp", "ArrowUp", 38), "Right": ("ArrowRight", "ArrowRight", 39),
            "Down": ("ArrowDown", "ArrowDown", 40), "Home": ("Home", "Home", 36),
            "End": ("End", "End", 35), "Prior": ("PageUp", "PageUp", 33),
            "Next": ("PageDown", "PageDown", 34), "space": (" ", "Space", 32),
        }
        if len(keysym) == 1 and keysym.isalpha():
            upper = keysym.upper()
            mapping[keysym] = (upper.lower() if not shift else upper, f"Key{upper}", ord(upper))

        if keysym in mapping:
            key, code, vk = mapping[keysym]
            self._submit_chromium_input(
                dispatch_embedded_chromium_key, key, event_type="keyDown",
                modifiers=modifiers, windows_vk=vk, code=code,
                target_id=self._chromium_frame_target_id,
            )
            self._submit_chromium_input(
                dispatch_embedded_chromium_key, key, event_type="keyUp",
                modifiers=modifiers, windows_vk=vk, code=code,
                target_id=self._chromium_frame_target_id, refresh=True,
            )
        return "break"

    def _clipboard_set(self, text):
        value = str(text or "")
        if not value:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.root.update_idletasks()
        except Exception:
            pass

    def _context_menu_base(self):
        menu = tk.Menu(
            self.root, tearoff=False, bg=self.ui["chrome_2"], fg=self.ui["text"],
            activebackground=self.ui["field_focus"], activeforeground="#ffffff",
            bd=0, relief="flat", font=(self._ui_font_family, 9),
        )
        menu.add_command(label="Back", command=self.go_back)
        menu.add_command(label="Forward", command=self.go_forward)
        menu.add_command(label="Reload", command=self._reload_current)
        menu.add_separator()
        return menu

    def _finish_page_context_menu(self, menu, *, link_url="", selected_text="", image_url="", editable=False):
        link_url = str(link_url or "")
        selected_text = str(selected_text or "")
        image_url = str(image_url or "")
        if link_url:
            menu.insert_command(0, label="Open Link", command=lambda u=link_url: self.navigate_to(u))
            menu.insert_command(1, label="Open Link in New Tab", command=lambda u=link_url: self._new_tab(url=u, switch=True, navigate=True))
            menu.insert_command(2, label="Copy Link Address", command=lambda u=link_url: self._clipboard_set(u))
            menu.insert_separator(3)
        if selected_text:
            menu.add_command(label="Copy Selected Text", command=lambda t=selected_text: self._clipboard_set(t))
        if image_url:
            menu.add_command(label="Copy Image Address", command=lambda u=image_url: self._clipboard_set(u))
        if selected_text or image_url:
            menu.add_separator()
        if editable:
            menu.add_command(label="Cut", command=lambda: self._edit_shortcut("x"))
            menu.add_command(label="Copy", command=lambda: self._edit_shortcut("c"))
            menu.add_command(label="Paste", command=lambda: self._edit_shortcut("v"))
            menu.add_separator()
        menu.add_command(label="Home", command=self._go_home)
        menu.add_command(label="Copy Page URL", command=lambda: self._clipboard_set(self.url_var.get()))
        menu.add_command(label="Inspect HTML", command=self.inspect_html)
        return menu

    def _popup_context_menu(self, menu, event):
        try:
            menu.tk_popup(int(event.x_root), int(event.y_root))
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _native_link_at_event(self, event):
        try:
            current = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
            for item_id in reversed(current):
                for tag in self.canvas.gettags(item_id):
                    if tag.startswith("link_") or tag.startswith("image_link_"):
                        href = self.painter.link_targets.get(tag)
                        if href:
                            return href
            x = float(self.canvas.canvasx(event.x))
            y = float(self.canvas.canvasy(event.y))
            region = self.painter._region_at(x, y)
            if region is not None and getattr(region, "href", None):
                return region.href
        except Exception:
            pass
        return ""

    def _screen_cursor_position(self, event=None):
        """Return the real Windows screen cursor position for popup placement.

        Tk root coordinates can be stale/wrong when the visible DWM thumbnail
        sits over a separate input plane, so prefer GetCursorPos on Windows.
        """
        if sys.platform.startswith("win"):
            try:
                import ctypes
                from ctypes import wintypes
                class POINT(ctypes.Structure):
                    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
                pt = POINT()
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
                user32.GetCursorPos.restype = wintypes.BOOL
                if user32.GetCursorPos(ctypes.byref(pt)):
                    return int(pt.x), int(pt.y)
            except Exception:
                pass
        if event is not None:
            try:
                return int(event.x_root), int(event.y_root)
            except Exception:
                pass
        return 0, 0

    def _on_native_context_menu(self, event):
        menu = self._context_menu_base()
        self._finish_page_context_menu(menu, link_url=self._native_link_at_event(event))
        self._popup_context_menu(menu, event)
        return "break"

    def _on_chromium_surface_context_menu(self, event):
        if not self._chromium_input_surface_active():
            return None
        try:
            (self.edge_host if self._chromium_dwm_mode else self.chromium_surface).focus_set()
        except Exception:
            pass
        self._address_focus_active = False
        self._cancel_embedded_surface_wakes()
        # v5.41: Chromium must never receive a native right-click gesture in
        # DWM/native presentation. Tekzite can resolve link/image/editable/
        # selection context directly with elementFromPoint(), so dispatching a
        # right mouse button event only causes Chromium's own context menu to
        # appear behind/on top of Tekzite. Keep the browser-style menu fully
        # Tekzite-owned.
        x, y = self._surface_xy(event)
        target_id = self._chromium_frame_target_id
        # Ask Chromium what is under the pointer without blocking Tk. The menu
        # appears as soon as the tiny Runtime.evaluate call completes.
        root_x, root_y = self._screen_cursor_position(event)
        future = self._executor.submit(
            get_embedded_chromium_context, x, y, target_id=target_id
        )

        def poll():
            if not future.done():
                self.root.after(15, poll)
                return
            try:
                info = future.result() or {}
            except Exception:
                info = {}
            menu = self._context_menu_base()
            self._finish_page_context_menu(
                menu,
                link_url=info.get("href", ""),
                selected_text=info.get("selected_text", ""),
                image_url=info.get("image_src", ""),
                editable=bool(info.get("editable")),
            )
            class PopupEvent: pass
            popup = PopupEvent()
            popup.x_root, popup.y_root = root_x, root_y
            self._popup_context_menu(menu, popup)

        self.root.after(0, poll)
        return "break"

    def _cancel_embedded_surface_wakes(self):
        """Cancel delayed native Chromium focus retries.

        Once the user enters Tekzite chrome (especially the omnibox), an old
        wake callback must not call SetFocus() back into Chromium a few
        milliseconds later.
        """
        ids = list(getattr(self, "_embedded_wake_after_ids", []) or [])
        self._embedded_wake_after_ids = []
        for after_id in ids:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass

    def _on_address_pointer_down(self, event=None):
        self._address_focus_active = True
        self._chromium_page_keyboard_active = False
        self._cancel_embedded_surface_wakes()
        try:
            self.root.focus_force()
        except Exception:
            pass
        return None

    def _on_address_focus_in(self, event=None):
        self._address_focus_active = True
        self._chromium_page_keyboard_active = False
        self._cancel_embedded_surface_wakes()

    def _on_address_focus_out(self, event=None):
        self._address_focus_active = False

    def _schedule_embedded_pointer_focus_watch(self):
        """Watch native Chromium mouse-downs that Tk cannot see.

        SetParent() embeds Chromium visually, but its render HWND belongs to a
        different process/thread. A click therefore does not traverse Tk's
        <Button-1> bindings. On Windows we sample the physical left mouse
        button and WindowFromPoint; when the press begins inside edge_host we
        explicitly focus Chromium's real render HWND.
        """
        try:
            if self._embedded_focus_watch_after_id is not None:
                self.root.after_cancel(self._embedded_focus_watch_after_id)
        except Exception:
            pass
        try:
            self._embedded_focus_watch_after_id = self.root.after(15, self._poll_embedded_pointer_focus)
        except Exception:
            self._embedded_focus_watch_after_id = None

    def _poll_embedded_pointer_focus(self):
        self._embedded_focus_watch_after_id = None
        pressed = False
        try:
            if os.name == "nt" and self._embedded_mode and not self._chromium_dwm_mode and self.edge_host.winfo_ismapped():
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32

                class POINT(ctypes.Structure):
                    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

                user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
                user32.GetAsyncKeyState.restype = ctypes.c_short
                user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
                user32.GetCursorPos.restype = wintypes.BOOL
                user32.WindowFromPoint.argtypes = [POINT]
                user32.WindowFromPoint.restype = wintypes.HWND
                user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
                user32.IsChild.restype = wintypes.BOOL

                VK_LBUTTON = 0x01
                pressed = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
                if pressed and not self._embedded_pointer_button_down:
                    pt = POINT()
                    if user32.GetCursorPos(ctypes.byref(pt)):
                        hit = user32.WindowFromPoint(pt)
                        host = wintypes.HWND(int(self.edge_host.winfo_id()))
                        if hit and (int(hit) == int(host.value or 0) or user32.IsChild(host, hit)):
                            # v4.89: record the click, but DO NOT call SetFocus
                            # while the physical button is down. Chromium must
                            # receive its native mousePressed + mouseReleased pair
                            # without Tekzite joining input queues in between.
                            self._address_focus_active = False
                            self._cancel_embedded_surface_wakes()
                            self._embedded_pointer_focus_pending = True

                # Run the narrow focus bridge only after the physical release.
                # This keeps transient DOM popup triggers (YouTube profile,
                # notifications, account menus, etc.) on Chromium's own input
                # path for the entire click gesture.
                if (not pressed and self._embedded_pointer_button_down
                        and self._embedded_pointer_focus_pending):
                    self._embedded_pointer_focus_pending = False
                    try:
                        self.root.after(0, self._focus_embedded_surface_for_pointer)
                        # v4.96: consent/auth clicks can swap Chromium's compositor
                        # surface and leave a valid-but-black PNG/native frame. Probe
                        # after the click has completed, off the Tk thread, and only
                        # wake/re-prime when two captures confirm a blank surface.
                        tab = self._active_tab()
                        target_id = tab.get("chromium_target_id") if tab else None
                        self._executor.submit(
                            validate_and_recover_embedded_chromium_frame, target_id
                        )
                    except Exception:
                        pass
        except Exception:
            pressed = False
        finally:
            self._embedded_pointer_button_down = bool(pressed)
            try:
                self._embedded_focus_watch_after_id = self.root.after(15, self._poll_embedded_pointer_focus)
            except Exception:
                self._embedded_focus_watch_after_id = None

    def _release_address_focus_for_navigation(self):
        """Release omnibox ownership once its URL has been committed."""
        self._address_focus_active = False
        self._cancel_embedded_surface_wakes()
        try:
            self.root.focus_set()
        except Exception:
            pass

    def _focus_embedded_surface_for_pointer(self):
        if self._chromium_dwm_mode:
            return False
        if self._chromium_dwm_mode:
            return False
        """Give a physically clicked Chromium page keyboard focus only.

        A real pointer press already activates/repaints Chromium as needed. The
        full wake path is intentionally avoided here because it pulses native
        activation, reapplies crop geometry and redraws the child HWND. Doing
        that between mouse-down and mouse-up can make transient controls such
        as account/profile menus miss their click.

        This lightweight path preserves the v4.83 form-focus fix while leaving
        the native click sequence undisturbed.
        """
        if not self._embedded_mode:
            return False
        try:
            if self._address_focus_active or self.root.focus_get() is self.address:
                return False
        except Exception:
            if self._address_focus_active:
                return False
        try:
            return bool(focus_embedded_chromium())
        except Exception:
            return False

    def _focus_embedded_surface(self):
        """Wake and focus the merged Chromium page surface.

        A native title-bar click activates the Tk top-level window *and* causes
        Windows to repaint/re-focus the embedded Chromium child.  Do the same
        thing explicitly so a freshly loaded compatibility page appears
        without the user having to click the frame.
        """
        if not self._embedded_mode:
            return False
        # v4.80: Chromium may only reclaim focus while Tekzite chrome is not
        # actively being edited. This also protects against delayed wake
        # callbacks queued by navigation/resize before the address was clicked.
        try:
            if self._address_focus_active or self.root.focus_get() is self.address:
                return False
        except Exception:
            if self._address_focus_active:
                return False
        try:
            self.root.focus_force()
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            # Wake does activation + repaint + geometry refresh.  The explicit
            # focus call afterwards is kept as a narrow fallback for older
            # Chromium/Windows combinations.
            woke = bool(wake_embedded_chromium())
            focused = bool(focus_embedded_chromium())
            return woke or focused
        except Exception:
            return False

    def _schedule_embedded_surface_wake(self):
        if self._chromium_dwm_mode:
            return False
        """Retry native activation while Chromium finishes creating its view.

        v4.80 keeps exactly one cancellable retry set. Entering the omnibox
        cancels it, preventing a stale retry from stealing keyboard focus.
        """
        if not self._embedded_mode or self._address_focus_active:
            return
        self._cancel_embedded_surface_wakes()
        self._focus_embedded_surface()
        for delay in (35, 90, 180, 360):
            try:
                after_id = self.root.after(delay, self._focus_embedded_surface)
                self._embedded_wake_after_ids.append(after_id)
            except Exception:
                pass

    def _show_embedded_host(self, recovery=False):
        tab = self._active_tab()
        # v5.10: a visible-surface fallback is authoritative. Ordinary UI,
        # tab-switch and navigation callbacks must never silently reactivate the
        # known-bad native HWND after software fallback. Only the explicit native
        # recovery path may temporarily cross this guard.
        if (not recovery and tab and
                tab.get("software_fallback_reason") == "visible-surface"):
            target_id = tab.get("chromium_target_id")
            tab["presentation"] = "software"
            try:
                set_embedded_chromium_presentation("software", target_id)
            except Exception:
                pass
            if not self._chromium_software_mode or self._chromium_frame_target_id != target_id:
                self._show_chromium_software_surface(target_id)
            return False
        set_embedded_chromium_presentation("native", tab.get("chromium_target_id") if tab else None)
        self._chromium_frame_target_id = tab.get("chromium_target_id") if tab else None
        self._embedded_mode = True
        self._chromium_software_mode = False
        self._chromium_dwm_mode = True
        self._chromium_frame_generation += 1
        try:
            self.canvas.pack_forget()
            self.scrollbar.pack_forget()
            self.chromium_surface.pack_forget()
        except Exception:
            pass
        if not self.edge_host.winfo_ismapped():
            self.edge_host.pack(fill="both", expand=True)
        self.root.update_idletasks()
        # v6.1: position the DWM destination while it is still hidden. The
        # surface is revealed only after Chromium has received its real viewport.
        self._dwm_surface_ready = False
        self._sync_dwm_host_geometry(show=False, transparent=False)
        # v4.63: the HWND may have existed as a 1x1 unmapped Tk placeholder
        # while Chromium was prepared off-screen.  Once the host is actually
        # mapped, immediately push its real viewport into Chromium instead of
        # waiting for a later <Configure> event that may never arrive.
        host_w = max(1, int(self.edge_host.winfo_width()))
        host_h = max(1, int(self.edge_host.winfo_height()))
        resize_embedded_chromium(host_w, host_h)
        self._dwm_last_chromium_viewport = (host_w, host_h)
        # The open/navigation future only reaches this point after Chromium has
        # produced a usable frame. Reveal the DWM host now, never before.
        self._dwm_surface_ready = True
        self._sync_dwm_host_geometry(show=True, transparent=False)
        self.root.after_idle(lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))
        try:
            (self.edge_host if self._chromium_dwm_mode else self.chromium_surface).focus_set()
        except Exception:
            pass
        return True

    def _on_edge_host_configure(self, event):
        if not self._embedded_mode:
            return
        if self._chromium_dwm_mode:
            # Size changes need a Chromium viewport update, but coalesce the
            # noisy Tk Configure burst into one ~60 Hz operation.
            self._schedule_dwm_geometry_sync(resize=True, delay=16)
            return
        resize_embedded_chromium(
            max(1, int(getattr(event, "width", 1))),
            max(1, int(getattr(event, "height", 1))),
        )

    def _on_root_configure_native_overlay(self, event=None):
        if not self._embedded_mode or self._chromium_software_mode:
            return
        try:
            if getattr(event, "widget", self.root) is not self.root:
                return
            if self._chromium_dwm_mode:
                # A pure top-level move does not resize Chromium. Only slide the
                # transparent DWM destination along with Tekzite.
                self._schedule_dwm_geometry_sync(resize=False, delay=16)
                return
            self.root.after_idle(
                lambda: resize_embedded_chromium(
                    max(1, int(self.edge_host.winfo_width())),
                    max(1, int(self.edge_host.winfo_height())),
                )
            )
        except Exception:
            pass

    def _probe_visible_embedded_surface(self, generation, target_id, cdp_visual, attempt=1):
        """Verify that the *screen-visible* native Chromium surface actually presents pixels.

        CDP can capture a healthy compositor frame while a re-parented Win32 Chromium
        child shows only Tekzite's gray host.  Probe the final on-screen host after attach.
        A near-uniform visible surface, combined with a known-good CDP frame, means the
        native presentation path stalled rather than the web page itself. v5.11 keeps
        that tab native and uses this probe only to drive native recovery/diagnostics.
        """
        if generation != self._navigation_generation or not self._embedded_mode:
            return
        if self._chromium_software_mode or not cdp_visual:
            return
        tab = self._active_tab()
        if tab is None or tab.get("chromium_target_id") != target_id:
            return
        try:
            self.root.update_idletasks()
            x = int(self.edge_host.winfo_rootx())
            y = int(self.edge_host.winfo_rooty())
            w = int(self.edge_host.winfo_width())
            h = int(self.edge_host.winfo_height())
            if w < 240 or h < 160:
                return
            # Stay inside the page area and away from borders where possible.
            pad = max(2, min(12, w // 100, h // 100))
            shot = ImageGrab.grab(bbox=(x + pad, y + pad, x + w - pad, y + h - pad), all_screens=True)
            rgb = shot.convert("RGB")
            rgb.thumbnail((72, 72))
            # Pillow 14 removes Image.getdata(); prefer the replacement on
            # newer Pillow while retaining compatibility with older releases.
            get_flattened = getattr(rgb, "get_flattened_data", None)
            if callable(get_flattened):
                pixels = list(get_flattened())
            else:
                pixels = list(rgb.getdata())
            if not pixels:
                return
            mins = [min(px[i] for px in pixels) for i in range(3)]
            maxs = [max(px[i] for px in pixels) for i in range(3)]
            span = max(maxs[i] - mins[i] for i in range(3))
            # Quantized dominant-color ratio catches the flat Tekzite gray host even
            # when antialiasing/DWM adds a couple of nearby shades.
            bins = {}
            for r, g, b in pixels:
                key = (r // 8, g // 8, b // 8)
                bins[key] = bins.get(key, 0) + 1
            dominant = max(bins.values()) / float(len(pixels))
            blank = bool(span <= 18 and dominant >= 0.975)
            try:
                record_embedded_surface_probe(blank, span, dominant, attempt, False)
            except Exception:
                pass
            if not blank:
                # A resize-triggered native retry has now proved itself on the
                # actual monitor.  Commit native presentation and release the
                # temporary software-fallback latch.
                if tab.get("presentation") == "native-retry":
                    tab["presentation"] = "native"
                    tab.pop("software_fallback_reason", None)
                    try:
                        record_embedded_native_recovery(True,
                            (int(self.edge_host.winfo_width()), int(self.edge_host.winfo_height())),
                            True)
                    except Exception:
                        pass
                    self.status_var.set("Chromium native presentation recovered after resize")
                return
            if attempt == 1:
                # Give native Chromium one last compositor/repaint pulse, then look
                # at the actual screen again instead of trusting another CDP capture.
                self._schedule_embedded_surface_wake()
                self.root.after(500, self._probe_visible_embedded_surface,
                                generation, target_id, cdp_visual, 2)
                return

            # v5.11: native presentation is authoritative unless the user explicitly
            # selected software mode in Preferences. A flat/black native HWND is now
            # treated as a native compositor problem to recover and diagnose, not as
            # permission to move the tab onto the slower CDP screenshot renderer.
            if generation != self._navigation_generation:
                return
            tab = self._active_tab()
            if tab is None or tab.get("chromium_target_id") != target_id:
                return
            tab["presentation"] = "native"
            tab.pop("software_fallback_reason", None)
            fallback_viewport = (
                max(1, int(self.edge_host.winfo_width())),
                max(1, int(self.edge_host.winfo_height())),
            )
            tab["native_recovery_viewport"] = fallback_viewport
            try:
                record_embedded_native_recovery(True, fallback_viewport, False)
            except Exception:
                pass
            try:
                # Keep the historical field for debug compatibility, but record that
                # no automatic software fallback was used.
                record_embedded_surface_probe(True, span, dominant, attempt, False)
            except Exception:
                pass
            # v5.16: do not hammer a stalled top-level DComp surface with
            # repeated resize/geometry-sync/repaint pulses. Those recovery
            # mutations caused visible black/blue flicker. Keep native mode
            # authoritative, record the stall, and leave Chromium's current
            # compositor/window hierarchy untouched until a real user-driven
            # geometry change occurs.
            try:
                set_embedded_chromium_presentation("native", target_id)
            except Exception:
                pass
            self.status_var.set("Chromium native surface stalled; recovery paused to preserve DComp stability")
        except Exception as exc:
            try:
                record_embedded_surface_probe(False, None, None, attempt, False, type(exc).__name__)
            except Exception:
                pass

    def _enforce_visible_surface_software_fallback(self, generation, target_id):
        """Keep a failed native surface in software mode until explicit recovery."""
        if generation != self._navigation_generation:
            return False
        tab = self._active_tab()
        if (not tab or tab.get("chromium_target_id") != target_id or
                tab.get("software_fallback_reason") != "visible-surface"):
            return False
        # A successful native probe clears software_fallback_reason before this
        # helper can run, so the latch cannot overwrite a proven recovery.
        tab["presentation"] = "software"
        try:
            set_embedded_chromium_presentation("software", target_id)
        except Exception:
            pass
        if not self._chromium_software_mode or self._chromium_frame_target_id != target_id:
            self._show_chromium_software_surface(target_id)
        return True

    def _poll_embedded_navigation(self, generation, future, url, add_history):
        if generation != self._navigation_generation:
            return
        if not future.done():
            self.root.after(40, self._poll_embedded_navigation,
                            generation, future, url, add_history)
            return
        try:
            session = future.result()
            tab = self._active_tab()
            if tab is not None:
                tab["chromium_target_id"] = session.get("target_id")
                tab["engine"] = "chromium"
                tab["url"] = url
                tab["title"] = self._tab_title_for_url(url)
                tab["loaded"] = True
                tab["loading"] = True
                tab["document"] = None
                self._refresh_tab_strip()
            self._schedule_chromium_zoom_apply(all_tabs=True)
            if self._use_chromium_software_surface_for_url(url):
                if tab is not None:
                    tab["presentation"] = "software"
                self._show_chromium_software_surface(session.get("target_id"))
            else:
                if tab is not None:
                    tab["presentation"] = "native"
                    tab.pop("software_fallback_reason", None)
                    tab.pop("native_recovery_viewport", None)
                self._show_embedded_host()
                # v5.42: navigation can rebuild Chromium's presenter/chrome after
                # the first committed frame (notably YouTube and consent shells).
                # Re-measure the DWM crop while that geometry settles so title-bar
                # pixels from the previous site can never leak into the mirror.
                for delay_index, delay_ms in enumerate((60, 180, 420, 850)):
                    self.root.after(
                        delay_ms,
                        self._refresh_dwm_crop_after_navigation,
                        generation,
                        delay_index,
                    )
                # Navigation can recreate Chromium's internal render widget. Wake
                # the surface repeatedly while that native view settles.
                self._schedule_embedded_surface_wake()
                # v4.99: CDP can see a healthy page while the re-parented native
                # HWND presents only Tekzite's flat gray host. Verify what is
                # actually visible on-screen and fall back per-tab when needed.
                self.root.after(300, self._probe_visible_embedded_surface,
                                generation, session.get("target_id"),
                                bool(session.get("attached_frame_visual")))
        except Exception as exc:
            self._show_native_canvas()
            self._finish_navigation_error(generation, exc, allow_chromium_fallback=False)
            return

        if add_history:
            if self.history_index < len(self.history) - 1:
                self.history = self.history[:self.history_index + 1]
            if not self.history or self.history[-1] != url:
                self.history.append(url)
                self.history_index = len(self.history) - 1
        self.update_history_buttons()
        tab = self._active_tab()
        if tab is not None:
            tab["history"] = list(self.history)
            tab["history_index"] = self.history_index
        self.url_var.set(url)
        self._current_document = None
        self.js_runtime = None
        self.status_var.set(f"Embedded Chromium compatibility | {url}")

    def _navigate_embedded(self, url, add_history, generation):
        # Do not expose the compatibility host until Chromium has a verified
        # compositor frame.  While the helper renders off-screen, keep the
        # current/native surface visible instead of showing a dead gray panel.
        self.status_var.set(f"Preparing Chromium frame | {url}…")
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        width = max(1, int(self.content_frame.winfo_width()))
        height = max(1, int(self.content_frame.winfo_height()))
        if not self._embedded_mode:
            self._dwm_surface_ready = False
        self._sync_dwm_host_geometry(show=False, transparent=False)
        parent_hwnd = int(self._ensure_dwm_host())
        tab = self._active_tab()
        target_id = tab.get("chromium_target_id") if tab is not None else None
        other_targets_exist = any(
            t.get("chromium_target_id")
            for t in self.tabs
            if tab is None or t.get("id") != tab.get("id")
        )
        create_new_target = bool(tab is not None and not target_id and other_targets_exist)
        software_presentation = self._use_chromium_software_surface_for_url(url)
        self._embedded_future = self._executor.submit(
            open_embedded_chromium,
            parent_hwnd,
            width,
            height,
            url,
            target_id,
            create_new_target,
            not software_presentation,
            self._page_zoom_percent(),
        )
        self._poll_embedded_navigation(
            generation, self._embedded_future, url, add_history
        )

    def _refresh_dwm_crop_after_navigation(self, generation, delay_index=0):
        """Re-measure Chromium page geometry after SPA/site navigation settles.

        Chromium can rebuild or resize its page presenter after navigation (YouTube
        and consent/app shells are common examples).  Re-run the native DWM sizing
        path a few times so the mirrored source crop follows the current live
        RenderWidgetHost instead of keeping the previous site's chrome inset.
        """
        if generation != self._navigation_generation:
            return
        if not self._embedded_mode or not self._chromium_dwm_mode:
            return
        try:
            self._schedule_dwm_geometry_sync(resize=True, delay=1)
        except Exception:
            pass



    @staticmethod
    def _text_item_visual_box(item):
        """Return an approximate visible text box for a DrawText-like item.

        The native layout engine already stores measured text width.  Font
        height is reconstructed conservatively from the Tk/PIL font tuple so
        this detector can spot gross overlap without depending on painter state.
        """
        if not hasattr(item, "text") or not hasattr(item, "x") or not hasattr(item, "y"):
            return None
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            return None
        try:
            x = float(getattr(item, "x", 0) or 0)
            y = float(getattr(item, "y", 0) or 0)
            width = max(1.0, float(getattr(item, "width", 0) or 0))
        except (TypeError, ValueError):
            return None

        font = getattr(item, "font", None)
        font_size = 14.0
        if isinstance(font, (tuple, list)):
            for value in font[1:]:
                try:
                    numeric = abs(float(value))
                except (TypeError, ValueError):
                    continue
                if 5 <= numeric <= 160:
                    font_size = numeric
                    break
        height = max(8.0, min(180.0, font_size * 1.45))
        return (x, y, x + width, y + height, text, getattr(item, "dom_node", None))

    @staticmethod


    def _live_viewport(self):
        """Return the currently drawable canvas viewport.

        A realized canvas can briefly report 1x1 while the window is mapping
        or minimizing.  Treat that as transient rather than laying out a
        desktop page against a bogus tiny viewport.
        """
        try:
            self.root.update_idletasks()
        except Exception:
            pass

        width = int(self.canvas.winfo_width() or 0)
        height = int(self.canvas.winfo_height() or 0)

        if width <= 1 or height <= 1:
            return None

        return (width, height)

    def _layout_ui_yield(self):
        """Let Tk process events and enforce the native first-layout budget."""
        now = time.perf_counter()
        deadline = getattr(self, "_native_layout_deadline", None)
        if deadline is not None and now >= deadline:
            raise NativeLayoutBudgetExceeded(
                "native first layout exceeded the compatibility time budget"
            )
        if now - self._last_layout_ui_yield < 0.020:
            return
        self._last_layout_ui_yield = now

        try:
            # update(), rather than update_idletasks(), keeps resizing, moving,
            # focus, keyboard and close-window handling alive. Configure events
            # are guarded by _layout_in_progress so they cannot recursively
            # start another layout pass.
            self.root.update()
        except tk.TclError:
            pass


    def _schedule_live_reflow(self):
        if self._current_document is None:
            return

        if getattr(self, "_layout_in_progress", False):
            self._pending_reflow = True
            return

        viewport = self._live_viewport()
        if viewport is None or self._last_layout_viewport == viewport:
            return

        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass

        generation = self._navigation_generation
        self._resize_after_id = self.root.after(
            self._resize_debounce_ms,
            self._relayout_current_document,
            generation,
            None,
        )

    def _on_canvas_configure(self, event):
        """Debounce every drawable viewport transition into a live reflow."""
        # Do not trust Configure's dimensions later: another resize/maximize/
        # restore can happen during the debounce interval.  Re-read the canvas
        # at execution time instead.
        self._schedule_live_reflow()

    def _on_window_map(self, event=None):
        """Reflow after restore/deiconify once Tk has remapped the viewport."""
        if self._current_document is None:
            return
        try:
            self.root.after_idle(self._schedule_live_reflow)
        except Exception:
            self._schedule_live_reflow()


    def normalize_url(self, url):
        value = url.strip()

        if not value:
            return START_URL

        # Preserve explicit URLs/schemes entered by the user.
        if "://" in value or value.startswith(("about:", "data:", "file:")):
            return value

        # Anything containing whitespace is clearly a search query.
        if any(ch.isspace() for ch in value):
            return "https://www.google.com/search?q=" + quote_plus(value)

        # Common host-like input should navigate directly rather than search.
        # This covers domains, localhost and IPv4/IPv6-ish addresses.
        if (
            "." in value
            or value.lower().startswith("localhost")
            or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?(?:/.*)?", value)
            or (":" in value and not value.startswith(":") )
        ):
            return "https://" + value

        # Bare words become Google searches, turning the address bar into an
        # omnibox instead of trying to open e.g. https://tekzite.
        return "https://www.google.com/search?q=" + quote_plus(value)


    def apply_site_compatibility(self, url):
        """Reserved compatibility hook; keep navigation URLs canonical.

        Google used to have a basic-HTML `gbv=1` variant, but current Search
        responses require JavaScript regardless. The network layer now detects
        that gate and uses the optional JS pre-render bridge instead of mutating
        the user's URL.
        """
        return url

    def update_history_buttons(self):
        self.back_button.configure(
            state="normal" if self.history_index > 0 else "disabled"
        )

        self.forward_button.configure(
            state=(
                "normal"
                if 0 <= self.history_index < len(self.history) - 1
                else "disabled"
            )
        )

    def _apply_frameless_app_style(self):
        """Keep an override-redirect Tk window visible in the Windows taskbar."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            self.root.update_idletasks()
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = ctypes.c_long
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            set_long.restype = ctypes.c_long
            style = get_long(hwnd, GWL_EXSTYLE)
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            set_long(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _make_window_control(self, parent, text, command, close=False):
        normal_bg = self.ui["bg"]
        hover_bg = "#c42b3a" if close else self.ui["field_focus"]
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=normal_bg,
            fg=self.ui["text"],
            activebackground=hover_bg,
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI Symbol", 11),
            width=5,
            cursor="hand2",
        )
        button.bind("<Enter>", lambda event, b=button, c=hover_bg: self._animate_widget_color(b, "bg", c, 95))
        button.bind("<Leave>", lambda event, b=button, c=normal_bg: self._animate_widget_color(b, "bg", c, 135))
        return button

    def _build_browser_menus(self, parent):
        menu_specs = [
            ("File", [
                ("New Tab", self._new_tab, "Ctrl+T"),
                ("Close Tab", self._close_active_tab, "Ctrl+W"),
                ("Reopen Closed Tab", self._restore_closed_tab, "Ctrl+Shift+T"),
                ("New Window", self._new_window, "Ctrl+N"),
                ("Open Location", self._focus_address, "Ctrl+L"),
                None,
                ("Exit", self.on_close, "Alt+F4"),
            ]),
            ("Edit", [
                ("Find in Page", self._show_find_bar, "Ctrl+F"),
                None,
                ("Cut", lambda: self._edit_shortcut("x"), "Ctrl+X"),
                ("Copy", lambda: self._edit_shortcut("c"), "Ctrl+C"),
                ("Paste", lambda: self._edit_shortcut("v"), "Ctrl+V"),
                ("Select All", lambda: self._edit_shortcut("a"), "Ctrl+A"),
            ]),
            ("View", [
                ("Reload", self._reload_current, "Ctrl+R"),
                ("Focus Address Bar", self._focus_address, "Ctrl+L"),
                None,
                ("Fullscreen", self._toggle_fullscreen, "F11"),
            ]),
            ("History", [
                ("Back", self.go_back, "Alt+Left"),
                ("Forward", self.go_forward, "Alt+Right"),
                ("Home", self._go_home, ""),
            ]),
            ("Tools", [
                ("Preferences", self.show_preferences, "Ctrl+,"),
                None,
                ("Copy All Debug", self.copy_all_debug, ""),
                ("Copy Full Debug", self.copy_full_debug, ""),
                None,
                ("Inspect Chromium HTML", self.inspect_html, "Ctrl+U"),
            ]),
            ("Help", [
                ("About Tekzite", self._show_about, ""),
            ]),
        ]
        for label, items in menu_specs:
            button = tk.Menubutton(
                parent,
                text=label,
                bg=self.ui["bg"],
                fg=self.ui["muted"],
                activebackground=self.ui["field_focus"],
                activeforeground=self.ui["text"],
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=(self._ui_font_family, 9),
                cursor="hand2",
                padx=7,
            )
            menu = tk.Menu(
                button,
                tearoff=0,
                bg=self.ui["chrome_2"],
                fg=self.ui["text"],
                activebackground=self.ui["accent"],
                activeforeground="#ffffff",
                disabledforeground=self.ui["muted"],
                relief="flat",
                bd=1,
                font=(self._ui_font_family, 9),
            )
            for item in items:
                if item is None:
                    menu.add_separator()
                    continue
                item_label, command, accelerator = item
                menu.add_command(label=item_label, command=command, accelerator=accelerator)
            button.configure(menu=menu)
            button.bind("<Enter>", lambda event, b=button: (
                self._animate_widget_color(b, "bg", self.ui["field_focus"], 100),
                self._animate_widget_color(b, "fg", self.ui["text"], 100),
            ))
            button.bind("<Leave>", lambda event, b=button: (
                self._animate_widget_color(b, "bg", self.ui["bg"], 140),
                self._animate_widget_color(b, "fg", self.ui["muted"], 140),
            ))
            button.pack(side="left", fill="y")

    def _start_window_drag(self, event):
        if self._window_maximized or self._fullscreen:
            return
        self._window_drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_window(self, event):
        if self._window_maximized or self._fullscreen:
            return
        dx, dy = self._window_drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _get_work_area(self):
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                rect = wintypes.RECT()
                SPI_GETWORKAREA = 0x0030
                if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _toggle_maximize(self):
        if self._fullscreen:
            return
        if self._window_maximized:
            if self._window_restore_geometry:
                self.root.geometry(self._window_restore_geometry)
            self._window_maximized = False
        else:
            self._window_restore_geometry = self.root.geometry()
            x, y, width, height = self._get_work_area()
            self.root.geometry(f"{width}x{height}+{x}+{y}")
            self._window_maximized = True

    def _minimize_window(self):
        # Tk cannot iconify an override-redirect window directly on Windows.
        self.root.overrideredirect(False)
        self.root.iconify()
        self.root.after(120, self._restore_frameless_after_minimize)

    def _restore_frameless_after_minimize(self):
        try:
            if self.root.state() != "iconic":
                self.root.overrideredirect(True)
                self._apply_frameless_app_style()
                return
        except Exception:
            return
        self.root.after(120, self._restore_frameless_after_minimize)

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        try:
            self.root.attributes("-fullscreen", self._fullscreen)
        except Exception:
            pass

    def _new_window(self):
        try:
            subprocess.Popen([sys.executable, os.path.abspath(__file__)])
        except Exception as exc:
            self.status_var.set(f"Could not open new window: {exc}")

    def _focus_address(self):
        # v4.80: explicitly take native keyboard ownership back from the
        # cross-process Chromium child before focusing the Tk Entry.
        self._address_focus_active = True
        self._chromium_page_keyboard_active = False
        self._cancel_embedded_surface_wakes()
        try:
            self.root.focus_force()
        except Exception:
            pass
        try:
            self.address.focus_force()
        except Exception:
            self.address.focus_set()
        self.address.selection_range(0, tk.END)
        self.address.icursor(tk.END)

    def _reload_current(self):
        url = (self.url_var.get() or self._homepage_url()).strip()
        if url:
            self.navigate_to(url, add_history=False, reuse_existing=False)

    def _go_home(self):
        self.navigate_to(self._homepage_url())

    def _edit_shortcut(self, key):
        # DWM presentation keeps Chromium off-screen, so native keybd_event
        # cannot reliably target the page. Route browser editing shortcuts over
        # CDP whenever the DWM/software input plane owns the interaction.
        if self._chromium_input_surface_active():
            key = str(key or "").lower()
            if key == "v":
                try:
                    text = self.root.clipboard_get()
                except Exception:
                    text = ""
                if text:
                    self._submit_chromium_input(
                        dispatch_embedded_chromium_key, text=text, event_type="insertText",
                        target_id=self._chromium_frame_target_id, refresh=True,
                    )
                return
            if key in {"a", "c", "x", "z", "y"}:
                upper = key.upper()
                self._submit_chromium_input(
                    dispatch_embedded_chromium_key, key, event_type="keyDown",
                    modifiers=2, windows_vk=ord(upper), code=f"Key{upper}",
                    target_id=self._chromium_frame_target_id,
                )
                self._submit_chromium_input(
                    dispatch_embedded_chromium_key, key, event_type="keyUp",
                    modifiers=2, windows_vk=ord(upper), code=f"Key{upper}",
                    target_id=self._chromium_frame_target_id, refresh=True,
                )
                return
        # Send a real Ctrl shortcut so it works both in Tk widgets and in the
        # embedded Chromium child window when that owns keyboard focus.
        if sys.platform == "win32":
            try:
                import ctypes
                VK_CONTROL = 0x11
                KEYEVENTF_KEYUP = 0x0002
                vk = ord(key.upper())
                user32 = ctypes.windll.user32
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(vk, 0, 0, 0)
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                return
            except Exception:
                pass
        widget = self.root.focus_get()
        if widget is not None:
            virtual = {"x": "<<Cut>>", "c": "<<Copy>>", "v": "<<Paste>>", "a": "<<SelectAll>>"}.get(key)
            if virtual:
                try:
                    widget.event_generate(virtual)
                except Exception:
                    pass

    def _page_zoom_percent(self):
        return _normalized_zoom_percent(
            getattr(self, "preferences", DEFAULT_PREFERENCES).get("page_zoom_percent", 100)
        )

    def _apply_chromium_zoom(self, target_id=None):
        """Apply Chromium page zoom and keep DWM on a 1:1 presentation contract."""
        if target_id is None:
            tab = self._active_tab()
            target_id = tab.get("chromium_target_id") if tab else None
        if not target_id:
            return False
        try:
            applied = bool(set_embedded_chromium_zoom(self._page_zoom_percent(), target_id))
        except Exception:
            return False
        if applied and self._chromium_dwm_mode:
            self._schedule_dwm_zoom_refresh()
        return applied

    def _refresh_dwm_after_zoom(self):
        """Re-measure the DWM source after Chromium has reflowed for page zoom.

        DWM is a presentation mirror only.  The page zoom lives inside Chromium;
        this refresh merely re-establishes the current viewport/crop at 1:1 so
        the thumbnail can never become a second, image-level zoom transform.
        """
        if not self._embedded_mode or not self._chromium_dwm_mode:
            return False
        try:
            self._sync_dwm_host_geometry(show=True, transparent=False)
            return bool(resize_embedded_chromium(
                max(1, int(self.edge_host.winfo_width())),
                max(1, int(self.edge_host.winfo_height())),
            ))
        except Exception:
            return False

    def _schedule_dwm_zoom_refresh(self):
        """Follow Chromium's short zoom/reflow settle window without DWM scaling."""
        for delay in (0, 45, 120, 260, 520):
            try:
                self.root.after(delay, self._refresh_dwm_after_zoom)
            except Exception:
                pass

    def _live_chromium_target_ids(self):
        """Return each currently open Chromium-backed tab target exactly once."""
        seen = set()
        targets = []
        for tab in getattr(self, "tabs", []) or []:
            target_id = tab.get("chromium_target_id") if isinstance(tab, dict) else None
            if target_id and target_id not in seen:
                seen.add(target_id)
                targets.append(target_id)
        return targets

    def _apply_chromium_zoom_to_all_tabs(self):
        """Push the authoritative zoom to every known page and active CDP target."""
        applied = False
        for target_id in self._live_chromium_target_ids():
            applied = self._apply_chromium_zoom(target_id) or applied
        # OAuth/JS flows can swap Chromium's active target before the Tk tab
        # bookkeeping notices. A final target-less apply resolves the session's
        # current DevTools target and closes that race.
        try:
            applied = bool(set_embedded_chromium_zoom(self._page_zoom_percent(), None)) or applied
        except Exception:
            pass
        return applied

    def _schedule_chromium_zoom_apply(self, target_id=None, all_tabs=False):
        """Re-apply zoom across the short redirect/renderer-settle window.

        Preference changes use all_tabs=True so every currently open web page is
        updated immediately. Navigation and preference changes both use the browser-wide path so every
        live page is kept on the same authoritative zoom. This deliberately
        favors consistency over a tiny amount of extra DevTools traffic.
        """
        for delay in (120, 350, 900, 1800, 3500, 6000):
            try:
                if all_tabs:
                    self.root.after(delay, self._apply_chromium_zoom_to_all_tabs)
                else:
                    self.root.after(delay, lambda tid=target_id: self._apply_chromium_zoom(tid))
            except Exception:
                pass

    def _zoom_watchdog_tick(self):
        """Backup verifier for Chromium-native zoom.

        v7.0 delegates the real monitoring to Tekzite's local Chromium extension,
        which receives chrome.tabs.onZoomChange events and restores the saved
        browser zoom immediately. This Tk watchdog is a low-frequency safety net.
        """
        self._zoom_watchdog_after_id = None
        wanted = self._page_zoom_percent()
        statuses = []
        for target_id in self._live_chromium_target_ids():
            try:
                status = check_embedded_chromium_zoom(wanted, target_id) or {}
            except Exception as exc:
                status = {"target_id": target_id, "error": f"{type(exc).__name__}: {exc}"}
            statuses.append(status)
            self._zoom_watchdog_checks += 1
            if status.get("ready") and not status.get("matches"):
                if self._apply_chromium_zoom(target_id):
                    self._zoom_watchdog_corrections += 1
                    status["corrected"] = True
        self._zoom_watchdog_last_status = statuses
        self._schedule_zoom_watchdog()

    def _schedule_zoom_watchdog(self, initial=False):
        try:
            if self._zoom_watchdog_after_id is not None:
                self.root.after_cancel(self._zoom_watchdog_after_id)
        except Exception:
            pass
        delay = 900 if initial else int(self._zoom_watchdog_interval_ms)
        try:
            self._zoom_watchdog_after_id = self.root.after(delay, self._zoom_watchdog_tick)
        except Exception:
            self._zoom_watchdog_after_id = None

    def _monitor_work_area_for_window(self, tk_window=None):
        """Return the Win32 work area of the monitor containing Tekzite."""
        if not sys.platform.startswith("win"):
            return None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            MONITOR_DEFAULTTONEAREST = 2
            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
            source = tk_window or self.root
            source.update_idletasks()
            hwnd = int(source.winfo_id())
            try:
                GA_ROOT = 2
                user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetAncestor.restype = wintypes.HWND
                root_hwnd = int(user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or 0)
                if root_hwnd:
                    hwnd = root_hwnd
            except Exception:
                pass
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return int(r.left), int(r.top), int(r.right), int(r.bottom)
        except Exception:
            pass
        return None

    def _homepage_url(self):
        value = str(getattr(self, "preferences", DEFAULT_PREFERENCES).get("homepage") or START_URL).strip()
        try:
            return self.normalize_url(value)
        except Exception:
            return START_URL

    def _apply_preferences_runtime(self):
        if hasattr(self, "status_bar"):
            visible = bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True))
            if visible and not self.status_bar.winfo_ismapped():
                self.status_bar.pack(fill="x")
            elif not visible and self.status_bar.winfo_ismapped():
                self.status_bar.pack_forget()

    def show_preferences(self):
        win = tk.Toplevel(self.root)
        win.title(f"Tekzite Browser Preferences — v{BROWSER_VERSION}")
        dialog_width = 620
        win.configure(bg=self.ui["bg"])
        win.transient(self.root)
        # v6.8: build Preferences while hidden, then size/center it from the
        # completed widget tree before exposing it. This avoids the v6.7
        # failure mode where a sizing exception could leave a 1-pixel dialog.
        win.withdraw()

        # Do not grab/focus the withdrawn shell. v6.8 shows, raises and
        # focuses the completed dialog only after its final geometry is known.

        outer = tk.Frame(win, bg=self.ui["bg"], padx=22, pady=18)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="Browser Preferences", fg=self.ui["text"], bg=self.ui["bg"],
                 font=(self._ui_display_font_family, 18, "bold")).pack(anchor="w")
        tk.Label(outer, text="Customize Tekzite without editing configuration files.", fg=self.ui["muted"],
                 bg=self.ui["bg"], font=(self._ui_font_family, 9)).pack(anchor="w", pady=(2, 18))

        homepage = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("homepage", START_URL))
        startup = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("startup", "homepage"))
        new_tab = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("new_tab", "blank"))
        renderer = tk.StringVar(value="chromium")
        chromium_presentation = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("chromium_presentation", "native"))
        auto_fallback = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("auto_chromium_fallback", True)))
        reuse_tabs = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("reuse_open_tabs", True)))
        status_bar = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True)))
        network_diagnostics = tk.StringVar(value=str(getattr(self, "preferences", DEFAULT_PREFERENCES).get("network_diagnostics", "off")))
        clear_on_exit = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("clear_browsing_data_on_exit", True)))
        adblock_enabled = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("adblock_enabled", True)))
        page_zoom = tk.StringVar(value=f"{self._page_zoom_percent()}%")

        def section(title):
            tk.Label(outer, text=title, fg=self.ui["accent_hover"], bg=self.ui["bg"],
                     font=(self._ui_font_family, 10, "bold")).pack(anchor="w", pady=(12, 6))
        def combo(var, values):
            box = ttk.Combobox(outer, textvariable=var, values=values, state="readonly")
            box.pack(fill="x", pady=(0, 6))
            return box

        section("Homepage")
        entry = tk.Entry(outer, textvariable=homepage, bg=self.ui["field"], fg=self.ui["text"],
                         insertbackground=self.ui["text"], relief="flat", font=(self._ui_font_family, 10))
        entry.pack(fill="x", ipady=7)

        section("Startup and tabs")
        combo(startup, ["homepage", "blank"])
        combo(new_tab, ["blank", "homepage"])
        tk.Checkbutton(outer, text="Switch to an already-open tab instead of loading the same URL again",
                       variable=reuse_tabs, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)

        section("Rendering engine")
        combo(renderer, ["chromium"])
        tk.Label(outer, text="Auto uses Tekzite first where practical and Chromium for compatibility-heavy sites.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, 8)).pack(anchor="w")
        tk.Checkbutton(outer, text="Automatically fall back to Chromium when native rendering fails",
                       variable=auto_fallback, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Chromium presentation", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, 8)).pack(anchor="w", pady=(7, 1))
        combo(chromium_presentation, ["native", "software"])
        tk.Label(outer, text="Native is GPU-backed and is kept for normal browsing. Software is manual diagnostics only.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, 8)).pack(anchor="w")

        section("Privacy")
        tk.Label(outer, text="Browser telemetry blocked • GPC + DNT enabled • third-party cookies blocked",
                 fg=self.ui["text"], bg=self.ui["bg"], font=(self._ui_font_family, 9)).pack(anchor="w", pady=3)
        tk.Label(outer, text="Notifications, location, camera, microphone, sensors, password saving and autofill are disabled by default.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, 8), wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Checkbutton(outer, text="Block ads with Tekzite Adblock",
                       variable=adblock_enabled, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Blocks dedicated advertising hosts before Chromium connects to them. Restart Tekzite after changing this setting.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, 8), wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Checkbutton(outer, text="Clear Chromium cookies, storage, cache and history on exit",
                       variable=clear_on_exit, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Network diagnostics", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, 8)).pack(anchor="w", pady=(6, 1))
        combo(network_diagnostics, ["off", "errors", "full"])
        tk.Label(outer, text="Off is the privacy-first default. Full can include destination hosts and plain-HTTP paths.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, 8)).pack(anchor="w")

        section("Interface")
        tk.Label(outer, text="Default page zoom", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, 8)).pack(anchor="w", pady=(0, 1))
        zoom_box = combo(page_zoom, ["75%", "80%", "90%", "100%", "110%", "125%", "150%", "175%", "200%"] )
        original_zoom = self._page_zoom_percent()
        preview_zoom = {"value": original_zoom}

        def preview_selected_zoom(_event=None):
            value = _normalized_zoom_percent(page_zoom.get(), original_zoom)
            preview_zoom["value"] = value
            # Preview through the same authoritative preference path used by
            # Save, so the visible result cannot differ from the persisted one.
            self.preferences["page_zoom_percent"] = value
            self._schedule_chromium_zoom_apply(all_tabs=True)
            self.status_var.set(f"Page zoom preview: {value}%")

        zoom_box.bind("<<ComboboxSelected>>", preview_selected_zoom)
        tk.Label(outer, text="Changes preview immediately on every open Chromium web page; Save makes the value permanent.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, 8)).pack(anchor="w", pady=(0, 5))
        tk.Checkbutton(outer, text="Show status bar", variable=status_bar, bg=self.ui["bg"], fg=self.ui["text"],
                       selectcolor=self.ui["field"], activebackground=self.ui["bg"],
                       activeforeground=self.ui["text"]).pack(anchor="w", pady=3)

        buttons = tk.Frame(outer, bg=self.ui["bg"])
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        def save_and_close():
            selected_zoom = _normalized_zoom_percent(page_zoom.get(), original_zoom)
            self.preferences.update({
                "homepage": homepage.get().strip() or START_URL,
                "startup": startup.get(),
                "new_tab": new_tab.get(),
                "renderer": "chromium",
                "chromium_presentation": chromium_presentation.get(),
                "auto_chromium_fallback": bool(auto_fallback.get()),
                "reuse_open_tabs": bool(reuse_tabs.get()),
                "show_status_bar": bool(status_bar.get()),
                "network_diagnostics": network_diagnostics.get(),
                "clear_browsing_data_on_exit": bool(clear_on_exit.get()),
                "adblock_enabled": bool(adblock_enabled.get()),
                "page_zoom_percent": selected_zoom,
            })
            try:
                save_preferences(self.preferences)
            except Exception as exc:
                messagebox.showerror("Tekzite Preferences", f"Could not save preferences:\n{exc}", parent=win)
                return
            self._apply_preferences_runtime()
            # Apply synchronously once before closing the modal, then keep a
            # few settle passes for renderer/redirect races.
            self._apply_chromium_zoom_to_all_tabs()
            self._schedule_chromium_zoom_apply(all_tabs=True)
            os.environ["TEKZITE_NETWORK_LOG_LEVEL"] = str(self.preferences.get("network_diagnostics", "off"))
            os.environ["TEKZITE_ADBLOCK_ENABLED"] = "1" if self.preferences.get("adblock_enabled", True) else "0"
            self.status_var.set("Preferences saved — restart Tekzite to apply network/privacy changes")
            win.destroy()
        def cancel_preferences():
            # Live zoom selection is only a preview until Save. Restore the
            # authoritative value when the dialog is cancelled.
            if self._page_zoom_percent() != original_zoom:
                self.preferences["page_zoom_percent"] = original_zoom
                self._apply_chromium_zoom_to_all_tabs()
                self._schedule_chromium_zoom_apply(all_tabs=True)
            win.destroy()

        tk.Button(buttons, text="Cancel", command=cancel_preferences, bg=self.ui["chrome_2"], fg=self.ui["text"],
                  relief="flat", padx=16, pady=7).pack(side="right")
        tk.Button(buttons, text="Save", command=save_and_close, bg=self.ui["accent"], fg="#ffffff",
                  relief="flat", padx=20, pady=7).pack(side="right", padx=(0, 8))
        def fit_and_center_preferences():
            # Always leave this function with a usable visible dialog. Monitor
            # discovery is optional; sizing the completed content is not.
            margin = 12
            try:
                win.update_idletasks()
                requested_w = max(dialog_width, int(outer.winfo_reqwidth()) + 2)
                requested_h = max(320, int(outer.winfo_reqheight()) + 2)
            except Exception:
                requested_w, requested_h = dialog_width, 720

            try:
                work = self._monitor_work_area_for_window(self.root)
            except Exception:
                work = None

            if work:
                left, top, right, bottom = work
            else:
                try:
                    screen_w = int(win.winfo_screenwidth())
                    screen_h = int(win.winfo_screenheight())
                except Exception:
                    screen_w, screen_h = 1280, 800
                left, top, right, bottom = 0, 0, screen_w, screen_h

            work_w = max(1, int(right - left))
            work_h = max(1, int(bottom - top))
            dialog_w = min(requested_w, max(560, work_w - margin * 2))
            dialog_h = min(requested_h, max(320, work_h - margin * 2))
            x = int(left + (work_w - dialog_w) // 2)
            y = int(top + (work_h - dialog_h) // 2)

            try:
                win.geometry(f"{dialog_w}x{dialog_h}+{x}+{y}")
                win.minsize(560, min(dialog_h, 320))
                win.maxsize(max(560, work_w - margin * 2), max(320, work_h - margin * 2))
                win.resizable(False, False)
            except Exception:
                try:
                    win.geometry(f"{dialog_width}x720+{max(0, x)}+{max(0, y)}")
                except Exception:
                    pass

            try:
                win.deiconify()
                self._animate_toplevel_in(win, 145)
                win.lift()
                win.attributes("-topmost", True)
                win.after(150, lambda: win.winfo_exists() and win.attributes("-topmost", False))
            except Exception:
                try:
                    win.deiconify()
                    win.lift()
                except Exception:
                    pass
            try:
                win.grab_set()
                win.focus_force()
            except Exception:
                pass

        win.after_idle(fit_and_center_preferences)
        win.protocol("WM_DELETE_WINDOW", cancel_preferences)

    def _show_about(self):
        messagebox.showinfo(
            "About Tekzite",
            f"Tekzite Browser v{BROWSER_VERSION}\n\nChromium-only web engine with Tekzite-native browser UI and DWM presentation.",
            parent=self.root,
        )

    def navigate(self):
        # v4.83: pressing Enter/Go commits the omnibox. Do not leave its
        # cross-window focus guard latched while the Chromium page loads.
        url = self.url_var.get()
        self._release_address_focus_for_navigation()
        self.navigate_to(
            url,
            add_history=True,
        )

    def navigate_to(self, url, add_history=True, reuse_existing=True):
        """Navigate using Chromium only. Tekzite no longer has a web renderer."""
        url = self.normalize_url(url)
        url = self.apply_site_compatibility(url)

        active = self._active_tab()
        if reuse_existing and self.preferences.get("reuse_open_tabs", True):
            existing = self._find_open_tab_by_url(url, exclude_id=self.active_tab_id)
            if existing is not None:
                self._switch_tab(existing["id"])
                return
            if (active is not None and active.get("loaded") and
                    self._canonical_tab_url(active.get("url")) == self._canonical_tab_url(url)):
                self.url_var.set(active.get("url") or url)
                self.status_var.set("Already open in this tab")
                return

        self.url_var.set(url)
        if active is not None:
            active["url"] = url
            active["title"] = self._tab_title_for_url(url)
            active["engine"] = "chromium"
            active["document"] = None
            active["loading"] = True
            active["ready_state"] = "loading"
            self._refresh_tab_strip()

        self._navigation_generation += 1
        generation = self._navigation_generation
        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass
            self._resize_after_id = None
        self._navigate_embedded(url, add_history, generation)



    def _start_lazy_font_loading(self, generation, font_manager):
        """Compatibility hook retained for future demand-driven font loading.

        v3.54 deliberately does not bulk-load every deferred face after first
        paint because that caused a visible typography swap and full-page
        reflow several seconds after navigation.

        Historical v3.46 implementation marker, intentionally disabled:
            font_manager.fetch_all,
            1,
        """
        return None

    def _poll_lazy_font_loading(self, generation, future):
        return None

    def _finish_navigation_error(
        self,
        generation,
        exc,
        allow_chromium_fallback=True,
    ):
        if generation != self._navigation_generation:
            return

        if allow_chromium_fallback and self._can_auto_chromium_fallback(
            getattr(self, "_navigation_url", "")
        ):
            if self._fallback_native_to_chromium(
                self._navigation_url,
                getattr(self, "_navigation_add_history", True),
                generation,
                f"native load failed: {exc}",
            ):
                return

        # Preserve the old page if one is already displayed. On a first-load
        # failure, show the error in the canvas as before.
        if not self.history:
            self.canvas.delete("all")
            self.canvas.create_text(
                30,
                30,
                anchor="nw",
                text=f"Load error:\n{exc}",
                width=900,
                font=("Arial", 14),
                fill="black",
            )

        self.status_var.set(
            f"Load failed: {exc}"
        )


    def go_back(self):
        if self.history_index <= 0:
            return

        self.history_index -= 1
        url = self.history[self.history_index]

        self.navigate_to(
            url,
            add_history=False,
            reuse_existing=False,
        )

        self.update_history_buttons()

    def go_forward(self):
        if self.history_index >= len(self.history) - 1:
            return

        self.history_index += 1
        url = self.history[self.history_index]

        self.navigate_to(
            url,
            add_history=False,
            reuse_existing=False,
        )

        self.update_history_buttons()

    def show_text_window(
        self,
        title,
        content,
        geometry="1100x720",
        wrap="none",
    ):
        """Open a reusable read-only debug text window.

        Paint Debug and Background Debug already routed through this helper,
        but the helper itself had been lost during earlier UI refactoring.
        """
        window = tk.Toplevel(self.root)
        window.title(f"Tekzite {title}")
        window.geometry(geometry)

        frame = tk.Frame(window)
        frame.pack(fill="both", expand=True)

        text = tk.Text(
            frame,
            wrap=wrap,
            font=("Consolas", 9),
        )
        ybar = tk.Scrollbar(
            frame,
            orient="vertical",
            command=text.yview,
        )
        xbar = tk.Scrollbar(
            frame,
            orient="horizontal",
            command=text.xview,
        )

        text.configure(
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")
        text.pack(side="left", fill="both", expand=True)

        text.insert("1.0", content or "(no data)")
        text.configure(state="disabled")
        return window



    def _full_debug_text(self):
        """v6.0 diagnostics: Chromium/DWM only; legacy renderer diagnostics removed."""
        sections = []
        def add(title, text):
            sections.append("=" * 80 + "\n" + title + "\n" + "=" * 80 + "\n" + (text or "(no data)"))
        add("TEKZITE", f"version: {BROWSER_VERSION}\nweb_engine: Chromium only\npresentation: DWM/native Chromium")
        try:
            add("CHROMIUM / DWM DEBUG", embedded_chromium_debug_report())
        except Exception as exc:
            add("CHROMIUM / DWM DEBUG", f"Unavailable: {exc}")
        tab = self._active_tab()
        if tab is not None:
            add("ACTIVE TAB", "\n".join([
                f"url: {tab.get('url','')}",
                f"engine: {tab.get('engine','chromium')}",
                f"target_id: {tab.get('chromium_target_id')}",
                f"presentation: {tab.get('presentation')}",
                f"zoom_percent: {self._page_zoom_percent()}",
                f"zoom_watchdog_interval_ms: {getattr(self, '_zoom_watchdog_interval_ms', None)}",
                f"zoom_watchdog_checks: {getattr(self, '_zoom_watchdog_checks', 0)}",
                f"zoom_watchdog_corrections: {getattr(self, '_zoom_watchdog_corrections', 0)}",
                f"zoom_watchdog_last_status: {getattr(self, '_zoom_watchdog_last_status', None)}",
            ]))
        return "\n\n".join(sections) + "\n"

    def _compact_debug_text(self):
        report = self._full_debug_text()
        return report if len(report) <= 12000 else report[:12000] + "\n... clipped ...\n"

    def _all_debug_text(self):
        """Compatibility name: since v1.33 this returns the compact bundle."""
        return self._compact_debug_text()

    def _copy_debug_report(self, report, label):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(report)
            self.root.update_idletasks()
            self.status_var.set(
                f"Copied {label} to clipboard ({len(report):,} chars)"
            )
        except Exception as exc:
            messagebox.showerror(
                label,
                f"Could not copy debug output:\\n{exc}",
            )

    def copy_all_debug(self):
        # v1.33: Copy All is a focused paste-friendly bundle. Full raw
        # diagnostics remain one click away.
        self._copy_debug_report(
            self._all_debug_text(),
            "compact debug",
        )

    def copy_full_debug(self):
        self._copy_debug_report(
            self._full_debug_text(),
            "full debug",
        )






    def inspect_html(self):
        """Open a searchable HTML source viewer for the current page.

        Native pages expose the exact response source that Tekzite parsed.
        Embedded Chromium pages expose the live DOM after JavaScript has run.
        """
        window = tk.Toplevel(self.root)
        window.title(f"Tekzite HTML Inspector — v{BROWSER_VERSION}")
        window.geometry("1180x760")
        window.configure(bg=self.ui["bg"])

        toolbar = tk.Frame(window, bg=self.ui["chrome"], height=44)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        source_var = tk.StringVar(
            value="Live Chromium DOM" if self._embedded_mode else "Native response source"
        )
        tk.Label(
            toolbar, textvariable=source_var, bg=self.ui["chrome"],
            fg=self.ui["muted"], font=(self._ui_font_family, 9), padx=12
        ).pack(side="left")

        find_var = tk.StringVar()
        find_entry = tk.Entry(
            toolbar, textvariable=find_var, bg=self.ui["field"],
            fg=self.ui["text"], insertbackground=self.ui["text"],
            relief="flat", bd=0, font=(self._ui_font_family, 9)
        )
        find_entry.pack(side="left", fill="x", expand=True, padx=(8, 6), pady=8)

        body = tk.Frame(window, bg=self.ui["bg"])
        body.pack(fill="both", expand=True)
        yscroll = tk.Scrollbar(body, orient="vertical")
        yscroll.pack(side="right", fill="y")
        xscroll = tk.Scrollbar(body, orient="horizontal")
        xscroll.pack(side="bottom", fill="x")
        text = tk.Text(
            body, wrap="none", font=("Consolas", 10),
            bg="#090d16", fg="#dce6f7", insertbackground="#ffffff",
            selectbackground=self.ui["accent"], selectforeground="#ffffff",
            relief="flat", bd=0, padx=12, pady=10,
            yscrollcommand=yscroll.set, xscrollcommand=xscroll.set,
        )
        text.pack(side="left", fill="both", expand=True)
        yscroll.configure(command=text.yview)
        xscroll.configure(command=text.xview)

        status_var = tk.StringVar(value="Loading HTML…" if self._embedded_mode else "Ready")
        status = tk.Label(
            window, textvariable=status_var, anchor="w",
            bg=self.ui["chrome"], fg=self.ui["muted"],
            font=(self._ui_font_family, 8), padx=10, pady=4
        )
        status.pack(fill="x")

        text.tag_configure("match", background="#4b3f83", foreground="#ffffff")
        search_state = {"start": "1.0"}

        def set_html(html):
            html = str(html or "")
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", html)
            text.configure(state="disabled")
            status_var.set(f"{len(html):,} characters")
            search_state["start"] = "1.0"

        def find_next(event=None):
            query = find_var.get()
            text.tag_remove("match", "1.0", "end")
            if not query:
                return "break"
            idx = text.search(query, search_state["start"], stopindex="end", nocase=True)
            if not idx:
                idx = text.search(query, "1.0", stopindex="end", nocase=True)
            if not idx:
                status_var.set(f"Not found: {query}")
                return "break"
            end = f"{idx}+{len(query)}c"
            text.tag_add("match", idx, end)
            text.see(idx)
            search_state["start"] = end
            status_var.set(f"Match: {query}")
            return "break"

        def copy_all():
            html = text.get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(html)
            status_var.set(f"Copied {len(html):,} characters")

        find_entry.bind("<Return>", find_next)
        tk.Button(
            toolbar, text="Find", command=find_next,
            bg=self.ui["chrome_2"], fg=self.ui["text"],
            activebackground=self.ui["accent"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=12, cursor="hand2"
        ).pack(side="left", padx=4, pady=7)
        tk.Button(
            toolbar, text="Copy All", command=copy_all,
            bg=self.ui["chrome_2"], fg=self.ui["text"],
            activebackground=self.ui["accent"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=12, cursor="hand2"
        ).pack(side="left", padx=(2, 10), pady=7)

        if self._embedded_mode:
            future = self._executor.submit(get_embedded_chromium_html)

            def poll_html():
                if not window.winfo_exists():
                    return
                if not future.done():
                    window.after(40, poll_html)
                    return
                try:
                    set_html(future.result())
                except Exception as exc:
                    source_var.set("Chromium DOM inspection failed")
                    set_html(f"<!-- Tekzite could not inspect the live Chromium DOM: {exc} -->")

            window.after(20, poll_html)
        else:
            html = ""
            if isinstance(self._current_document, dict):
                html = self._current_document.get("html") or ""
            if not html:
                html = "<!-- No native HTML source is currently loaded. -->"
            set_html(html)

        find_entry.focus_set()
        return window

    def _load_hybrid_layout_snapshot_async(self, on_success, on_error=None):
        """Fetch Chromium's live layout/computed-style snapshot without blocking Tk."""
        if not self._embedded_mode:
            if on_error:
                on_error(RuntimeError("Hybrid layout is available on Chromium-backed pages"))
            return
        future = self._executor.submit(get_embedded_chromium_layout_snapshot)

        def poll():
            if not future.done():
                self.root.after(40, poll)
                return
            try:
                on_success(future.result())
            except Exception as exc:
                if on_error:
                    on_error(exc)
        self.root.after(20, poll)


    @staticmethod
    def _tk_color_from_css(value, fallback=None):
        """Return a Tk-friendly #RRGGBB color for the simple CSS colors in snapshots."""
        value = str(value or "").strip().lower()
        if not value or value in {"transparent", "rgba(0, 0, 0, 0)", "rgba(0,0,0,0)"}:
            return fallback
        if value.startswith("#"):
            if len(value) == 4:
                return "#" + "".join(ch * 2 for ch in value[1:])
            if len(value) >= 7:
                return value[:7]
        m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", value)
        if m:
            return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in m.groups())
        return fallback






    def on_close(self):
        self._navigation_generation += 1
        try:
            if self._page_state_after_id is not None:
                self.root.after_cancel(self._page_state_after_id)
        except Exception:
            pass
        try:
            close_embedded_chromium(clear_profile=bool(self.preferences.get("clear_browsing_data_on_exit", True)))
        except Exception:
            pass
        try:
            try:
                self._chromium_input_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._executor.shutdown(wait=False, cancel_futures=True)
        finally:
            try:
                if self._dwm_host is not None and os.name == "nt":
                    import ctypes
                    from ctypes import wintypes
                    ctypes.WinDLL("user32", use_last_error=True).DestroyWindow(wintypes.HWND(int(self._dwm_host)))
            except Exception:
                pass
            self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    BrowserApp().run()
