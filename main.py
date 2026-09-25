import time
import re
import os
import sys
import subprocess
import json
import base64
import tempfile
import shutil
import traceback
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog, filedialog, colorchooser
from browser_features import BrowserFeatures, omnibox_suggestions
from browser_state import load_bookmarks, load_session, read_json, session_snapshot, write_json, valid_url
from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageFont
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit, parse_qsl, urlencode
from privacy_core import strip_tracking_parameters, upgrade_to_https
import loopback_policy

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
    get_embedded_chromium_dwm_input_offset, get_embedded_chromium_input_scale, get_embedded_chromium_input_zoom_factor,
    get_embedded_chromium_software_input_scale,
    refresh_embedded_chromium_dwm_input_metrics,
    get_embedded_chromium_page_state, find_embedded_chromium_text,
    set_embedded_chromium_presentation, set_embedded_chromium_zoom, check_embedded_chromium_zoom,
    set_embedded_chromium_color_scheme,
    validate_and_recover_embedded_chromium_frame, record_embedded_surface_probe, record_embedded_native_recovery, sync_embedded_chromium_native_geometry,
    warm_embedded_chromium_io_channels, stop_embedded_chromium_loading,
    request_embedded_chromium_dwm_recrop, request_embedded_chromium_dwm_reregister, detach_embedded_chromium_dwm_thumbnail, network_engine_debug, privacy_stats,
    cleanup_abandoned_temporary_profiles, remove_profile_tree,
    start_standalone_auth_chromium,
    standalone_auth_chromium_running, wait_for_standalone_auth_chromium_release,
    standalone_google_auth_succeeded, close_standalone_auth_chromium,
)



START_URL = "https://www.startpage.com/"


UI_COLOR_DEFAULTS = {
    "bg": "#06080d",
    "chrome": "#0d1118",
    "chrome_2": "#121826",
    "chrome_hover": "#1a2233",
    "field": "#141c2a",
    "field_focus": "#1b2537",
    "border": "#2c3850",
    "border_soft": "#1a2233",
    "border_focus": "#8f7dff",
    "text": "#f5f7fb",
    "muted": "#9aa4bc",
    "muted_dim": "#69738a",
    "accent": "#8b75ff",
    "accent_hover": "#a08dff",
    "danger": "#ff6d87",
    "success": "#4ad594",
}

TOOLBAR_ITEM_IDS = ("back", "forward", "reload", "home", "address", "downloads", "menu")
TOOLBAR_ITEM_NAMES = {
    "back": "Back", "forward": "Forward", "reload": "Reload / Stop",
    "home": "Home", "address": "Address bar", "downloads": "Downloads", "menu": "Main menu",
}

CUSTOMIZATION_PRESETS = {
    "Aurora Glass": {
        **UI_COLOR_DEFAULTS,
        "bg": "#05070c", "chrome": "#0b111a", "chrome_2": "#111a28",
        "chrome_hover": "#1a2740", "field": "#121c2b", "field_focus": "#1b2940",
        "border": "#30415d", "border_soft": "#18263b", "border_focus": "#9b8aff",
        "text": "#f7f8fd", "muted": "#a3aec6", "muted_dim": "#6c7891",
        "accent": "#8f79ff", "accent_hover": "#aa9bff", "danger": "#ff6c87", "success": "#4fe0a0",
    },
    "OLED Neon": {
        **UI_COLOR_DEFAULTS,
        "bg": "#000000", "chrome": "#030609", "chrome_2": "#07100f",
        "chrome_hover": "#0c1d1a", "field": "#081311", "field_focus": "#0d211d",
        "border": "#153b32", "border_soft": "#0b211c", "border_focus": "#69f6c8",
        "text": "#effff9", "muted": "#9bc9bb", "muted_dim": "#55796e",
        "accent": "#64ebbf", "accent_hover": "#91ffd8", "danger": "#ff637d", "success": "#64ebbf",
    },
    "Aurora": dict(UI_COLOR_DEFAULTS),
    "Midnight": {
        **UI_COLOR_DEFAULTS, "bg": "#090b10", "chrome": "#0f131b", "chrome_2": "#151a24",
        "chrome_hover": "#1b2230", "field": "#181e29", "field_focus": "#202838",
        "border": "#2a3242", "border_soft": "#1d2430",
        "border_focus": "#7c68ff", "muted": "#929caf", "muted_dim": "#6f788a",
        "accent": "#7965ff", "accent_hover": "#8c7aff", "danger": "#ff6078", "success": "#45d483",
    },
    "OLED Black": {
        **UI_COLOR_DEFAULTS, "bg": "#000000", "chrome": "#050505", "chrome_2": "#0b0b0b",
        "chrome_hover": "#171717", "field": "#101010", "field_focus": "#1a1a1a",
        "border": "#292929", "border_soft": "#151515",
    },
    "Graphite": {
        **UI_COLOR_DEFAULTS, "bg": "#17191d", "chrome": "#202328", "chrome_2": "#292d33",
        "chrome_hover": "#333841", "field": "#252930", "field_focus": "#303640",
        "border": "#414750", "border_soft": "#2a2f36", "accent": "#6f8cff", "accent_hover": "#88a0ff",
    },
    "Light": {
        "bg": "#f4f6f9", "chrome": "#ffffff", "chrome_2": "#edf0f5", "chrome_hover": "#e3e7ee",
        "field": "#ffffff", "field_focus": "#f6f8fb", "border": "#c9d0da", "border_soft": "#dfe4ea",
        "border_focus": "#6355e8", "text": "#161a22", "muted": "#5d6675", "muted_dim": "#7c8592",
        "accent": "#6556e8", "accent_hover": "#7669ee", "danger": "#d63f55", "success": "#168f55",
    },
}

DEFAULT_CUSTOMIZATION = {
    "preset": "Aurora Glass",
    "colors": dict(CUSTOMIZATION_PRESETS["Aurora Glass"]),
    "font_family": "",
    "display_font_family": "",
    "monospace_font_family": "",
    "font_size": 11,
    "menu_font_size": 10,
    "tab_font_size": 10,
    "toolbar_font_size": 11,
    "ui_scale": 1.0,
    "density": "spacious",
    "spacing_generation": 2,
    "animations": True,
    "window_control_style": "traffic_lights",
    "tab_style": "soft",
    "show_app_bar": True,
    "show_brand_badge": True,
    "show_title_text": True,
    "show_version_in_title": False,
    "show_menu_bar": True,
    "show_window_controls": True,
    "show_tab_bar": True,
    "show_toolbar": True,
    "show_new_tab_button": True,
    "new_tab_button_position": "right",
    "show_tab_favicons": True,
    "show_tab_close_buttons": True,
    "show_tab_group_chips": True,
    "show_tab_active_indicator": True,
    "tab_title_chars": 28,
    "tab_min_width": 175,
    "tab_max_width": 330,
    "window_corner_radius": 24,
    "content_corner_radius": 18,
    "control_corner_radius": 16,
    "tab_position": "above_toolbar",
    "toolbar_order": list(TOOLBAR_ITEM_IDS),
    "toolbar_visible": {item: True for item in TOOLBAR_ITEM_IDS},
    "toolbar_label_style": "icons",
    "show_site_info_button": True,
    "show_bookmark_button": True,
    "show_scrollbar": True,
    "show_chrome_separator": True,
    "show_status_activity_dot": True,
    "show_status_version": True,
    "app_bar_height": 44,
    "tab_bar_height": 52,
    "toolbar_height": 72,
    "status_bar_height": 30,
    "find_bar_height": 46,
    "window_width": 1440,
    "window_height": 900,
    "window_min_width": 960,
    "window_min_height": 640,
    "start_maximized": False,
}

def _valid_hex_color(value, fallback):
    text = str(value or "").strip()
    return text.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else str(fallback)

def _normalized_customization(value):
    src = value if isinstance(value, dict) else {}
    # v10.5.15: migrate only an untouched v10.5.14 layout to the new spacious
    # defaults. Any user-adjusted spacing/size value opts out automatically.
    legacy_layout = {
        "font_size": 10, "tab_font_size": 9, "toolbar_font_size": 10,
        "ui_scale": 1.0, "density": "comfortable", "tab_title_chars": 24,
        "tab_min_width": 150, "tab_max_width": 290,
        "window_corner_radius": 22, "content_corner_radius": 16, "control_corner_radius": 14,
        "app_bar_height": 38, "tab_bar_height": 44, "toolbar_height": 62,
        "status_bar_height": 26, "find_bar_height": 40,
        "window_width": 1360, "window_height": 860,
        "window_min_width": 900, "window_min_height": 600,
    }
    if src and int(src.get("spacing_generation", 1) or 1) < 2:
        untouched = all(src.get(key, expected) == expected for key, expected in legacy_layout.items())
        if untouched:
            src = dict(src)
            for key in legacy_layout:
                src[key] = DEFAULT_CUSTOMIZATION[key]
            src["spacing_generation"] = 2
    out = dict(DEFAULT_CUSTOMIZATION)
    default_colors = dict(DEFAULT_CUSTOMIZATION.get("colors") or UI_COLOR_DEFAULTS)
    raw_colors = src.get("colors") if isinstance(src.get("colors"), dict) else {}
    colors = dict(default_colors) if not raw_colors else {}
    if raw_colors:
        for key, fallback in UI_COLOR_DEFAULTS.items():
            colors[key] = _valid_hex_color(raw_colors.get(key), fallback)
    out["colors"] = colors
    for key in out:
        if key in ("colors", "toolbar_visible", "toolbar_order"):
            continue
        if key in src:
            out[key] = src[key]
    for key in ("show_app_bar", "show_brand_badge", "show_title_text", "show_version_in_title", "show_menu_bar",
                "show_window_controls", "show_tab_bar", "show_toolbar", "show_new_tab_button", "show_tab_favicons",
                "show_tab_close_buttons", "show_tab_group_chips", "show_tab_active_indicator", "animations",
                "show_site_info_button", "show_bookmark_button", "show_scrollbar", "show_chrome_separator", "show_status_activity_dot", "show_status_version", "start_maximized"):
        out[key] = bool(out.get(key, DEFAULT_CUSTOMIZATION[key]))
    for key, low, high in (("font_size", 7, 22), ("menu_font_size", 7, 20), ("tab_font_size", 7, 20),
                           ("toolbar_font_size", 7, 22), ("tab_title_chars", 6, 80),
                           ("tab_min_width", 90, 420), ("tab_max_width", 120, 600),
                           ("window_corner_radius", 0, 48), ("content_corner_radius", 0, 40), ("control_corner_radius", 4, 28),
                           ("app_bar_height", 24, 80), ("tab_bar_height", 28, 90), ("toolbar_height", 38, 100),
                           ("status_bar_height", 18, 60), ("find_bar_height", 28, 80),
                           ("window_width", 720, 7680), ("window_height", 480, 4320),
                           ("window_min_width", 640, 3840), ("window_min_height", 400, 2160)):
        try:
            out[key] = max(low, min(high, int(out.get(key, DEFAULT_CUSTOMIZATION[key]))))
        except Exception:
            out[key] = DEFAULT_CUSTOMIZATION[key]
    try:
        out["ui_scale"] = max(0.70, min(1.60, float(out.get("ui_scale", 1.0))))
    except Exception:
        out["ui_scale"] = 1.0
    out["density"] = str(out.get("density") or "spacious") if str(out.get("density") or "spacious") in ("compact", "comfortable", "spacious") else "spacious"
    out["spacing_generation"] = 2
    out["window_control_style"] = str(out.get("window_control_style") or "traffic_lights") if str(out.get("window_control_style") or "traffic_lights") in ("tekzite", "traffic_lights") else "traffic_lights"
    out["tab_style"] = str(out.get("tab_style") or "soft") if str(out.get("tab_style") or "soft") in ("soft", "classic") else "soft"
    out["toolbar_label_style"] = str(out.get("toolbar_label_style") or "icons") if str(out.get("toolbar_label_style") or "icons") in ("icons", "text", "both") else "icons"
    out["tab_position"] = str(out.get("tab_position") or "above_toolbar") if str(out.get("tab_position") or "above_toolbar") in ("above_toolbar", "below_toolbar") else "above_toolbar"
    out["new_tab_button_position"] = str(out.get("new_tab_button_position") or "right") if str(out.get("new_tab_button_position") or "right") in ("left", "right") else "right"
    if int(out.get("tab_max_width", 330)) < int(out.get("tab_min_width", 175)):
        out["tab_max_width"] = int(out.get("tab_min_width", 175))
    order = []
    for item in src.get("toolbar_order", DEFAULT_CUSTOMIZATION["toolbar_order"]):
        item = str(item)
        if item in TOOLBAR_ITEM_IDS and item not in order:
            order.append(item)
    for item in TOOLBAR_ITEM_IDS:
        if item not in order:
            order.append(item)
    out["toolbar_order"] = order
    visible_src = src.get("toolbar_visible") if isinstance(src.get("toolbar_visible"), dict) else {}
    out["toolbar_visible"] = {item: bool(visible_src.get(item, True)) for item in TOOLBAR_ITEM_IDS}
    out["font_family"] = str(out.get("font_family") or "").strip()[:80]
    out["display_font_family"] = str(out.get("display_font_family") or "").strip()[:80]
    out["monospace_font_family"] = str(out.get("monospace_font_family") or "").strip()[:80]
    out["preset"] = str(out.get("preset") or "Custom")[:40]
    return out


DEFAULT_PREFERENCES = {
    "homepage": START_URL,
    "startup": "homepage",
    "restore_tabs": False,
    "quiet_mode": False,
    "adblock_sites": [],
    "new_tab": "blank",
    "renderer": "chromium",
    "reuse_open_tabs": True,
    # v10.5.48: local-only omnibox suggestions. No query is sent to a remote
    # autocomplete service; suggestions come from Tekzite-owned local/session data.
    "omnibox_suggestions_enabled": True,
    "show_status_bar": True,
    # v4.68: real native Chromium interaction is the default. The CDP
    # screenshot surface remains available only as an explicit diagnostic mode.
    "chromium_presentation": "native",
    # v4.56 privacy-first defaults.
    "network_diagnostics": "off",
    "strict_python_loopback": True,
    # v10.4 Privacy Core. Lockdown deliberately keeps browsing history/session
    # in memory only; bookmarks and explicit downloads remain user-owned data.
    "privacy_lockdown": True,
    "tracker_blocking_enabled": True,
    "strip_tracking_parameters": True,
    "strip_referrer": True,
    "https_first": True,
    "clear_browsing_data_on_exit": True,
    "page_zoom_percent": 100,
    # Hint websites through Chromium's prefers-color-scheme media feature.
    "website_color_scheme": "system",
    "adblock_enabled": True,
    # User-managed unpacked Chromium extensions. Tekzite's built-in local
    # services extension is always loaded separately and cannot be removed.
    "extensions": [],
    # v10.2 productivity + resource controls.
    "sleeping_tabs_enabled": True,
    "sleeping_tabs_minutes": 30,
    "tab_groups": {},
    "site_permissions": {},
    "download_prompt": False,
    "update_repository": "",
    "search_url_template": "https://www.startpage.com/sp/search?query={query}",
    "customization": dict(DEFAULT_CUSTOMIZATION),
}

def _profile_slug(value):
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", str(value or "")).strip().replace(" ", "-")
    value = re.sub(r"-+", "-", value).strip(".-_")
    return value[:48] or "Default"


def _requested_profile_name(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for index, item in enumerate(argv):
        if item == "--profile" and index + 1 < len(argv):
            return _profile_slug(argv[index + 1])
        if str(item).startswith("--profile="):
            return _profile_slug(str(item).split("=", 1)[1])
    return "Default"


def _state_root_for_profile(profile=None):
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
    return root if profile == "Default" else root / profiles_dir / profile


DEFAULT_BROWSER_REGISTERED_NAME = "Tekzite Browser"
DEFAULT_BROWSER_CLIENT_KEY = "TekziteBrowser"
DEFAULT_BROWSER_URL_PROGID = "TekziteBrowserURL"
DEFAULT_BROWSER_HTML_PROGID = "TekziteBrowserHTML"


def _requested_launch_target(argv=None):
    """Return a URL/file target supplied by Windows shell activation.

    Windows launches a registered desktop browser with the selected URL or HTML
    file as a positional argument.  Keep Tekzite's own switches out of this path
    so profiles/private mode continue to work normally.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    skip_next = False
    for item in argv:
        if skip_next:
            skip_next = False
            continue
        raw = str(item or "").strip()
        if not raw:
            continue
        if raw == "--profile":
            skip_next = True
            continue
        if raw.startswith("--profile=") or raw in {"--private", "--register-browser"}:
            continue
        if raw.startswith("--"):
            continue
        lowered = raw.lower()
        if lowered.startswith(("http://", "https://", "file://")):
            return raw
        try:
            candidate = Path(raw).expanduser()
            if candidate.is_file() and candidate.suffix.lower() in {".htm", ".html"}:
                return candidate.resolve().as_uri()
        except Exception:
            pass
    return None


def _browser_shell_command(executable=None, script_path=None, *, frozen=None, include_target=True):
    """Build the command Windows stores for Tekzite URL/file activation."""
    executable = str(executable or sys.executable)
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    parts = [f'"{executable}"']
    if not frozen:
        script_path = str(script_path or Path(__file__).resolve())
        parts.append(f'"{script_path}"')
    if include_target:
        parts.append('"%1"')
    return " ".join(parts)


def _tekzite_default_browser_registry_plan(executable=None, script_path=None, *, frozen=None):
    """Return HKCU registry values required for Windows Default Apps."""
    executable = str(executable or sys.executable)
    client = rf"Software\Clients\StartMenuInternet\{DEFAULT_BROWSER_CLIENT_KEY}"
    capabilities = client + r"\Capabilities"
    classes = r"Software\Classes"
    icon = f'"{executable}",0'
    open_target = _browser_shell_command(executable, script_path, frozen=frozen, include_target=True)
    open_browser = _browser_shell_command(executable, script_path, frozen=frozen, include_target=False)
    app_exe_name = Path(executable).name or "TekziteBrowser.exe"
    app_key = rf"{classes}\Applications\{app_exe_name}"

    entries = [
        (client, "", DEFAULT_BROWSER_REGISTERED_NAME),
        (client + r"\DefaultIcon", "", icon),
        (client + r"\shell\open\command", "", open_browser),
        (capabilities, "ApplicationName", DEFAULT_BROWSER_REGISTERED_NAME),
        (capabilities, "ApplicationDescription", "Tekzite Browser - Chromium rendered, privacy-focused Windows browser."),
        (capabilities, "ApplicationIcon", icon),
        (capabilities + r"\FileAssociations", ".htm", DEFAULT_BROWSER_HTML_PROGID),
        (capabilities + r"\FileAssociations", ".html", DEFAULT_BROWSER_HTML_PROGID),
        (capabilities + r"\URLAssociations", "http", DEFAULT_BROWSER_URL_PROGID),
        (capabilities + r"\URLAssociations", "https", DEFAULT_BROWSER_URL_PROGID),
        (capabilities + r"\StartMenu", "StartMenuInternet", DEFAULT_BROWSER_CLIENT_KEY),
        (r"Software\RegisteredApplications", DEFAULT_BROWSER_REGISTERED_NAME, capabilities),
        (rf"{classes}\{DEFAULT_BROWSER_URL_PROGID}", "", "Tekzite Browser URL"),
        (rf"{classes}\{DEFAULT_BROWSER_URL_PROGID}", "URL Protocol", ""),
        (rf"{classes}\{DEFAULT_BROWSER_URL_PROGID}\DefaultIcon", "", icon),
        (rf"{classes}\{DEFAULT_BROWSER_URL_PROGID}\shell\open\command", "", open_target),
        (rf"{classes}\{DEFAULT_BROWSER_HTML_PROGID}", "", "Tekzite Browser HTML Document"),
        (rf"{classes}\{DEFAULT_BROWSER_HTML_PROGID}\DefaultIcon", "", icon),
        (rf"{classes}\{DEFAULT_BROWSER_HTML_PROGID}\shell\open\command", "", open_target),
        (app_key, "FriendlyAppName", DEFAULT_BROWSER_REGISTERED_NAME),
        (app_key + r"\shell\open\command", "", open_target),
        (app_key + r"\SupportedTypes", ".htm", ""),
        (app_key + r"\SupportedTypes", ".html", ""),
    ]
    return entries


def _register_tekzite_default_browser(executable=None):
    """Register Tekzite as an available per-user browser on Windows."""
    if os.name != "nt":
        raise OSError("Default-browser registration is only available on Windows.")
    import winreg

    frozen = bool(getattr(sys, "frozen", False))
    executable = str(executable or sys.executable)
    for key_path, value_name, value_data in _tekzite_default_browser_registry_plan(
        executable, Path(__file__).resolve(), frozen=frozen
    ):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(value_data))

    # Tell Explorer that new association choices are available.
    try:
        import ctypes
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass
    return executable


def _windows_user_choice_progid(association, *, winreg_module=None):
    """Return Windows' current per-user ProgId for a URL/file association.

    This is deliberately read-only. Windows protects UserChoice with a hash and
    expects the user to make the final default-app selection in Settings.
    """
    association = str(association or "").strip().lower()
    if not association:
        return None
    if winreg_module is None:
        if os.name != "nt":
            return None
        import winreg as winreg_module

    if association in {"http", "https"}:
        key_path = (
            "Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\"
            + association
            + "\\UserChoice"
        )
    elif association in {".htm", ".html"}:
        key_path = (
            "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\"
            + association
            + "\\UserChoice"
        )
    else:
        raise ValueError(f"Unsupported browser association: {association}")

    try:
        with winreg_module.OpenKey(winreg_module.HKEY_CURRENT_USER, key_path, 0, winreg_module.KEY_READ) as key:
            value, _kind = winreg_module.QueryValueEx(key, "ProgId")
    except (FileNotFoundError, OSError):
        return None
    value = str(value or "").strip()
    return value or None


def _windows_effective_association_executable(association):
    """Return the executable Windows Shell currently uses for an association.

    UserChoice's ProgId is not a stable identity for a desktop browser. Windows
    can legitimately store an ``Applications\\some-browser.exe`` ProgId (or
    another app-specific ProgId) even when the browser was registered through
    Default Apps. Ask the Shell for the *effective executable* as the primary
    signal and keep UserChoice only as diagnostic/fallback information.
    """
    if os.name != "nt":
        return None
    association = str(association or "").strip().lower()
    if association not in {"http", "https", ".htm", ".html"}:
        raise ValueError(f"Unsupported browser association: {association}")
    try:
        import ctypes
        from ctypes import wintypes

        ASSOCF_NONE = 0x00000000
        ASSOCSTR_EXECUTABLE = 2
        shlwapi = ctypes.WinDLL("shlwapi", use_last_error=True)
        fn = shlwapi.AssocQueryStringW
        fn.argtypes = [
            wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
            wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        fn.restype = ctypes.c_long
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        hr = int(fn(ASSOCF_NONE, ASSOCSTR_EXECUTABLE, association, "open", buf, ctypes.byref(size)))
        if hr != 0:
            return None
        value = str(buf.value or "").strip().strip('"')
        return value or None
    except Exception:
        return None


def _looks_like_tekzite_executable(path):
    """Recognize installed and versioned Tekzite Windows executable names."""
    try:
        raw = str(path or "").strip().strip('"').replace("\\", "/")
        name = raw.rsplit("/", 1)[-1].lower()
    except Exception:
        return False
    compact = re.sub(r"[^a-z0-9]+", "", name)
    return compact.startswith("tekzitebrowser") and compact.endswith("exe")


def _tekzite_progid_matches(progid, *, executable=None):
    """Return True for both Tekzite's stable ProgIds and Windows app ProgIds."""
    value = str(progid or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered in {DEFAULT_BROWSER_URL_PROGID.lower(), DEFAULT_BROWSER_HTML_PROGID.lower()}:
        return True
    if lowered.startswith("applications\\"):
        candidate = value.split("\\")[-1]
        if _looks_like_tekzite_executable(candidate):
            return True
        if executable and candidate.lower() == Path(str(executable)).name.lower():
            return True
    return False


def _tekzite_default_browser_status(*, winreg_module=None, executable_resolver=None, executable=None):
    """Describe whether Windows currently routes web links to Tekzite.

    The effective Shell handler is authoritative. The raw UserChoice ProgId is
    retained for diagnostics because Windows 11 may represent the same browser
    with a different ProgId than the one Tekzite registered itself with.
    """
    supported = os.name == "nt" or winreg_module is not None or executable_resolver is not None
    if not supported:
        return {
            "supported": False,
            "is_default": False,
            "http": None,
            "https": None,
            "html": None,
            "htm": None,
        }

    values = {
        name: _windows_user_choice_progid(name, winreg_module=winreg_module)
        for name in ("http", "https", ".html", ".htm")
    }
    resolver = executable_resolver or _windows_effective_association_executable
    effective = {}
    for name in ("http", "https", ".html", ".htm"):
        try:
            effective[name] = resolver(name)
        except Exception:
            effective[name] = None

    current_executable = str(executable or sys.executable)

    def association_is_tekzite(name):
        # Preferred path: ask the Windows Shell which executable would actually
        # be launched. This also handles Applications\TekziteBrowser.exe and
        # versioned standalone release EXEs.
        handler_exe = effective.get(name)
        if handler_exe and _looks_like_tekzite_executable(handler_exe):
            return True
        try:
            if handler_exe and os.path.normcase(os.path.realpath(handler_exe)) == os.path.normcase(os.path.realpath(current_executable)):
                return True
        except Exception:
            pass
        # Fallback for test environments and systems where Shell association
        # lookup is unavailable. Do not require one exact UserChoice ProgId.
        return _tekzite_progid_matches(values.get(name), executable=current_executable)

    http_default = association_is_tekzite("http")
    https_default = association_is_tekzite("https")
    html_default = association_is_tekzite(".html")
    htm_default = association_is_tekzite(".htm")
    return {
        "supported": True,
        "is_default": bool(http_default and https_default),
        "http": values["http"],
        "https": values["https"],
        "html": values[".html"],
        "htm": values[".htm"],
        "http_executable": effective["http"],
        "https_executable": effective["https"],
        "html_executable": effective[".html"],
        "htm_executable": effective[".htm"],
        "http_default": http_default,
        "https_default": https_default,
        "html_default": html_default,
        "htm_default": htm_default,
    }


def _default_apps_settings_uri():
    return "ms-settings:defaultapps?registeredAppUser=" + quote(DEFAULT_BROWSER_REGISTERED_NAME, safe="")


def _open_tekzite_default_apps_settings():
    """Open Windows 11 Default Apps directly on Tekzite's registered entry."""
    if os.name != "nt":
        raise OSError("Default Apps settings are only available on Windows.")
    uri = _default_apps_settings_uri()
    try:
        os.startfile(uri)
    except Exception:
        # Older Windows builds may not understand registeredAppUser. The generic
        # Default Apps page still lets the user search for Tekzite Browser.
        os.startfile("ms-settings:defaultapps")
    return uri


def _set_windows_app_user_model_id():
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


def _preferences_path():
    base = _state_root_for_profile()
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


def _normalized_website_color_scheme(value, default="system"):
    value = str(value or default).strip().lower()
    return value if value in {"system", "dark", "light"} else str(default)


def _next_pointer_click_count(last_release_at, last_point, last_count, now, point, *, max_delay=0.50, max_distance=6.0):
    """Return Chromium clickCount for a press at *point*.

    Tk's DWM input plane does not reliably emit a distinct double-click event,
    while Chromium relies on clickCount=2/3 for native word/paragraph selection
    and double-click handlers. Count consecutive clicks by release time and
    page-space distance so the same path works at every Windows DPI scale.
    """
    try:
        px, py = float(point[0]), float(point[1])
        lx, ly = float(last_point[0]), float(last_point[1])
        dt = float(now) - float(last_release_at)
        distance2 = (px - lx) ** 2 + (py - ly) ** 2
        if 0.0 <= dt <= float(max_delay) and distance2 <= float(max_distance) ** 2:
            return min(3, max(1, int(last_count) + 1))
    except Exception:
        pass
    return 1

def _normalized_extension_entries(value):
    """Normalize persisted Extension Manager entries without touching disk."""
    result = []
    seen = set()
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, str):
            item = {"path": item, "enabled": True}
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        try:
            normalized = str(Path(path).expanduser().resolve())
        except Exception:
            normalized = os.path.abspath(os.path.expanduser(path))
        key = os.path.normcase(normalized)
        if key in seen:
            continue
        seen.add(key)
        result.append({"path": normalized, "enabled": bool(item.get("enabled", True))})
    return result


def _enabled_extension_paths(prefs):
    return [
        row["path"] for row in _normalized_extension_entries(prefs.get("extensions", []))
        if row.get("enabled")
    ]


def load_preferences():
    prefs = dict(DEFAULT_PREFERENCES)
    data = read_json(_preferences_path(), {})
    if isinstance(data, dict):
        for key in prefs:
            if key in data:
                prefs[key] = data[key]
    # Keep zoom canonical in memory. Older builds could leave a string value
    # behind; normalizing it here prevents a later dialog save from silently
    # restoring 100%.
    prefs["page_zoom_percent"] = _normalized_zoom_percent(
        prefs.get("page_zoom_percent", 100)
    )
    prefs["website_color_scheme"] = _normalized_website_color_scheme(
        prefs.get("website_color_scheme", "system")
    )
    prefs["extensions"] = _normalized_extension_entries(prefs.get("extensions", []))
    try:
        prefs["sleeping_tabs_minutes"] = max(5, min(240, int(prefs.get("sleeping_tabs_minutes", 30))))
    except Exception:
        prefs["sleeping_tabs_minutes"] = 30
    prefs["sleeping_tabs_enabled"] = bool(prefs.get("sleeping_tabs_enabled", True))
    prefs["omnibox_suggestions_enabled"] = bool(prefs.get("omnibox_suggestions_enabled", True))
    prefs["download_prompt"] = bool(prefs.get("download_prompt", False))
    prefs["strict_python_loopback"] = bool(prefs.get("strict_python_loopback", True))
    if not isinstance(prefs.get("tab_groups"), dict):
        prefs["tab_groups"] = {}
    if not isinstance(prefs.get("site_permissions"), dict):
        prefs["site_permissions"] = {}
    prefs["update_repository"] = str(prefs.get("update_repository") or "").strip()[:160]
    prefs["homepage"] = str(prefs.get("homepage") or START_URL).strip()[:32768] or START_URL
    template = str(prefs.get("search_url_template") or "https://www.startpage.com/sp/search?query={query}").strip()[:500]
    prefs["search_url_template"] = template if "{query}" in template else "https://www.startpage.com/sp/search?query={query}"
    prefs["customization"] = _normalized_customization(prefs.get("customization"))
    return prefs

def save_preferences(prefs):
    """Atomically save preferences with retry and one-generation recovery.

    ``write_json`` keeps the previous valid file as ``preferences.json.bak``.
    Antivirus/indexers can briefly race a replace on Windows, so preference
    commits still get three short retries and a read-back verification.
    """
    path = _preferences_path()
    payload = dict(prefs)
    payload["page_zoom_percent"] = _normalized_zoom_percent(
        payload.get("page_zoom_percent", 100)
    )
    payload["website_color_scheme"] = _normalized_website_color_scheme(
        payload.get("website_color_scheme", "system")
    )
    payload["extensions"] = _normalized_extension_entries(payload.get("extensions", []))
    payload["homepage"] = str(payload.get("homepage") or START_URL).strip()[:32768] or START_URL
    payload["search_url_template"] = str(payload.get("search_url_template") or "https://www.startpage.com/sp/search?query={query}").strip()[:500]
    if "{query}" not in payload["search_url_template"]:
        payload["search_url_template"] = "https://www.startpage.com/sp/search?query={query}"
    payload["customization"] = _normalized_customization(payload.get("customization"))
    last_error = None
    for attempt in range(3):
        try:
            write_json(path, payload)
            check = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(check, dict):
                raise OSError("saved preferences did not verify")
            if _normalized_zoom_percent(check.get("page_zoom_percent", 100)) != payload["page_zoom_percent"]:
                raise OSError("saved zoom preference did not verify")
            return path
        except Exception as exc:
            last_error = exc
            time.sleep(0.04 * (attempt + 1))
    raise OSError(f"Could not persist preferences: {last_error}")



BROWSER_VERSION = "10.5.80"


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






class _RoundedChromeButton(tk.Canvas):
    """Small rounded browser-chrome button backed by a Canvas.

    It intentionally mimics the tiny subset of ``tk.Button`` used by Tekzite
    (``configure(text=..., state=..., font=...)``, ``pack`` and ``winfo_*``),
    while drawing a modern pill/circle surface with true rounded corners.
    """

    def __init__(self, parent, text, command, *, surface_bg, hover_bg, fg,
                 hover_fg, border, hover_border, canvas_bg, font, padx=12,
                 pady=7, width=None, radius=12, disabled_fg=None):
        self._text = str(text or "")
        self._command = command
        self._surface_bg = surface_bg
        self._hover_bg = hover_bg
        self._fg = fg
        self._hover_fg = hover_fg
        self._border = border
        self._hover_border = hover_border
        self._canvas_bg = canvas_bg
        self._font = font
        self._padx = int(padx)
        self._pady = int(pady)
        self._radius = int(radius)
        self._state = "normal"
        self._hovered = False
        self._pressed = False
        self._focused = False
        self._selected = False
        self._disabled_fg = disabled_fg or fg
        self._explicit_width_chars = width
        pixel_w, pixel_h = self._measure()
        super().__init__(
            parent, width=pixel_w, height=pixel_h, bg=canvas_bg,
            highlightthickness=0, bd=0, relief="flat", cursor="hand2",
            takefocus=1,
        )
        self.bind("<Configure>", lambda _e: self._redraw(), add="+")
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.bind("<FocusOut>", lambda _e: self._set_focus(False))
        self.bind("<Return>", self._keyboard_invoke)
        self.bind("<space>", self._keyboard_invoke)
        self._redraw()

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        radius = max(2, min(int(radius), int((x2-x1)/2), int((y2-y1)/2)))
        points = [
            x1+radius,y1, x2-radius,y1, x2,y1, x2,y1+radius,
            x2,y2-radius, x2,y2, x2-radius,y2, x1+radius,y2,
            x1,y2, x1,y2-radius, x1,y1+radius, x1,y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _measure(self):
        try:
            f = tkfont.Font(font=self._font)
            text_w = max(8, int(f.measure(self._text)))
            text_h = max(14, int(f.metrics("linespace")))
        except Exception:
            text_w, text_h = max(8, len(self._text) * 8), 16
        if self._explicit_width_chars:
            text_w = max(text_w, int(self._explicit_width_chars) * 8)
        return max(34, text_w + self._padx * 2), max(30, text_h + self._pady * 2)

    def _resize_to_text(self):
        w, h = self._measure()
        try:
            super().configure(width=w, height=h)
        except Exception:
            pass

    def _redraw(self):
        try:
            self.delete("all")
            w = max(2, int(self.winfo_width() or self.cget("width")))
            h = max(2, int(self.winfo_height() or self.cget("height")))
            disabled = self._state == "disabled"
            engaged = bool((self._hovered or self._selected) and not disabled)
            fill = self._hover_bg if engaged else self._surface_bg
            if self._pressed and not disabled:
                fill = self._hover_bg
            outline = self._hover_border if ((engaged or self._focused) and not disabled) else self._border
            text_color = self._disabled_fg if disabled else (self._hover_fg if engaged else self._fg)
            press_inset = 2 if (self._pressed and not disabled) else 0
            self._round_rect(self, 1+press_inset, 1+press_inset, w-1-press_inset, h-1-press_inset,
                             min(self._radius, h//2), fill=fill, outline=outline, width=1.1)
            self.create_text(w/2, h/2 + (1 if press_inset else 0), text=self._text,
                             fill=text_color, font=self._font)
            self.configure(cursor="arrow" if disabled else "hand2")
        except Exception:
            pass

    def set_selected(self, selected):
        self._selected = bool(selected)
        self._redraw()

    def _set_focus(self, focused):
        self._focused = bool(focused)
        self._redraw()

    def _keyboard_invoke(self, _event=None):
        if self._state != "disabled" and callable(self._command):
            self._command()
        return "break"

    def _enter(self, _event=None):
        self._hovered = True
        self._redraw()

    def _leave(self, _event=None):
        self._hovered = False
        self._pressed = False
        self._redraw()

    def _press(self, _event=None):
        if self._state != "disabled":
            self._pressed = True
            self._redraw()

    def _release(self, event=None):
        if self._state == "disabled":
            return "break"
        inside = True
        try:
            inside = 0 <= int(event.x) <= self.winfo_width() and 0 <= int(event.y) <= self.winfo_height()
        except Exception:
            pass
        self._pressed = False
        self._redraw()
        if inside and callable(self._command):
            self._command()
        return "break"

    def set_palette(self, *, surface_bg=None, hover_bg=None, fg=None,
                    hover_fg=None, border=None, hover_border=None,
                    canvas_bg=None, radius=None, disabled_fg=None):
        if surface_bg is not None: self._surface_bg = surface_bg
        if hover_bg is not None: self._hover_bg = hover_bg
        if fg is not None: self._fg = fg
        if hover_fg is not None: self._hover_fg = hover_fg
        if border is not None: self._border = border
        if hover_border is not None: self._hover_border = hover_border
        if canvas_bg is not None:
            self._canvas_bg = canvas_bg
            try: super().configure(bg=canvas_bg)
            except Exception: pass
        if radius is not None: self._radius = int(radius)
        if disabled_fg is not None: self._disabled_fg = disabled_fg
        self._redraw()

    def configure(self, cnf=None, **kwargs):
        if cnf is None and not kwargs:
            return super().configure()
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        elif cnf not in (None, {}):
            return super().configure(cnf, **kwargs)
        redraw = False
        resize = False
        if "text" in kwargs:
            self._text = str(kwargs.pop("text") or "")
            redraw = resize = True
        if "state" in kwargs:
            self._state = str(kwargs.pop("state") or "normal")
            redraw = True
        if "font" in kwargs:
            self._font = kwargs.pop("font")
            redraw = resize = True
        if "fg" in kwargs: self._fg = kwargs.pop("fg"); redraw = True
        if "foreground" in kwargs: self._fg = kwargs.pop("foreground"); redraw = True
        if "activeforeground" in kwargs: self._hover_fg = kwargs.pop("activeforeground"); redraw = True
        if "activebackground" in kwargs: self._hover_bg = kwargs.pop("activebackground"); redraw = True
        if "highlightbackground" in kwargs: self._border = kwargs.pop("highlightbackground"); redraw = True
        # ``bg`` on a button means its rounded surface, not the square Canvas.
        if "bg" in kwargs: self._surface_bg = kwargs.pop("bg"); redraw = True
        if "background" in kwargs: self._surface_bg = kwargs.pop("background"); redraw = True
        result = super().configure(**kwargs) if kwargs else None
        if resize: self._resize_to_text()
        if redraw: self._redraw()
        return result

    config = configure

    def cget(self, key):
        key = str(key)
        if key in {"bg", "background"}: return self._surface_bg
        if key in {"fg", "foreground"}: return self._fg
        if key == "activebackground": return self._hover_bg
        if key == "activeforeground": return self._hover_fg
        if key == "highlightbackground": return self._border
        if key == "text": return self._text
        if key == "state": return self._state
        if key == "font": return self._font
        return super().cget(key)


class _AnimatedPopupMenu:
    """Rounded Tekzite popup menu with real hover/click feedback and reveal motion.

    This deliberately implements only the Menu API Tekzite uses.  Keeping the
    popup in Tk instead of delegating to a platform menu gives us predictable
    animation, pressed states and palette control without touching Chromium/DWM.
    """

    def __init__(self, app, parent=None, *, font_size=None):
        self.app = app
        self.parent = parent or app.root
        self.items = []
        self._postcommand = None
        self._window = None
        self._canvas = None
        self._rows = []
        self._hover_index = None
        self._pressed_index = None
        self._keyboard_index = None
        self._submenu_after_id = None
        self._open_submenu = None
        self._parent_menu = None
        self._anchor_button = None
        self._outside_bind_id = None
        self._outside_bind_previous = None
        self._animation_jobs = []
        # Linux software presentation lives inside the Tk root, so keep
        # autocomplete physically attached to the browser instead of using a
        # separately managed override-redirect window. That avoids compositor
        # placement drift on X11/XWayland/Wayland.
        self._inline_linux = sys.platform.startswith("linux")
        self._font = (app._ui_font_family, int(font_size or app._font_size(10)))
        self._surface = app.ui["chrome_2"]
        self._text = app.ui["text"]
        self._muted = app.ui["muted"]
        self._disabled = app.ui.get("muted_dim", app.ui["muted"])
        self._hover = app.ui["field_focus"]
        self._accent = app.ui["accent"]
        self._border = app.ui.get("border_soft", app.ui["border"])
        self._width = 240
        self._height = 1
        self._outer_pad = max(6, app._ui_padding(7))
        self._row_h = max(34, app._ui_padding(36))
        self._separator_h = max(8, app._ui_padding(9))

    def add_command(self, *, label="", command=None, accelerator="", state="normal", **_kwargs):
        self.items.append({"type": "command", "label": str(label), "command": command,
                           "accelerator": str(accelerator or ""), "state": str(state or "normal")})

    def add_separator(self, **_kwargs):
        self.items.append({"type": "separator"})

    def add_cascade(self, *, label="", menu=None, state="normal", accelerator="", **_kwargs):
        self.items.append({"type": "cascade", "label": str(label), "menu": menu,
                           "accelerator": str(accelerator or ""), "state": str(state or "normal")})
        if isinstance(menu, _AnimatedPopupMenu):
            menu._parent_menu = self

    def insert_command(self, index, **kwargs):
        self.items.insert(self._normalize_insert_index(index), {
            "type": "command", "label": str(kwargs.get("label", "")),
            "command": kwargs.get("command"), "accelerator": str(kwargs.get("accelerator", "") or ""),
            "state": str(kwargs.get("state", "normal") or "normal"),
        })

    def insert_separator(self, index, **_kwargs):
        self.items.insert(self._normalize_insert_index(index), {"type": "separator"})

    def _normalize_insert_index(self, index):
        if index in ("end", tk.END):
            return len(self.items)
        try:
            return max(0, min(len(self.items), int(index)))
        except Exception:
            return len(self.items)

    def entryconfigure(self, index, **kwargs):
        try:
            item = self.items[int(index)]
        except Exception:
            return
        for key in ("label", "state", "accelerator", "command"):
            if key in kwargs:
                item[key] = str(kwargs[key]) if key in {"label", "state", "accelerator"} else kwargs[key]
        if self._window is not None:
            self._rebuild_visible_menu()

    entryconfig = entryconfigure

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
        if "postcommand" in kwargs:
            self._postcommand = kwargs.pop("postcommand")
        if "font" in kwargs:
            self._font = kwargs.pop("font")
        if "bg" in kwargs: self._surface = kwargs.pop("bg")
        if "background" in kwargs: self._surface = kwargs.pop("background")
        if "fg" in kwargs: self._text = kwargs.pop("fg")
        if "foreground" in kwargs: self._text = kwargs.pop("foreground")
        if "activebackground" in kwargs: self._hover = kwargs.pop("activebackground")
        if "disabledforeground" in kwargs: self._disabled = kwargs.pop("disabledforeground")
        if "selectcolor" in kwargs: self._accent = kwargs.pop("selectcolor")
        # Native-menu compatibility options intentionally accepted and ignored.
        for key in ("activeforeground", "borderwidth", "activeborderwidth", "bd", "relief", "cursor"):
            kwargs.pop(key, None)
        if self._window is not None:
            self._rebuild_visible_menu()
        return None

    config = configure

    def is_posted(self):
        try:
            return self._window is not None and bool(self._window.winfo_exists())
        except Exception:
            return False

    def _measure(self):
        try:
            font = tkfont.Font(font=self._font)
            label_widths = [font.measure(str(i.get("label", ""))) for i in self.items if i.get("type") != "separator"]
            accel_widths = [font.measure(str(i.get("accelerator", ""))) for i in self.items if i.get("type") != "separator"]
            label_w = max(label_widths or [120])
            accel_w = max(accel_widths or [0])
        except Exception:
            label_w, accel_w = 180, 80
        self._width = max(230, min(620, int(label_w + accel_w + self.app._ui_padding(58))))
        y = self._outer_pad
        rows = []
        for index, item in enumerate(self.items):
            h = self._separator_h if item.get("type") == "separator" else self._row_h
            rows.append((index, y, y + h))
            y += h
        self._rows = rows
        self._height = max(20, y + self._outer_pad)
        return self._width, self._height

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        return _RoundedChromeButton._round_rect(canvas, x1, y1, x2, y2, radius, **kwargs)

    def _draw(self):
        canvas = self._canvas
        if canvas is None:
            return
        try:
            canvas.delete("all")
            w, h = self._width, self._height
            self._round_rect(canvas, 1, 1, w-1, h-1, min(16, h//2),
                             fill=self._surface, outline=self._border, width=1)
            font = self._font
            left = self._outer_pad + self.app._ui_padding(7)
            right = w - self._outer_pad - self.app._ui_padding(9)
            for index, y1, y2 in self._rows:
                item = self.items[index]
                typ = item.get("type")
                if typ == "separator":
                    cy = (y1 + y2) / 2
                    canvas.create_line(left, cy, right, cy, fill=self._border, width=1)
                    continue
                disabled = item.get("state") == "disabled"
                active = index in {self._hover_index, self._keyboard_index} and not disabled
                pressed = index == self._pressed_index and not disabled
                if active or pressed:
                    inset = self.app._ui_padding(4)
                    fill = self._accent if pressed else self._hover
                    self._round_rect(canvas, inset, y1+1, w-inset, y2-1,
                                     min(11, int((y2-y1)/2)), fill=fill, outline=fill)
                    if active and not pressed:
                        canvas.create_rectangle(inset, y1+8, inset+2, y2-8,
                                                fill=self._accent, outline="")
                color = self._disabled if disabled else self._text
                y_text = (y1 + y2) / 2 + (1 if pressed else 0)
                canvas.create_text(left + (1 if pressed else 0), y_text,
                                   text=item.get("label", ""), fill=color,
                                   font=font, anchor="w")
                accelerator = item.get("accelerator", "")
                if accelerator:
                    canvas.create_text(right - (14 if typ == "cascade" else 0), y_text,
                                       text=accelerator, fill=(self._disabled if disabled else self._muted),
                                       font=font, anchor="e")
                if typ == "cascade":
                    canvas.create_text(right, y_text, text="›", fill=color, font=font, anchor="e")
        except Exception:
            pass

    def _hit_index(self, y):
        try:
            y = int(y)
        except Exception:
            return None
        for index, y1, y2 in self._rows:
            if y1 <= y < y2 and self.items[index].get("type") != "separator":
                return index
        return None

    def _on_motion(self, event):
        index = self._hit_index(getattr(event, "y", -1))
        if index != self._hover_index:
            self._hover_index = index
            self._keyboard_index = None
            self._draw()
            self._schedule_cascade(index)

    def _on_leave(self, _event=None):
        # Keep the cascade parent highlighted while the pointer crosses the
        # tiny gap between parent and child popup.
        if self._open_submenu is None:
            self._hover_index = None
            self._draw()

    def _schedule_cascade(self, index):
        if self._submenu_after_id is not None:
            try: self.app.root.after_cancel(self._submenu_after_id)
            except Exception: pass
            self._submenu_after_id = None
        if index is None or self.items[index].get("type") != "cascade" or self.items[index].get("state") == "disabled":
            self._close_submenu()
            return
        try:
            self._submenu_after_id = self.app.root.after(140, lambda i=index: self._open_cascade(i))
        except Exception:
            pass

    def _open_cascade(self, index):
        self._submenu_after_id = None
        try:
            item = self.items[index]
        except Exception:
            return
        submenu = item.get("menu")
        if not isinstance(submenu, _AnimatedPopupMenu) or item.get("state") == "disabled":
            return
        if self._open_submenu is submenu and submenu.is_posted():
            return
        self._close_submenu()
        self._open_submenu = submenu
        submenu._parent_menu = self
        if not self._window:
            return
        try:
            x = int(self._window.winfo_rootx()) + self._width - 5
            row = next((r for r in self._rows if r[0] == index), None)
            y = int(self._window.winfo_rooty()) + (row[1] if row else self._outer_pad)
            submenu._post(x, y, root_binding=False)
        except Exception:
            self._open_submenu = None

    def _close_submenu(self):
        submenu = self._open_submenu
        self._open_submenu = None
        if isinstance(submenu, _AnimatedPopupMenu):
            submenu.dismiss(include_parent=False)

    def _on_press(self, event):
        index = self._hit_index(getattr(event, "y", -1))
        if index is None or self.items[index].get("state") == "disabled":
            self._pressed_index = None
            return
        self._pressed_index = index
        self._hover_index = index
        self._draw()

    def _on_release(self, event):
        index = self._hit_index(getattr(event, "y", -1))
        pressed = self._pressed_index
        self._pressed_index = None
        if index is None or index != pressed:
            self._draw()
            return "break"
        item = self.items[index]
        if item.get("state") == "disabled":
            self._draw()
            return "break"
        if item.get("type") == "cascade":
            self._open_cascade(index)
            self._draw()
            return "break"
        # Keep the pressed glow visible for a tiny beat. It makes the click
        # tactile without making the command itself feel delayed.
        self._pressed_index = index
        self._draw()
        try:
            self.app.root.after(45, lambda i=index: self._invoke(i))
        except Exception:
            self._invoke(index)
        return "break"

    def _invoke(self, index):
        try:
            item = self.items[index]
        except Exception:
            return
        self._pressed_index = None
        command = item.get("command")
        root = self._root_menu()
        root.dismiss(include_parent=False)
        if callable(command):
            try:
                self.app.root.after_idle(command)
            except Exception:
                command()

    def _root_menu(self):
        menu = self
        seen = set()
        while isinstance(menu._parent_menu, _AnimatedPopupMenu) and id(menu) not in seen:
            seen.add(id(menu))
            menu = menu._parent_menu
        return menu

    def _all_open_windows(self):
        windows = []
        menu = self._root_menu()
        while isinstance(menu, _AnimatedPopupMenu):
            if menu.is_posted(): windows.append(menu._window)
            menu = menu._open_submenu
        return windows

    def _outside_press(self, event):
        try:
            x, y = int(event.x_root), int(event.y_root)
            for win in self._all_open_windows():
                wx, wy = int(win.winfo_rootx()), int(win.winfo_rooty())
                ww, wh = int(win.winfo_width()), int(win.winfo_height())
                if wx <= x < wx + ww and wy <= y < wy + wh:
                    return
            root = self._root_menu()
            anchor = getattr(root, "_anchor_button", None)
            if anchor is not None:
                ax, ay = int(anchor.winfo_rootx()), int(anchor.winfo_rooty())
                aw, ah = int(anchor.winfo_width()), int(anchor.winfo_height())
                if ax <= x < ax + aw and ay <= y < ay + ah:
                    return
        except Exception:
            return
        self.dismiss(include_parent=False)

    def _keyboard_candidates(self):
        return [i for i, item in enumerate(self.items)
                if item.get("type") != "separator" and item.get("state") != "disabled"]

    def _on_key(self, event):
        key = str(getattr(event, "keysym", ""))
        if key == "Escape":
            self._root_menu().dismiss(include_parent=False)
            return "break"
        candidates = self._keyboard_candidates()
        if not candidates:
            return "break"
        if key in {"Down", "Up"}:
            current = self._keyboard_index if self._keyboard_index in candidates else None
            pos = candidates.index(current) if current in candidates else (-1 if key == "Down" else 0)
            pos = (pos + (1 if key == "Down" else -1)) % len(candidates)
            self._keyboard_index = candidates[pos]
            self._hover_index = self._keyboard_index
            self._draw()
            self._schedule_cascade(self._keyboard_index)
            return "break"
        if key in {"Return", "space"} and self._keyboard_index in candidates:
            index = self._keyboard_index
            if self.items[index].get("type") == "cascade": self._open_cascade(index)
            else: self._invoke(index)
            return "break"
        if key == "Right" and self._keyboard_index in candidates:
            self._open_cascade(self._keyboard_index)
            return "break"
        if key == "Left" and self._parent_menu is not None:
            self.dismiss(include_parent=False)
            try:
                if sys.platform.startswith("linux"):
                    self._parent_menu._canvas.focus_set()
                else:
                    self._parent_menu._window.focus_force()
            except Exception:
                pass
            return "break"
        return None

    def _animate_open(self, x, y):
        if not self._window:
            return
        self._animation_jobs.clear()
        steps = 7
        for step in range(steps + 1):
            def frame(s=step):
                if not self.is_posted():
                    return
                t = s / steps
                eased = 1.0 - (1.0 - t) ** 3
                yy = int(y - (1.0 - eased) * 9)
                try:
                    self._window.geometry(f"{self._width}x{self._height}+{int(x)}+{yy}")
                    self._window.attributes("-alpha", max(0.06, min(1.0, eased)))
                except Exception:
                    pass
            try:
                job = self.app.root.after(step * 12, frame)
                self._animation_jobs.append(job)
            except Exception:
                pass

    def _post(self, x, y, *, root_binding=True):
        if callable(self._postcommand):
            try: self._postcommand()
            except Exception: pass
        self.dismiss(include_parent=False)
        self._measure()
        try:
            screen_w = int(self.app.root.winfo_screenwidth())
            screen_h = int(self.app.root.winfo_screenheight())
            x = max(4, min(int(x), screen_w - self._width - 4))
            y = max(4, min(int(y), screen_h - self._height - 4))
        except Exception:
            x, y = int(x), int(y)
        win = tk.Toplevel(self.app.root)
        self._window = win
        win.overrideredirect(True)
        try: win.transient(self.app.root)
        except Exception: pass
        if os.name == "nt":
            try: win.attributes("-topmost", True)
            except Exception: pass
        try: win.attributes("-alpha", 0.06)
        except Exception: pass
        win.configure(bg=self._surface, bd=0, highlightthickness=0)
        canvas = tk.Canvas(win, width=self._width, height=self._height,
                           bg=self._surface, highlightthickness=0, bd=0,
                           relief="flat", cursor="hand2", takefocus=1)
        self._canvas = canvas
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<Leave>", self._on_leave)
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        win.bind("<KeyPress>", self._on_key)
        self._draw()
        self._animate_open(x, y)
        try:
            win.lift()
            if sys.platform.startswith("linux"):
                # Linux window managers already received the menu-opening click.
                # Keep keyboard navigation inside Tk without issuing a second
                # compositor-level activation request.
                canvas.focus_set()
            else:
                win.focus_force()
        except Exception:
            pass
        if root_binding:
            try:
                self._outside_bind_previous = self.app.root.bind_all("<ButtonPress-1>")
            except Exception:
                self._outside_bind_previous = ""
            self._outside_bind_id = self.app.root.bind_all("<ButtonPress-1>", self._outside_press, add="+")
            self.app._active_popup_menu = self
        return self

    def tk_popup(self, x, y, entry=None):
        root = self._root_menu()
        current = getattr(self.app, "_active_popup_menu", None)
        if current is root and root.is_posted():
            root.dismiss(include_parent=False)
            return
        if isinstance(current, _AnimatedPopupMenu) and current is not root:
            current.dismiss(include_parent=False)
        root._post(x, y, root_binding=True)

    def dismiss(self, include_parent=False):
        if include_parent and self._parent_menu is not None:
            return self._parent_menu.dismiss(include_parent=True)
        if self._submenu_after_id is not None:
            try: self.app.root.after_cancel(self._submenu_after_id)
            except Exception: pass
            self._submenu_after_id = None
        self._close_submenu()
        for job in tuple(self._animation_jobs):
            try: self.app.root.after_cancel(job)
            except Exception: pass
        self._animation_jobs.clear()
        if self._outside_bind_id is not None:
            try:
                self.app.root.tk.call("bind", "all", "<ButtonPress-1>", self._outside_bind_previous or "")
            except Exception:
                pass
            try:
                self.app.root.deletecommand(self._outside_bind_id)
            except Exception:
                pass
            self._outside_bind_id = None
            self._outside_bind_previous = None
        win = self._window
        self._window = None
        self._canvas = None
        self._hover_index = self._pressed_index = self._keyboard_index = None
        if win is not None:
            try: win.destroy()
            except Exception: pass
        if self._anchor_button is not None and hasattr(self._anchor_button, "set_selected"):
            try: self._anchor_button.set_selected(False)
            except Exception: pass
        if getattr(self.app, "_active_popup_menu", None) is self:
            self.app._active_popup_menu = None

    def grab_release(self):
        # Kept for tkinter.Menu compatibility.  Animated menus do not use a Tk
        # grab, so callers' traditional try/finally grab_release() is harmless.
        return None

    def _rebuild_visible_menu(self):
        if not self.is_posted():
            return
        try:
            x, y = int(self._window.winfo_rootx()), int(self._window.winfo_rooty())
        except Exception:
            return
        self._measure()
        try:
            self._window.configure(bg=self._surface)
            self._canvas.configure(width=self._width, height=self._height, bg=self._surface)
            self._window.geometry(f"{self._width}x{self._height}+{x}+{y}")
        except Exception:
            pass
        self._draw()


class _OmniboxSuggestionPopup:
    """Non-activating-looking autocomplete surface rendered above DWM.

    The address Entry keeps keyboard focus.  This popup never calls focus_force,
    which is essential because Chromium's DWM presenter and Tekzite's omnibox
    live in separate native focus domains.
    """

    ICONS = {
        "bookmark": "★",
        "tab": "▣",
        "history": "◷",
        "recent": "↺",
        "search": "⌕",
    }

    def __init__(self, app):
        self.app = app
        self.window = None
        self.canvas = None
        self.items = []
        self.selected = -1
        self.hover = None
        self.pressed = None
        self.rows = []
        self.width = 1
        self.height = 1
        self._animation_jobs = []
        # Keep Linux autocomplete inside the Tekzite root so the compositor
        # cannot place it as a detached override-redirect window.
        self._inline_linux = sys.platform.startswith("linux")

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        return _RoundedChromeButton._round_rect(canvas, x1, y1, x2, y2, radius, **kwargs)

    def is_visible(self):
        try:
            if self.window is None or not bool(self.window.winfo_exists()):
                return False
            if self._inline_linux:
                return bool(self.window.winfo_ismapped())
            return self.window.state() != "withdrawn"
        except Exception:
            return False

    def _hit(self, y):
        try:
            y = int(y)
        except Exception:
            return None
        for index, top, bottom in self.rows:
            if top <= y < bottom:
                return index
        return None

    def _draw(self):
        if self.canvas is None:
            return
        try:
            c = self.canvas
            c.delete("all")
            app = self.app
            surface = app.ui.get("chrome_2", app.ui["bg"])
            border = app.ui.get("border_soft", app.ui["border"])
            hover = app.ui.get("field_focus", app.ui["field"])
            self._round_rect(c, 1, 1, self.width - 1, self.height - 1,
                             min(16, max(8, self.height // 4)),
                             fill=surface, outline=border, width=1)
            title_font = (app._ui_font_family, app._font_size(10))
            meta_font = (app._ui_font_family, app._font_size(8))
            icon_font = ("Segoe UI Symbol", app._font_size(12))
            left = app._ui_padding(14)
            for index, top, bottom in self.rows:
                item = self.items[index]
                active = index == self.selected or index == self.hover
                if active:
                    inset = app._ui_padding(5)
                    self._round_rect(c, inset, top + 2, self.width - inset, bottom - 2,
                                     min(12, int((bottom - top) / 2)),
                                     fill=hover, outline=hover)
                    c.create_rectangle(inset, top + 11, inset + 2, bottom - 11,
                                       fill=app.ui["accent"], outline="")
                cy = (top + bottom) / 2
                icon = self.ICONS.get(item.get("kind"), "•")
                c.create_text(left, cy, text=icon, fill=app.ui["accent_hover"],
                              font=icon_font, anchor="w")
                tx = left + app._ui_padding(30)
                title = str(item.get("title") or item.get("value") or "")
                secondary = str(item.get("secondary") or "")
                c.create_text(tx, cy - app._ui_padding(8), text=title,
                              fill=app.ui["text"], font=title_font, anchor="w",
                              width=max(80, self.width - tx - app._ui_padding(18)))
                if secondary and secondary != title:
                    c.create_text(tx, cy + app._ui_padding(10), text=secondary,
                                  fill=app.ui["muted"], font=meta_font, anchor="w",
                                  width=max(80, self.width - tx - app._ui_padding(18)))
        except Exception:
            pass

    def _on_motion(self, event):
        index = self._hit(getattr(event, "y", -1))
        if index != self.hover:
            self.hover = index
            self._draw()

    def _on_leave(self, _event=None):
        if self.hover is not None:
            self.hover = None
            self._draw()

    def _on_press(self, event):
        self.pressed = self._hit(getattr(event, "y", -1))
        self.app._omnibox_popup_pointer_down = self.pressed is not None
        if self.pressed is not None:
            self.hover = self.pressed
            self._draw()
        return "break"

    def _on_release(self, event):
        index = self._hit(getattr(event, "y", -1))
        pressed = self.pressed
        self.pressed = None
        self.app._omnibox_popup_pointer_down = False
        if index is not None and index == pressed:
            self.app._activate_omnibox_suggestion(index, navigate=True)
        else:
            self._draw()
        return "break"

    def set_selected(self, index):
        self.selected = int(index) if 0 <= int(index) < len(self.items) else -1
        self._draw()

    def show(self, items, selected=-1):
        self.items = list(items or [])
        if not self.items:
            self.hide()
            return False
        app = self.app
        try:
            app.root.update_idletasks()
            width = max(360, int(app.address_shell.winfo_width()))
            if self._inline_linux:
                root_x = int(app.root.winfo_rootx())
                root_y = int(app.root.winfo_rooty())
                x = int(app.address_shell.winfo_rootx()) - root_x
                y = (
                    int(app.address_shell.winfo_rooty()) - root_y
                    + int(app.address_shell.winfo_height())
                    + app._ui_padding(3)
                )
            else:
                x = int(app.address_shell.winfo_rootx())
                y = int(app.address_shell.winfo_rooty() + app.address_shell.winfo_height() + app._ui_padding(3))
        except Exception:
            return False
        row_h = max(46, app._ui_padding(48))
        outer = max(6, app._ui_padding(7))
        height = outer * 2 + row_h * len(self.items)
        try:
            if self._inline_linux:
                host_w = max(1, int(app.root.winfo_width()))
                host_h = max(1, int(app.root.winfo_height()))
                width = min(width, max(360, host_w - 8))
                x = max(4, min(x, host_w - width - 4))
                if y + height > host_h - 4:
                    address_top = int(app.address_shell.winfo_rooty()) - int(app.root.winfo_rooty())
                    y = max(4, address_top - height - app._ui_padding(3))
            else:
                screen_w = int(app.root.winfo_screenwidth())
                screen_h = int(app.root.winfo_screenheight())
                width = min(width, max(360, screen_w - 8))
                x = max(4, min(x, screen_w - width - 4))
                if y + height > screen_h - 4:
                    y = max(4, int(app.address_shell.winfo_rooty()) - height - app._ui_padding(3))
        except Exception:
            pass
        self.width, self.height = width, height
        self.rows = [(i, outer + i * row_h, outer + (i + 1) * row_h) for i in range(len(self.items))]
        self.selected = int(selected) if 0 <= int(selected) < len(self.items) else -1

        created = False
        try:
            if self.window is None or not self.window.winfo_exists():
                if self._inline_linux:
                    win = tk.Frame(
                        app.root,
                        bg=app.ui.get("chrome_2", app.ui["bg"]),
                        bd=0,
                        highlightthickness=0,
                    )
                else:
                    win = tk.Toplevel(app.root)
                self.window = win
                created = True
                if not self._inline_linux:
                    win.overrideredirect(True)
                    try:
                        win.transient(app.root)
                        win.attributes("-topmost", True)
                        win.attributes("-alpha", 0.12 if app._motion_enabled() else 1.0)
                    except Exception:
                        pass
                win.configure(bg=app.ui.get("chrome_2", app.ui["bg"]), bd=0, highlightthickness=0)
                self.canvas = tk.Canvas(
                    win, bg=app.ui.get("chrome_2", app.ui["bg"]),
                    highlightthickness=0, bd=0, takefocus=0, cursor="hand2",
                )
                self.canvas.pack(fill="both", expand=True)
                self.canvas.bind("<Motion>", self._on_motion)
                self.canvas.bind("<Leave>", self._on_leave)
                self.canvas.bind("<ButtonPress-1>", self._on_press)
                self.canvas.bind("<ButtonRelease-1>", self._on_release)
            elif not self._inline_linux:
                self.window.deiconify()

            if self._inline_linux:
                self.window.place(x=x, y=y, width=width, height=height)
            else:
                self.window.geometry(f"{width}x{height}+{x}+{y}")
            self.canvas.configure(width=width, height=height)
            self._draw()
            self.window.lift()

            if not self._inline_linux:
                try:
                    self.window.attributes("-topmost", True)
                except Exception:
                    pass

            if created and app._motion_enabled():
                for step in range(1, 7):
                    def frame(s=step, base_y=y):
                        try:
                            if self.window is None or not self.window.winfo_exists():
                                return
                            t = s / 6.0
                            eased = 1.0 - (1.0 - t) ** 3
                            yy = int(base_y - (1.0 - eased) * 7)
                            if self._inline_linux:
                                self.window.place_configure(y=yy)
                            else:
                                self.window.geometry(f"{self.width}x{self.height}+{x}+{yy}")
                                self.window.attributes("-alpha", max(0.12, min(1.0, eased)))
                        except Exception:
                            pass
                    self._animation_jobs.append(app.root.after(step * 10, frame))
            elif not self._inline_linux:
                try:
                    self.window.attributes("-alpha", 1.0)
                except Exception:
                    pass
            return True
        except Exception:
            self.hide()
            return False

    def hide(self):
        for job in tuple(self._animation_jobs):
            try:
                self.app.root.after_cancel(job)
            except Exception:
                pass
        self._animation_jobs.clear()
        self.app._omnibox_popup_pointer_down = False
        win = self.window
        self.window = None
        self.canvas = None
        self.items = []
        self.rows = []
        self.hover = None
        self.pressed = None
        self.selected = -1
        if win is not None:
            try:
                if self._inline_linux:
                    win.place_forget()
                win.destroy()
            except Exception:
                pass


class BrowserApp(BrowserFeatures):
    def _apply_linux_managed_frameless(self, win):
        """Remove Linux WM decorations without making the window unmanaged.

        Tk's overrideredirect(True) bypasses the window manager on X11/XWayland,
        which can leave the previously active application owning the keyboard.
        Keep Tekzite as a normal managed window and request zero decorations via
        the widely-supported Motif WM hints instead. If the hint is unavailable
        or ignored, leave the native decoration in place rather than sacrificing
        correct activation/input behavior.
        """
        if not sys.platform.startswith("linux"):
            return False
        try:
            win.overrideredirect(False)
            win.update_idletasks()
        except Exception:
            return False
        try:
            if str(win.tk.call("tk", "windowingsystem")).lower() != "x11":
                # Future/native Wayland Tk should remain WM-managed. There is no
                # portable Tk decoration-removal API there yet.
                return False
        except Exception:
            return False
        display = None
        try:
            import ctypes
            import ctypes.util
            lib_name = ctypes.util.find_library("X11")
            if not lib_name:
                return False
            x11 = ctypes.CDLL(lib_name)
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            x11.XCloseDisplay.restype = ctypes.c_int
            x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            x11.XInternAtom.restype = ctypes.c_ulong
            x11.XChangeProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
            ]
            x11.XChangeProperty.restype = ctypes.c_int
            x11.XQueryTree.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                ctypes.POINTER(ctypes.c_uint),
            ]
            x11.XQueryTree.restype = ctypes.c_int
            x11.XFree.argtypes = [ctypes.c_void_p]
            x11.XFree.restype = ctypes.c_int
            x11.XFlush.argtypes = [ctypes.c_void_p]
            x11.XFlush.restype = ctypes.c_int

            display = x11.XOpenDisplay(None)
            if not display:
                return False
            motif = x11.XInternAtom(display, b"_MOTIF_WM_HINTS", 0)
            if not motif:
                return False
            # MWM_HINTS_DECORATIONS=1<<1, decorations=0.
            hints = (ctypes.c_ulong * 5)(2, 0, 0, 0, 0)
            data = ctypes.cast(hints, ctypes.POINTER(ctypes.c_ubyte))

            # Tk/X11 can put a toplevel inside a separate WM wrapper. KWin and
            # other reparenting window managers may decorate that outer window,
            # so writing the property only to winfo_id() is not sufficient.
            # Apply the same Motif hint to every relevant managed XID.
            xids = set()
            client_xid = 0
            try:
                client_xid = int(win.winfo_id())
                if client_xid:
                    xids.add(client_xid)
            except Exception:
                pass

            # Tk/X11 normally creates an extra wrapper window around the widget
            # XID. The window manager decorates that wrapper, not necessarily the
            # inner winfo_id(). Ask X11 directly for the real parent before the
            # first map and hint that window too.
            if client_xid:
                try:
                    root_ret = ctypes.c_ulong()
                    parent_ret = ctypes.c_ulong()
                    children_ret = ctypes.POINTER(ctypes.c_ulong)()
                    child_count = ctypes.c_uint()
                    if x11.XQueryTree(
                        display,
                        ctypes.c_ulong(client_xid),
                        ctypes.byref(root_ret),
                        ctypes.byref(parent_ret),
                        ctypes.byref(children_ret),
                        ctypes.byref(child_count),
                    ):
                        parent_xid = int(parent_ret.value or 0)
                        if parent_xid and parent_xid != int(root_ret.value or 0):
                            xids.add(parent_xid)
                    if children_ret:
                        x11.XFree(ctypes.cast(children_ret, ctypes.c_void_p))
                except Exception:
                    pass

            # Keep wm frame as a mapped-window fallback for reparenting WMs.
            try:
                frame_id = win.frame()
                if isinstance(frame_id, str):
                    frame_xid = int(frame_id, 0)
                else:
                    frame_xid = int(frame_id)
                if frame_xid:
                    xids.add(frame_xid)
            except Exception:
                try:
                    frame_id = win.tk.call("wm", "frame", win._w)
                    frame_xid = int(str(frame_id), 0)
                    if frame_xid:
                        xids.add(frame_xid)
                except Exception:
                    pass

            for xid in xids:
                x11.XChangeProperty(
                    display,
                    ctypes.c_ulong(xid),
                    ctypes.c_ulong(motif),
                    ctypes.c_ulong(motif),
                    32,
                    0,
                    data,
                    5,
                )
            x11.XFlush(display)
            return bool(xids)
        except Exception:
            return False
        finally:
            if display:
                try:
                    x11.XCloseDisplay(display)
                except Exception:
                    pass

    def _write_stability_log(self, heading, details):
        """Best-effort local diagnostics without turning an error into a crash."""
        try:
            folder = Path(getattr(self, "_state_directory", _preferences_path().parent))
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "stability.log"
            if path.exists() and path.stat().st_size > 512 * 1024:
                rotated = path.with_name("stability.log.1")
                try:
                    rotated.unlink(missing_ok=True)
                    os.replace(path, rotated)
                except OSError:
                    pass
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {heading}\n")
                handle.write(str(details).rstrip() + "\n\n")
        except Exception:
            pass

    def _report_tk_callback_exception(self, exc_type, exc_value, exc_tb):
        """Contain Tk callback failures and leave a useful local breadcrumb."""
        if getattr(self, "_closing", False):
            return
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        self._write_stability_log("Tk callback error", details)
        status = getattr(self, "status_var", None)
        if status is not None:
            try:
                status.set(f"Recovered UI error: {exc_type.__name__}: {exc_value}")
            except Exception:
                pass

    def _cancel_all_tk_after_jobs(self):
        """Cancel queued Tk timers before native/Chromium teardown begins."""
        try:
            jobs = self.root.tk.call("after", "info")
        except Exception:
            return
        if isinstance(jobs, str):
            jobs = (jobs,) if jobs else ()
        for job in tuple(jobs or ()):
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def _native_root_hwnd(self):
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

    def __init__(self):
        self.browser_version = BROWSER_VERSION
        self._profile_name = _requested_profile_name()
        os.environ["TEKZITE_BROWSER_PROFILE"] = self._profile_name
        self._private_mode = "--private" in sys.argv[1:]
        self._external_launch_target = _requested_launch_target()
        self._private_profile_dir = None
        self._privacy_profile_dir = None
        # Clean abandoned private/lockdown trees from crashed prior sessions.
        # Live owner PIDs and newly-created markerless directories are protected.
        try:
            cleanup_abandoned_temporary_profiles()
        except Exception:
            pass
        if self._private_mode:
            # Always create a fresh profile, even when this process was spawned
            # by another private window and inherited its environment. Embed the
            # UI PID in the directory name so crash scavenging can prove liveness
            # even before Chromium writes its own owner marker.
            self._private_profile_dir = tempfile.mkdtemp(prefix=f"Tekzite-Private-{os.getpid()}-")
            os.environ["TEKZITE_CHROMIUM_PROFILE"] = self._private_profile_dir
            os.environ["TEKZITE_PRIVATE_MODE"] = "1"
        else:
            # A normal child spawned from a private process must never inherit
            # the parent's temporary Chromium identity. Named profiles receive
            # their own Chromium storage; Default preserves the historical path.
            os.environ.pop("TEKZITE_PRIVATE_MODE", None)
            if self._profile_name == "Default":
                os.environ.pop("TEKZITE_CHROMIUM_PROFILE", None)
            else:
                profile_dir = _state_root_for_profile(self._profile_name) / "Chromium Bridge Profile"
                profile_dir.mkdir(parents=True, exist_ok=True)
                os.environ["TEKZITE_CHROMIUM_PROFILE"] = str(profile_dir)

        self._dpi_awareness_enabled = _enable_per_monitor_dpi_awareness()
        self._windows_app_user_model_id_set = _set_windows_app_user_model_id()
        self.root = tk.Tk()
        # On Linux, keep the root unmapped until the managed-frameless WM hint
        # has been installed. Reparenting WMs such as KWin decide decorations
        # during the first map; setting _MOTIF_WM_HINTS afterward can be ignored.
        if sys.platform.startswith("linux"):
            try:
                self.root.withdraw()
            except Exception:
                pass
        self._apply_app_icon()
        self._taskbar_presence_guard_after_id = None
        try:
            self._taskbar_presence_guard_after_id = self.root.after(250, self._taskbar_presence_guard)
        except Exception:
            pass
        self._google_auth_handoff_active = False
        self._google_auth_launch_future = None
        self._google_auth_release_future = None
        self._google_auth_success_future = None
        self._google_auth_close_future = None
        self._google_auth_handle = None
        self._google_auth_return_url = None
        self._google_auth_source_url = None
        self._google_auth_refresh_pending_url = None
        self.preferences = load_preferences()
        if not self._private_mode and self.preferences.get("privacy_lockdown", True):
            # Privacy Lockdown never points Chromium at a persistent profile.
            # Cookies/cache/storage live only in this process-owned temp tree.
            self._privacy_profile_dir = tempfile.mkdtemp(prefix=f"Tekzite-Privacy-{os.getpid()}-")
            os.environ["TEKZITE_CHROMIUM_PROFILE"] = self._privacy_profile_dir
        strict_python_loopback = bool(self.preferences.get("strict_python_loopback", True))
        os.environ["TEKZITE_STRICT_PYTHON_LOOPBACK"] = "1" if strict_python_loopback else "0"
        os.environ["TEKZITE_PRIVACY_LOCKDOWN"] = "1" if self.preferences.get("privacy_lockdown", True) else "0"
        os.environ["TEKZITE_TRACKER_BLOCKING"] = "1" if self.preferences.get("tracker_blocking_enabled", True) else "0"
        os.environ["TEKZITE_STRIP_REFERRER"] = "1" if self.preferences.get("strip_referrer", True) else "0"
        os.environ["TEKZITE_HTTPS_FIRST"] = "1" if self.preferences.get("https_first", True) else "0"
        os.environ["TEKZITE_LOOPBACK_ROLE"] = "browser"
        os.environ["TEKZITE_LOOPBACK_AUDIT_LOG"] = str(_preferences_path().parent / "loopback-blocked.jsonl")
        # Process-local Python egress guard. Only ports registered by Tekzite's
        # proxy/CDP bootstrap may receive outbound loopback connects. Public
        # internet sockets and Chromium's own sockets are not affected.
        loopback_policy.install(strict_python_loopback)
        self.customization = _normalized_customization(self.preferences.get("customization"))
        self.preferences["customization"] = self.customization
        # v10.5.19: the app-owned motion system starts before the first map so
        # the main shell can fade in rather than appearing as a single hard cut.
        self._startup_motion_enabled = bool(
            self.customization.get("animations", True)
            and not self.preferences.get("quiet_mode", False)
        )
        try:
            self.root.attributes("-alpha", 0.0 if self._startup_motion_enabled else 1.0)
        except Exception:
            pass
        # v7.3: prefer Windows' variable UI font for Tekzite chrome.  This keeps
        # the shell visually closer to modern native Windows/Firefox typography
        # without touching web-page CSS or changing site layout.
        self._ui_font_family = "Segoe UI"
        self._ui_display_font_family = "Segoe UI"
        self._ui_monospace_font_family = "Consolas"
        try:
            import tkinter.font as tkfont
            families = {str(name).casefold(): str(name) for name in tkfont.families(self.root)}
            if os.name == "nt":
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
                                       families.get("dejavu sans mono") or "DejaVu Sans Mono")
            requested_ui = str(self.customization.get("font_family") or "").casefold()
            requested_display = str(self.customization.get("display_font_family") or "").casefold()
            requested_mono = str(self.customization.get("monospace_font_family") or "").casefold()
            self._ui_font_family = families.get(requested_ui, automatic_ui_font) if requested_ui else automatic_ui_font
            self._ui_display_font_family = families.get(requested_display, automatic_display_font) if requested_display else automatic_display_font
            self._ui_monospace_font_family = families.get(requested_mono, automatic_mono_font) if requested_mono else automatic_mono_font
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
        title_version = f" v{BROWSER_VERSION}" if self.customization.get("show_version_in_title", True) else ""
        self.root.title(f"Tekzite Browser{' — Private' if self._private_mode else ''}{' — ' + self._profile_name if self._profile_name != 'Default' else ''}{title_version}")
        self.root.geometry(f"{self.customization['window_width']}x{self.customization['window_height']}")
        self.root.minsize(self.customization["window_min_width"], self.customization["window_min_height"])
        # Windows uses Tk's override-redirect shell. Linux must remain a
        # window-manager-managed application so the active window owns keyboard
        # input correctly. Decorations are removed with Motif hints where the WM
        # supports them, with a normal decorated window as the safe fallback.
        if sys.platform.startswith("linux"):
            self.root.overrideredirect(False)
            # Install the decoration hint synchronously while the root is still
            # withdrawn. This is the critical pre-map path for KWin/Mutter/Xfwm.
            self._apply_linux_managed_frameless(self.root)
        else:
            self.root.overrideredirect(True)
        self._window_restore_geometry = None
        self._window_maximized = False
        self._window_drag_offset = (0, 0)
        self._fullscreen = False
        self._window_rounding_signature = None
        self._dwm_host_region_signature = None
        self._address_focused = False
        # v10.5.48 local omnibox autocomplete state. The popup is created only
        # while the real Entry owns focus and never performs remote lookups.
        self._omnibox_suggestion_popup = None
        self._omnibox_suggestions = []
        self._omnibox_suggestion_index = -1
        self._omnibox_suggestion_after_id = None
        self._omnibox_popup_pointer_down = False
        self._omnibox_recent_inputs = []
        self._omnibox_update_suspended = False
        # v8.1: lightweight Tk-side animation state. Animations are intentionally
        # confined to Tekzite chrome; Chromium/DWM remains completely untouched.
        self._ui_animation_serial = 0
        self._ui_animation_jobs = {}
        # v10.5.22: opening tabs animate from a compact pill into their full
        # width. Store start times by tab id so a tab-strip rebuild during
        # navigation can resume the same animation instead of snapping.
        self._tab_open_animation_started = {}
        self._tab_open_animation_duration = 0.20
        self._loading_spinner_frames = ("◐", "◓", "◑", "◒")
        user_extension_paths = [] if self.preferences.get("privacy_lockdown", True) else _enabled_extension_paths(self.preferences)
        os.environ["TEKZITE_USER_EXTENSIONS"] = json.dumps(user_extension_paths)
        self._state_directory = _preferences_path().parent
        if self.preferences.get("privacy_lockdown", True) and not self._private_mode:
            for sensitive_name in ("session.json", "history.json"):
                try:
                    (self._state_directory / sensitive_name).unlink(missing_ok=True)
                except OSError:
                    pass
        self.root.report_callback_exception = self._report_tk_callback_exception
        self.bookmarks = load_bookmarks(self._state_directory / "bookmarks.json")
        self._init_features()
        self._zoom_watchdog_after_id = None
        self._zoom_watchdog_interval_ms = 5000
        self._zoom_watchdog_checks = 0
        self._zoom_watchdog_corrections = 0
        self._zoom_watchdog_last_status = None
        # Privacy settings are exported before the first network/Chromium
        # process is started, so the helper inherits a privacy-first policy.
        os.environ["TEKZITE_NETWORK_LOG_LEVEL"] = str(self.preferences.get("network_diagnostics", "off"))
        os.environ["TEKZITE_ADBLOCK_ENABLED"] = "1" if self.preferences.get("adblock_enabled", True) else "0"
        os.environ["TEKZITE_DOWNLOAD_PROMPT"] = "1" if self.preferences.get("download_prompt", False) else "0"

        # v4.28 visual shell: OLED-friendly, compact and intentionally distinct
        # from the embedded Chromium content surface.
        # v7.9: tighter OLED chrome.  Keep the shell low-clutter, but give
        # active/hover states a clearer hierarchy so the interface reads as one
        # coherent browser rather than a collection of Tk controls.
        self.ui = dict(self.customization.get("colors") or UI_COLOR_DEFAULTS)
        self.root.configure(bg=self.ui["bg"])

        # v4.31 is fully frameless. Keep Tekzite as a normal taskbar/Alt-Tab
        # application even though the native Windows title bar is removed.
        self.root.after(20, self._apply_frameless_app_style)
        self.root.after(40, self._prewarm_native_window_drag)

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
            width=max(8, int(12 * float(self.customization.get("ui_scale", 1.0)))),
        )
        style.configure("Tekzite.TNotebook", background=self.ui["bg"], borderwidth=0)
        style.configure("Tekzite.TNotebook.Tab", background=self.ui["chrome_2"], foreground=self.ui["text"], padding=(10, 6))
        style.map("Tekzite.TNotebook.Tab", background=[("selected", self.ui["accent"]), ("active", self.ui["chrome_hover"])], foreground=[("selected", "#ffffff")])
        style.configure("Treeview", background=self.ui["field"], fieldbackground=self.ui["field"], foreground=self.ui["text"],
                        rowheight=max(20, self._font_size(22)), bordercolor=self.ui["border"], font=(self._ui_font_family, self._font_size(9)))
        style.map("Treeview", background=[("selected", self.ui["accent"])], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=self.ui["chrome_2"], foreground=self.ui["text"],
                        bordercolor=self.ui["border"], font=(self._ui_font_family, self._font_size(9)))
        style.configure("TCombobox", fieldbackground=self.ui["field"], background=self.ui["chrome_2"], foreground=self.ui["text"],
                        arrowcolor=self.ui["muted"], bordercolor=self.ui["border"], font=(self._ui_font_family, self._font_size(9)))
        style.map("TCombobox", fieldbackground=[("readonly", self.ui["field"])], foreground=[("readonly", self.ui["text"])],
                  selectbackground=[("readonly", self.ui["accent"])], selectforeground=[("readonly", "#ffffff")])
        self._install_global_motion_bindings()

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
        self._page_state_poll_ms = 850
        self._page_state_inflight = set()
        self._favicon_images = {}
        self._sleeping_tabs_after_id = None
        self._find_bar_visible = False
        # v6.0: Chromium is the only web engine.  Tekzite owns browser UI,
        # while all page parsing/layout/JS/media/storage live in Chromium.
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tekzite-chromium")
        # v8.3: serialize tab activations away from Tk's UI thread. Chromium's
        # Target.activateTarget may briefly wait on the browser/compositor; doing
        # that work inline made Tekzite chrome advance before the DWM page did.
        self._tab_switch_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-tab-switch")
        self._tab_switch_serial = 0
        self._tab_switch_pending_id = None
        self._tab_switch_future = None
        # v10.5.32: closing a Chromium target can make Chromium/DWM churn even
        # when the close itself runs on a worker. Keep closed targets parked for
        # a short grace period so an immediate + click never competes with target
        # destruction. The queue is drained only after the user has had time to
        # start the next action.
        self._closed_target_retire_queue = set()
        self._closed_target_retire_after_id = None
        self._closed_tab_handoff_after_id = None
        self._closed_tab_handoff_retire_target = None
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
        # v10.5.47: keep the safe lazy Tk sink as a focus anchor, but do not
        # depend on Tk receiving KeyPress events from it.  DWM presentation is a
        # separate top-level visual mirror and some Windows builds can report
        # native focus without ever translating that focus into a Tk key event.
        # A foreground-only GetAsyncKeyState poller now supplies the missing
        # physical-key path without installing a raw Python WNDPROC.
        self._dwm_keyboard_sink_widget = None
        self._dwm_keyboard_sink_hwnd = None
        self._dwm_keyboard_sink_focused = False
        self._dwm_keyboard_sink_messages = 0
        self._dwm_keyboard_sink_chars = 0
        self._dwm_keyboard_sink_last = None
        self._dwm_keyboard_sink_create_count = 0
        self._dwm_keyboard_sink_focus_count = 0
        self._dwm_keyboard_poll_after_id = None
        self._dwm_keyboard_poll_active = False
        self._dwm_keyboard_poll_down = {}
        self._dwm_keyboard_poll_events = 0
        self._dwm_keyboard_poll_chars = 0
        self._dwm_keyboard_poll_last = None
        self._dwm_keyboard_poll_error = None
        self._dwm_keyboard_poll_foreground = False
        self._dwm_user32 = None
        # v6.1: keep the raw DWM destination hidden until Chromium has a
        # verified frame, and coalesce move/resize traffic while the user drags
        # the Tekzite window.
        self._dwm_surface_ready = False
        self._dwm_host_visible = False
        self._dwm_host_alpha = None
        # v10.5.50: minimizing the frameless Tk root must also suppress the
        # separate DWM destination popup.  Otherwise a queued geometry/reveal
        # callback can remap the owned popup while the real Tekzite window is
        # iconic, leaving the raw presentation surface in front on taskbar
        # restore.  Keep this separate from _dwm_surface_ready so Chromium does
        # not have to re-bootstrap after every minimize/restore cycle.
        self._dwm_host_suspended_for_minimize = False
        # v10.5.50: taskbar restore is a cold DWM recovery, not merely a popup
        # remap.  Windows can retain the destination HWND while silently dropping
        # the live thumbnail composition after an override-redirect/iconify cycle.
        # Keep the destination hidden until a fresh thumbnail registration has
        # succeeded and the compositor has been flushed.
        self._dwm_restore_recovery_after_id = None
        self._dwm_restore_recovery_count = 0
        self._dwm_restore_recovery_success = None
        # v10.5.54: Tk can transiently report a frameless root as ``withdrawn``
        # during the override-redirect -> iconify -> restore wrapper handoff.
        # Track the taskbar round-trip explicitly so a withdrawn root is
        # deiconified and retried instead of being mistaken for a successful
        # restore and disappearing while the Python process keeps running.
        self._taskbar_restore_pending = False
        self._taskbar_restore_after_id = None
        self._taskbar_restore_watchdog_id = None
        self._taskbar_restore_attempts = 0
        self._taskbar_restore_geometry = None
        self._dwm_host_owner_hwnd = None
        self._dwm_reveal_pending = False
        self._dwm_reveal_after_id = None
        self._dwm_host_rect = None
        self._dwm_geometry_after_id = None
        self._dwm_pending_resize = False
        # v10.5.70: a forced recrop/metrics refresh must not be lost merely
        # because the visible viewport already matches the cached size. Maximize
        # can change Chromium's native/CSS transform without changing this cache
        # again by the time the recrop callback runs.
        self._dwm_pending_force_resize = False
        self._dwm_pending_input_metrics_refresh = False
        self._dwm_last_chromium_viewport = None
        self._dwm_last_root_configure_size = None
        # v10.5.4: DWM thumbnails are visual mirrors, not native Chromium input
        # surfaces.  Keep a tiny Win32 pointer watchdog as an insurance layer
        # behind Tk's normal hit-transparent edge_host bindings.  If Windows
        # ever leaves the popup itself on top of hit testing, physical pointer
        # motion and left-button transitions are still forwarded to Chromium
        # over the same CDP path.  State matching prevents duplicate clicks when
        # Tk is already receiving the events normally.
        self._dwm_pointer_after_id = None
        self._dwm_pointer_inside = False
        self._dwm_pointer_last_screen_xy = None
        self._dwm_pointer_last_page_xy = None
        self._dwm_tk_pointer_event_at = 0.0
        # v9.7: live window dragging is latest-value-only. Tk geometry and DWM
        # destination updates are both coalesced so raw mouse-motion bursts do
        # not become CPU/compositor bursts. Chromium is never resized for a
        # pure top-level move.
        self._window_drag_active = False
        self._window_drag_pending_xy = None
        self._window_drag_after_id = None
        # v9.8: cache the native top-level/DWM drag path before the first drag
        # so the first mouse movement does not pay Win32/Tk setup costs. During
        # an active drag both windows move in the same native frame.
        self._native_drag_user32 = None
        self._native_drag_hwnd = 0
        self._native_drag_dwm_offset = None
        self._native_drag_last_xy = None
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
        self._privacy_tracking_params_stripped = 0

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
        self.app_bar = tk.Frame(
            self.root, bg=self.ui["bg"], height=self._ui_metric("app_bar_height", 44), highlightthickness=0,
        )
        self.app_bar.pack(fill="x")
        self.app_bar.pack_propagate(False)
        self.app_bar.bind("<ButtonPress-1>", self._start_window_drag)
        self.app_bar.bind("<B1-Motion>", self._drag_window)
        self.app_bar.bind("<ButtonRelease-1>", self._end_window_drag)
        self.app_bar.bind("<Double-Button-1>", lambda event: self._toggle_maximize())

        self.app_brand = tk.Frame(self.app_bar, bg=self.ui["bg"])
        self.app_brand.pack(side="left", padx=(self._ui_padding(16), self._ui_padding(14)), fill="y")
        self.app_brand.bind("<ButtonPress-1>", self._start_window_drag)
        self.app_brand.bind("<B1-Motion>", self._drag_window)
        self.app_brand.bind("<ButtonRelease-1>", self._end_window_drag)
        self.brand_badge = tk.Label(
            self.app_brand, text="T", fg="#ffffff", bg=self.ui["accent"],
            font=(self._ui_font_family, max(7, int(self._custom("menu_font_size", 9))), "bold"),
            width=2, padx=1, pady=2,
        )
        self.brand_badge.pack(side="left", pady=self._ui_padding(5))
        title_version = f"  v{BROWSER_VERSION}" if self._custom("show_version_in_title", True) else ""
        self.title_label = tk.Label(
            self.app_brand, text=f"Tekzite{' • Private' if self._private_mode else ''}{title_version}",
            fg=self.ui["text"], bg=self.ui["bg"],
            font=(self._ui_font_family, max(7, int(self._custom("menu_font_size", 9))), "bold"),
        )
        self.title_label.pack(side="left", padx=(self._ui_padding(7), 0))
        self.title_label.bind("<ButtonPress-1>", self._start_window_drag)
        self.title_label.bind("<B1-Motion>", self._drag_window)
        self.title_label.bind("<ButtonRelease-1>", self._end_window_drag)

        self.menu_strip = tk.Frame(self.app_bar, bg=self.ui["bg"])
        self.menu_strip.pack(side="left", fill="y")
        self._browser_menu_buttons = []
        self._browser_menus = []
        self._build_browser_menus(self.menu_strip)

        self.window_controls = tk.Frame(self.app_bar, bg=self.ui["bg"])
        self.window_controls.pack(side="right", fill="y", padx=(self._ui_padding(8), self._ui_padding(14)), pady=self._ui_padding(7))
        self.window_control_buttons = [
            self._make_window_control(self.window_controls, "minimize", self._minimize_window),
            self._make_window_control(self.window_controls, "maximize", self._toggle_maximize),
            self._make_window_control(self.window_controls, "close", self.on_close, close=True),
        ]
        for button in self.window_control_buttons:
            button.pack(side="left", padx=(0, self._ui_padding(6)))
        if self.window_control_buttons:
            try:
                self.window_control_buttons[-1].pack_configure(padx=(0, 0))
            except Exception:
                pass
        self._refresh_window_controls()
        if self._custom("window_control_style", "traffic_lights") == "traffic_lights":
            try:
                self.window_controls.pack_forget()
                self.window_controls.pack(side="left", fill="y", padx=(self._ui_padding(14), self._ui_padding(6)), pady=self._ui_padding(7), before=self.app_brand)
            except Exception:
                pass

        # ── Browser tab strip ───────────────────────────────────────────────
        self.tab_bar = tk.Frame(self.root, bg=self.ui["chrome"], height=self._ui_metric("tab_bar_height", 52), highlightthickness=0)
        self.tab_bar.pack(fill="x")
        self.tab_bar.pack_propagate(False)
        self.tab_items = tk.Frame(self.tab_bar, bg=self.ui["chrome"])
        self.tab_items.pack(side="left", fill="both", expand=True, padx=(self._ui_padding(16), self._ui_padding(10)), pady=(self._ui_padding(8), self._ui_padding(7)))
        # Keep + in the same row as the tabs so "right" means immediately
        # after the open tabs, not the far-right edge of the whole strip.
        self.new_tab_button = _RoundedChromeButton(
            self.tab_items, "+", self._new_tab, surface_bg=self.ui["chrome_2"],
            hover_bg=self.ui["field_focus"], fg=self.ui["muted"], hover_fg=self.ui["text"],
            border=self.ui["border_soft"], hover_border=self.ui["border_focus"],
            canvas_bg=self.ui["chrome"],
            font=(self._ui_font_family, max(10, int(self._custom("tab_font_size", 9)) + 4)),
            padx=self._ui_padding(12), pady=self._ui_padding(6), width=None,
            radius=self._ui_metric("control_corner_radius", 16), disabled_fg=self.ui["muted_dim"],
        )

        # ── Tekzite browser chrome ──────────────────────────────────────────
        self.toolbar = tk.Frame(
            self.root, bg=self.ui["chrome"], height=self._ui_metric("toolbar_height", 72), highlightthickness=0,
        )
        self.toolbar.pack(fill="x")
        self.toolbar.pack_propagate(False)

        def chrome_button(parent, text, command, *, accent=False, width=None):
            bg = self.ui["accent"] if accent else self.ui["field"]
            hover = self.ui["accent_hover"] if accent else self.ui["field_focus"]
            fg = "#ffffff" if accent else self.ui["muted"]
            return _RoundedChromeButton(
                parent, text, command, surface_bg=bg, hover_bg=hover, fg=fg,
                hover_fg="#ffffff", border=self.ui["border_soft"],
                hover_border=self.ui["accent_hover"] if accent else self.ui["border_focus"],
                canvas_bg=self.ui["chrome"],
                font=(self._ui_font_family, max(7, int(self._custom("toolbar_font_size", 10))), "bold" if accent else "normal"),
                padx=self._ui_padding(14), pady=self._ui_padding(9), width=width,
                radius=self._ui_metric("control_corner_radius", 16),
                disabled_fg=self.ui["muted_dim"],
            )

        self.back_button = chrome_button(self.toolbar, self._toolbar_text("back"), self.go_back, width=None)
        self.forward_button = chrome_button(self.toolbar, self._toolbar_text("forward"), self.go_forward, width=None)
        self.reload_button = chrome_button(self.toolbar, self._toolbar_text("reload"), self._reload_or_stop_current, width=None)
        self.home_button = chrome_button(self.toolbar, self._toolbar_text("home"), self._go_home, width=None)

        self.url_var = tk.StringVar(value=self._homepage_url())
        self.address_shell = tk.Frame(
            self.toolbar, bg=self.ui["chrome"], highlightthickness=0, bd=0,
        )
        self.address_backdrop = tk.Canvas(
            self.address_shell, bg=self.ui["chrome"], highlightthickness=0, bd=0, takefocus=0,
        )
        self.address_backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.address_inner = tk.Frame(self.address_shell, bg=self.ui["field"], bd=0, highlightthickness=0)
        self.address_inner.pack(fill="both", expand=True, padx=self._ui_padding(9), pady=self._ui_padding(6))
        self.address_inner.lift()
        self.address_shell.bind("<Configure>", lambda _e: self._redraw_address_shell(), add="+")
        self.site_info_button = tk.Button(
            self.address_inner, text="◈", command=self._show_site_info, fg=self.ui["accent_hover"], bg=self.ui["field"],
            activeforeground=self.ui["text"], activebackground=self.ui["field_focus"], relief="flat", bd=0,
            highlightthickness=0, cursor="hand2", font=("Segoe UI Symbol", max(8, int(self._custom("toolbar_font_size", 10)) + 1)),
            padx=self._ui_padding(5), pady=1,
        )
        self.site_info_button.pack(side="left", padx=(self._ui_padding(8), self._ui_padding(2)))

        # Keep the editable Entry for real keyboard/caret/selection behavior, but
        # cover it with a Pillow-rendered preview while unfocused.  Tk's Win32
        # ClearType path can produce colored/black-looking subpixel halves on
        # very dark omnibox surfaces; the preview uses grayscale antialiasing
        # instead, so the resting URL stays clean and uniformly colored.
        self.address_text_host = tk.Frame(self.address_inner, bg=self.ui["field"], bd=0, highlightthickness=0)
        # v10.5.21: do not squeeze the editable/preview layer into a thin
        # horizontal strip. The address shell already provides the vertical
        # breathing room; a second large pady here left only a few pixels for
        # the actual URL surface on the spacious layout.
        self.address_text_host.pack(side="left", fill="both", expand=True,
                                    padx=(self._ui_padding(3), self._ui_padding(6)), pady=self._ui_padding(1))
        self.address = tk.Entry(
            self.address_text_host, textvariable=self.url_var, bg=self.ui["field"], fg=self.ui["text"],
            insertbackground=self.ui["text"], selectbackground=self.ui["accent"], selectforeground="#ffffff",
            relief="flat", bd=0, highlightthickness=0,
            font=("Segoe UI", max(10, int(self._custom("font_size", 10)) + 1)),
        )
        self.address.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.address_preview = tk.Canvas(
            self.address_text_host, bg=self.ui["field"], highlightthickness=0, bd=0, takefocus=0,
        )
        self.address_preview.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._address_preview_photo = None
        self._address_preview_after_id = None
        self.address_text_host.bind("<Configure>", lambda _e: self._schedule_address_preview_render(), add="+")
        self.address_preview.bind("<Button-1>", self._activate_address_preview)
        self.address_preview.bind("<Button-3>", self._show_address_preview_context_menu)
        self.url_var.trace_add("write", self._on_omnibox_text_changed)

        self.bookmark_button = tk.Button(
            self.address_inner, text="☆", command=self._toggle_current_bookmark, fg=self.ui["muted"], bg=self.ui["field"],
            activeforeground=self.ui["accent_hover"], activebackground=self.ui["field_focus"], relief="flat", bd=0,
            highlightthickness=0, cursor="hand2", font=("Segoe UI Symbol", max(10, int(self._custom("toolbar_font_size", 10)) + 3)),
            padx=self._ui_padding(7), pady=1,
        )
        self.bookmark_button.pack(side="right", padx=(0, self._ui_padding(4)))
        self.address.bind("<Return>", self._on_omnibox_return)
        self.address.bind("<Down>", lambda event: self._move_omnibox_suggestion(1))
        self.address.bind("<Up>", lambda event: self._move_omnibox_suggestion(-1))
        self.address.bind("<Tab>", self._accept_omnibox_suggestion)
        self.address.bind("<Escape>", lambda event: self._hide_omnibox_suggestions(return_break=True))
        self.address.bind("<FocusIn>", lambda event: self._set_address_shell_focus(True))
        self.address.bind("<FocusOut>", lambda event: self._set_address_shell_focus(False))
        self.address.bind("<Button-1>", self._on_address_pointer_down, add="+")
        self.address.bind("<FocusIn>", self._on_address_focus_in, add="+")
        self.address.bind("<FocusOut>", self._on_address_focus_out, add="+")
        self.address.bind("<Button-3>", self._show_address_context_menu)
        self.address.bind("<Control-Shift-v>", lambda event: self._paste_and_go())

        self.downloads_button = chrome_button(self.toolbar, self._toolbar_text("downloads"), self._show_downloads, width=None)
        self.main_menu_button = chrome_button(self.toolbar, self._toolbar_text("menu"), self._show_main_menu, width=None)
        self._toolbar_widgets = {
            "back": self.back_button, "forward": self.forward_button, "reload": self.reload_button, "home": self.home_button,
            "address": self.address_shell, "downloads": self.downloads_button, "menu": self.main_menu_button,
        }
        self._apply_toolbar_layout()

        # Debug actions remain available from Tools, but they no longer occupy
        # the primary browser toolbar. Keep an unattached frame attribute for
        # compatibility with older diagnostics/tests that probe it.
        self.debug_group = tk.Frame(self.toolbar, bg=self.ui["chrome"])

        # v8.0 find-in-page bar. It lives in Tekzite chrome and uses Chromium's
        # own live DOM selection, so no site CSS/HTML is modified.
        self.find_bar = tk.Frame(self.root, bg=self.ui["chrome"], height=0, highlightthickness=0)
        self.find_bar.pack_propagate(False)
        self.find_var = tk.StringVar()
        self.find_entry = tk.Entry(
            self.find_bar, textvariable=self.find_var, bg=self.ui["field"], fg=self.ui["text"],
            insertbackground=self.ui["text"], selectbackground=self.ui["accent"], selectforeground="#ffffff",
            relief="flat", bd=0, highlightthickness=1, highlightbackground=self.ui["border"],
            font=(self._ui_font_family, self._font_size(9)),
        )
        self.find_entry.pack(side="left", fill="x", expand=True, padx=(16, 8), pady=8)
        self.find_entry.bind("<Return>", lambda event: self._find_in_page(False))
        self.find_entry.bind("<Shift-Return>", lambda event: self._find_in_page(True))
        self.find_entry.bind("<Escape>", lambda event: self._hide_find_bar())
        for text, cmd in (("↑", lambda: self._find_in_page(True)), ("↓", lambda: self._find_in_page(False)), ("×", self._hide_find_bar)):
            b = tk.Button(self.find_bar, text=text, command=cmd, bg=self.ui["chrome_2"], fg=self.ui["text"],
                          activebackground=self.ui["field_focus"], activeforeground="#ffffff", relief="flat", bd=0,
                          highlightthickness=0, cursor="hand2", padx=10, pady=3, font=(self._ui_font_family, self._font_size(9)))
            b.pack(side="left", padx=(0, 5), pady=5)

        self.chrome_separator = tk.Frame(self.root, bg=self.ui["border_soft"], height=1)
        self.chrome_separator.pack(fill="x")

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
        if sys.platform.startswith("linux"):
            self.edge_host.bind("<Button-4>", self._on_chromium_surface_linux_wheel)
            self.edge_host.bind("<Button-5>", self._on_chromium_surface_linux_wheel)
        self.edge_host.bind("<KeyPress>", self._on_chromium_surface_key)
        self.edge_host.bind("<ButtonRelease-2>", self._on_chromium_surface_middle_click)
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
        # v8.4: hover/cursor traffic is isolated from critical clicks, wheel,
        # and keyboard input so cosmetic probes cannot delay interaction.
        self._chromium_hover_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-cdp-hover")
        # v8.9: cursor DOM probes are cosmetic and can be more expensive than
        # Input.dispatchMouseEvent. Keep them off the actual hover lane so a
        # computed-style query can never delay page hover/mousemove delivery.
        self._chromium_cursor_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-cdp-cursor")
        # v8.7: wheel traffic gets its own CDP lane too. Precision touchpads and
        # high-resolution wheels can emit bursts that must never queue ahead of
        # a click or keystroke on the critical input lane.
        self._chromium_scroll_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tekzite-cdp-scroll")
        self._chromium_scroll_future = None
        self._chromium_pending_wheel = None
        self._chromium_wheel_after_id = None
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
        self._chromium_motion_future = None
        # v7.7: track a real left-button drag so Chromium can create native
        # text selections through the DWM input plane.
        self._chromium_left_button_down = False
        self._chromium_drag_selecting = False
        self._chromium_press_point = None
        # v10.5.7: preserve real browser gesture semantics over the DWM mirror.
        # Chromium needs clickCount=2/3 for double/triple click selection, while
        # drag moves are coalesced so sliders/scrollbars cannot flood the input
        # FIFO and delay the matching release.
        self._chromium_press_click_count = 1
        self._chromium_last_click_release_at = 0.0
        self._chromium_last_click_point = None
        self._chromium_last_click_count = 0
        self._chromium_pending_drag = None
        self._chromium_drag_after_id = None
        self._chromium_drag_future = None
        # v5.08: software presentation can sustain a noticeably smoother
        # interaction cadence now that the viewport contract and Tk image are
        # reused between frames. 33 ms targets ~30 FPS without queueing captures.
        self._chromium_active_frame_ms = 24
        self._chromium_idle_frame_ms = 750
        # Hover is coalesced, but at ~80 Hz so menus/tooltips feel immediate.
        self._chromium_motion_interval_ms = 8
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
        if sys.platform.startswith("linux"):
            self.chromium_surface.bind("<Button-4>", self._on_chromium_surface_linux_wheel)
            self.chromium_surface.bind("<Button-5>", self._on_chromium_surface_linux_wheel)
        self.chromium_surface.bind("<KeyPress>", self._on_chromium_surface_key)
        self.chromium_surface.bind("<ButtonRelease-2>", self._on_chromium_surface_middle_click)
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
        if self._custom("show_scrollbar", True):
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
        self.status_bar = tk.Frame(
            self.root, bg=self.ui["chrome"], height=self._ui_metric("status_bar_height", 30),
            highlightbackground=self.ui["border"], highlightthickness=1,
        )
        self.status_bar.pack(fill="x")
        if not getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True):
            self.status_bar.pack_forget()
        self.status_bar.pack_propagate(False)
        self.status_activity_dot = tk.Label(
            self.status_bar, text="●", fg=self.ui.get("success", "#45d483"), bg=self.ui["chrome"],
            font=(self._ui_font_family, self._font_size(7)),
        )
        self.status_activity_dot.pack(side="left", padx=(self._ui_padding(16), self._ui_padding(8)))
        self.status_text_label = tk.Label(
            self.status_bar, textvariable=self.status_var, anchor="w", fg=self.ui["muted"], bg=self.ui["chrome"],
            font=(self._ui_font_family, max(7, int(self._custom("menu_font_size", 9)))),
        )
        self.status_text_label.pack(side="left", fill="x", expand=True)
        self.status_version_label = tk.Label(
            self.status_bar, text=f"{'Private • ' if self._private_mode else ''}v{BROWSER_VERSION}",
            fg=self.ui["muted"], bg=self.ui["chrome"],
            font=(self._ui_font_family, max(7, int(self._custom("menu_font_size", 9)) - 1)),
        )
        self.status_version_label.pack(side="right", padx=(self._ui_padding(10), self._ui_padding(16)))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-l>", lambda event: self._focus_address())
        self.root.bind("<Control-t>", lambda event: self._new_tab())
        self.root.bind("<Control-Shift-N>", lambda event: self._new_private_window())
        self.root.bind("<Control-w>", lambda event: self._close_active_tab())
        self.root.bind("<Control-Shift-T>", lambda event: self._restore_closed_tab())
        self.root.bind("<Control-j>", lambda event: self._show_downloads())
        self.root.bind("<Control-h>", lambda event: self._show_history())
        self.root.bind("<Control-d>", lambda event: self._bookmark_current_page())
        self.root.bind("<Control-Shift-O>", lambda event: self._show_bookmarks())
        self.root.bind("<Control-f>", lambda event: self._show_find_bar())
        self.root.bind("<Control-Tab>", lambda event: self._cycle_tab(1))
        self.root.bind("<Control-Shift-Tab>", lambda event: self._cycle_tab(-1))
        self.root.bind("<Control-r>", lambda event: self._reload_current())
        self.root.bind("<Control-u>", lambda event: self.inspect_html())
        self.root.bind("<Control-comma>", lambda event: self.show_preferences())
        self.root.bind("<Control-Shift-comma>", lambda event: self._show_customize_browser())
        self.root.bind("<Control-Shift-Alt-R>", lambda event: self._reset_interface_customization(confirm=True))
        self.root.bind("<F5>", lambda event: self._reload_current())
        self.root.bind("<Alt-Left>", lambda event: self.go_back())
        self.root.bind("<Alt-Right>", lambda event: self.go_forward())
        self.root.bind("<Alt-Home>", lambda event: self._go_home())
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

        self._apply_customization_runtime(repack=True, refresh_tabs=False)
        if self._custom("start_maximized", False):
            self.root.after_idle(self._toggle_maximize)

        # Create the initial tab before startup navigation.
        self._new_tab(switch=True, navigate=False)

        # Let Tk map and paint the chrome before startup navigation begins.
        self._schedule_zoom_watchdog(initial=True)
        self._schedule_page_state_poll(initial=True)

        startup_mode = getattr(self, "preferences", DEFAULT_PREFERENCES).get("startup", "homepage")
        external_target = getattr(self, "_external_launch_target", None)
        startup_action = (
            (lambda target=external_target: self.navigate_to(target, add_history=True, reuse_existing=False))
            if external_target else
            ((lambda: self.navigate_to(self._homepage_url(), add_history=True))
             if startup_mode == "homepage" else self._focus_address)
        )
        # Map Linux only after the WM decoration hint is present. The window
        # remains a normal managed application, so the compositor owns activation
        # and keyboard focus exactly like Dolphin/Firefox/etc.
        if sys.platform.startswith("linux"):
            try:
                self._apply_linux_managed_frameless(self.root)
                self.root.deiconify()
                # Re-apply once after mapping so reparenting WMs also see the
                # hint on their final wrapper. This never requests focus.
                self.root.after(40, lambda: self._apply_linux_managed_frameless(self.root)
                                if self.root.winfo_exists() else None)
            except Exception:
                try:
                    self.root.deiconify()
                except Exception:
                    pass

        # Shell activation must win over session restore. A Windows http/https
        # click should open exactly the requested URL, never an old session.
        if external_target:
            self.root.after_idle(lambda: self._feature_startup(startup_action))
        else:
            # v9.2: start Chromium/homepage preparation on the first Tk idle turn.
            # The old fixed 250 ms chrome-paint delay was pure startup latency.
            self.root.after_idle(lambda: self._feature_startup(lambda: self._restore_startup_tabs(startup_action)))

    def _restore_startup_tabs(self, fallback):
        if getattr(self, "_private_mode", False) or self.preferences.get("privacy_lockdown", False):
            fallback()
            return
        session = load_session(self._state_directory / "session.json") if self.preferences.get("restore_tabs", True) else {"tabs": []}
        if not session["tabs"]:
            fallback()
            return
        if session.get("clean_exit") is False:
            restore = self._ask_yes_no(
                "Restore Tekzite Tabs",
                "Tekzite did not finish its previous shutdown cleanly. Restore the previous tabs?",
                parent=self.root,
            )
            if not restore:
                try:
                    write_json(self._state_directory / "session.json", {"tabs": [], "active": 0, "clean_exit": True})
                except OSError:
                    pass
                fallback()
                return
        # Reuse the initial blank tab; only the selected page starts Chromium.
        for index, saved in enumerate(session["tabs"]):
            tab = self.tabs[0] if index == 0 else self._new_tab(switch=False, navigate=False)
            tab.update(url=saved["url"], title=saved["title"], pinned=bool(saved.get("pinned")), group=str(saved.get("group") or ""), restore_pending=bool(saved["url"]))
        selected = self.tabs[session["active"]]
        self.active_tab_id = selected["id"]
        self.history = []
        self.history_index = -1
        self.url_var.set(selected["url"])
        self._refresh_tab_strip()
        if selected.pop("restore_pending", False):
            self.navigate_to(selected["url"], reuse_existing=False)
        else:
            self._focus_address()

    def _save_session(self):
        path = self._state_directory / "session.json"
        if getattr(self, "_private_mode", False) or self.preferences.get("privacy_lockdown", False):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        if self.preferences.get("restore_tabs", True):
            # Tab metadata contains navigated URLs, unlike unsubmitted omnibox text.
            snapshot = session_snapshot(self.tabs, self.active_tab_id)
            snapshot["clean_exit"] = True
            write_json(path, snapshot)
        else:
            path.unlink(missing_ok=True)

    def _store_bookmarks(self, updated, parent=None):
        try:
            write_json(self._state_directory / "bookmarks.json", updated)
        except OSError as exc:
            self._show_message("error", "Bookmarks", f"Could not save bookmarks:\n{exc}", parent=parent or self.root)
            return False
        self.bookmarks = updated
        self._refresh_standard_toolbar_state()
        return True

    def _toggle_current_bookmark(self):
        tab = self._active_tab() or {}
        url = str(tab.get("url") or "")
        if not valid_url(url):
            self.status_var.set("Open a webpage before bookmarking it")
            return "break"
        existing = next((i for i, item in enumerate(self.bookmarks) if item.get("url") == url), None)
        if existing is None:
            updated = self.bookmarks + [{"url": url, "title": tab.get("title") or url}]
            if self._store_bookmarks(updated):
                self.status_var.set("Bookmark saved")
        else:
            updated = [item for i, item in enumerate(self.bookmarks) if i != existing]
            if self._store_bookmarks(updated):
                self.status_var.set("Bookmark removed")
        return "break"

    def _bookmark_current_page(self):
        tab = self._active_tab() or {}
        url = tab.get("url", "")
        if not valid_url(url):
            self.status_var.set("Open a webpage before bookmarking it")
            return "break"
        if any(item["url"] == url for item in self.bookmarks):
            self.status_var.set("This page is already bookmarked — manage it in Bookmarks")
            return "break"
        if self._store_bookmarks(self.bookmarks + [{"url": url, "title": tab.get("title") or url}]):
            self.status_var.set("Bookmark saved")
        return "break"

    def _show_bookmarks(self):
        previous = getattr(self, "_bookmarks_window", None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return "break"
        win = self._new_animated_toplevel(self.root)
        self._bookmarks_window = win
        win.title("Tekzite Bookmarks")
        win.geometry("680x400")
        win.transient(self.root)
        win.configure(bg=self.ui["bg"])
        tree = ttk.Treeview(win, columns=("title", "url"), show="headings", selectmode="browse")
        tree.heading("title", text="Name")
        tree.heading("url", text="Address")
        tree.column("title", width=220)
        tree.column("url", width=400)
        scroll = ttk.Scrollbar(win, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        controls = tk.Frame(win, bg=self.ui["bg"])
        controls.pack(side="bottom", fill="x", padx=12, pady=12)
        scroll.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True, padx=12, pady=12)

        def refresh():
            tree.delete(*tree.get_children())
            for index, item in enumerate(self.bookmarks):
                tree.insert("", "end", iid=str(index), values=(item["title"], item["url"]))

        def selected():
            rows = tree.selection()
            return int(rows[0]) if rows else None

        def open_selected(event=None):
            index = selected()
            if index is not None:
                url = self.bookmarks[index]["url"]
                win.destroy()
                self._new_tab(url=url)

        def rename():
            index = selected()
            if index is None:
                return
            title = self._ask_string_animated("Rename bookmark", "Name:", initialvalue=self.bookmarks[index]["title"], parent=win)
            if title and title.strip():
                updated = [dict(item) for item in self.bookmarks]
                updated[index]["title"] = title.strip()
                if self._store_bookmarks(updated, win):
                    refresh()

        def remove():
            index = selected()
            if index is not None and self._store_bookmarks([item for i, item in enumerate(self.bookmarks) if i != index], win):
                refresh()

        for label, callback in (("Open in new tab", open_selected), ("Rename", rename), ("Remove", remove), ("Close", win.destroy)):
            tk.Button(controls, text=label, command=callback, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat").pack(side="left", padx=4)
        tree.bind("<Double-1>", open_selected)
        tree.bind("<Return>", open_selected)
        win.bind("<Escape>", lambda event: win.destroy())
        refresh()
        tree.focus_set()
        return "break"

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
        if self.preferences.get("quiet_mode", False) or not self._custom("animations", True):
            widget.configure(**{option: target})
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
        if self.preferences.get("quiet_mode", False) or not self._custom("animations", True):
            widget.configure(height=max(0, int(end)))
            if on_done:
                on_done()
            return
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

    def _motion_enabled(self):
        return bool(
            not self.preferences.get("quiet_mode", False)
            and self._custom("animations", True)
        )

    @staticmethod
    def _ease_out_cubic(t):
        t = max(0.0, min(1.0, float(t)))
        return 1.0 - (1.0 - t) ** 3

    def _dialog_display_title(self, win):
        """Return a clean in-window title for a Tekzite-owned dialog."""
        try:
            title = str(win.title() or "Tekzite")
        except Exception:
            title = "Tekzite"
        if title.startswith("Tekzite "):
            title = title[len("Tekzite "):]
        title = re.sub(r"\s*[—-]\s*v\d+(?:\.\d+){1,3}\s*$", "", title).strip()
        return title or "Tekzite"

    def _screen_center_geometry(self, win, width=None, height=None, margin=16):
        """Return a deterministic screen-centered geometry for an app dialog.

        Tekzite dialogs are frameless, so relying on Tk/Windows default placement
        can scatter otherwise identical windows around the desktop. Keep all
        app-owned dialogs in one coordinate space: measure in Tk pixels, clamp
        the requested size to the visible screen, then center that final box.
        """
        try:
            win.update_idletasks()
            screen_w = max(1, int(win.winfo_screenwidth()))
            screen_h = max(1, int(win.winfo_screenheight()))
            if width is None:
                width = max(1, int(win.winfo_width()), int(win.winfo_reqwidth()))
            if height is None:
                height = max(1, int(win.winfo_height()), int(win.winfo_reqheight()))
            width = min(max(1, int(width)), max(1, screen_w - int(margin) * 2))
            height = min(max(1, int(height)), max(1, screen_h - int(margin) * 2))
            x = max(int(margin), (screen_w - width) // 2)
            y = max(int(margin), (screen_h - height) // 2)
            return f"{width}x{height}+{x}+{y}"
        except Exception:
            width = max(1, int(width or 640))
            height = max(1, int(height or 420))
            return f"{width}x{height}"

    def _center_dialog_on_screen(self, win, width=None, height=None, margin=16):
        """Center a Tekzite-owned dialog using the shared Settings placement."""
        geometry = self._screen_center_geometry(win, width, height, margin)
        try:
            win.geometry(geometry)
            win._tekzite_screen_center_geometry = geometry
        except Exception:
            pass
        return geometry

    def _bind_frameless_dialog_drag(self, win, *handles):
        """Let Tekzite-owned frameless dialogs move from their in-window header.

        Native title bars are intentionally disabled for every app-owned Toplevel.
        Keep the familiar drag behavior by treating the branded header/logo/title
        area as the window's move handle instead. Buttons are not registered as
        handles, so clicking Close or another header control never starts a drag.
        """
        if win is None:
            return False

        def start_drag(event):
            try:
                win._tekzite_dialog_drag_anchor = (
                    int(event.x_root) - int(win.winfo_x()),
                    int(event.y_root) - int(win.winfo_y()),
                )
            except Exception:
                win._tekzite_dialog_drag_anchor = None

        def move_drag(event):
            anchor = getattr(win, "_tekzite_dialog_drag_anchor", None)
            if not anchor:
                return
            try:
                x = int(event.x_root) - int(anchor[0])
                y = int(event.y_root) - int(anchor[1])
                win.geometry(f"+{x}+{y}")
            except Exception:
                pass

        def end_drag(_event=None):
            win._tekzite_dialog_drag_anchor = None

        bound = False
        for widget in handles:
            if widget is None:
                continue
            try:
                widget.configure(cursor="fleur")
            except Exception:
                pass
            try:
                widget.bind("<ButtonPress-1>", start_drag, add="+")
                widget.bind("<B1-Motion>", move_drag, add="+")
                widget.bind("<ButtonRelease-1>", end_drag, add="+")
                bound = True
            except Exception:
                pass
        return bound

    def _apply_about_style_to_dialog(self, win):
        """Give every Tekzite-owned dialog the same visual shell as About.

        The dialog body remains owned by the individual feature, but the shared
        top area always uses Tekzite's logo tile, display title, version line,
        generous spacing and separator.  The header is inserted *before* the
        first packed child so existing feature windows do not need to be rebuilt.
        """
        try:
            if not win.winfo_exists() or getattr(win, "_tekzite_about_style_applied", False):
                return False
            win._tekzite_about_style_applied = True
            win.configure(bg=self.ui["bg"])

            shell = tk.Frame(win, bg=self.ui["bg"], padx=24, pady=18)
            header = tk.Frame(shell, bg=self.ui["bg"])
            header.pack(fill="x")

            logo = tk.Canvas(header, width=46, height=46, bg=self.ui["bg"],
                             highlightthickness=0, bd=0)
            logo.pack(side="left", padx=(0, 14))
            logo.create_rectangle(3, 3, 43, 43, fill=self.ui["accent"],
                                  outline=self.ui["accent_hover"], width=1)
            logo.create_text(23, 23, text="T", fill="#ffffff",
                             font=(self._ui_display_font_family, self._font_size(17), "bold"))

            title_col = tk.Frame(header, bg=self.ui["bg"])
            title_col.pack(side="left", fill="x", expand=True)
            title_label = tk.Label(title_col, text=self._dialog_display_title(win), bg=self.ui["bg"],
                                   fg=self.ui["text"],
                                   font=(self._ui_display_font_family, self._font_size(15), "bold"),
                                   anchor="w")
            title_label.pack(fill="x")
            version_label = tk.Label(title_col, text=f"v{BROWSER_VERSION}",
                                     bg=self.ui["bg"], fg=self.ui["accent_hover"],
                                     font=(self._ui_font_family, self._font_size(9)),
                                     anchor="w")
            version_label.pack(fill="x", pady=(2, 0))
            close_button = tk.Button(
                header, text="×", command=win.destroy,
                bg=self.ui["bg"], fg=self.ui["muted"],
                activebackground=self.ui["chrome_hover"], activeforeground=self.ui["text"],
                relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                font=(self._ui_display_font_family, self._font_size(14)),
                padx=9, pady=3,
            )
            close_button.pack(side="right", padx=(12, 0))
            win._tekzite_dialog_close_button = close_button
            self._bind_frameless_dialog_drag(
                win, shell, header, logo, title_col, title_label, version_label
            )

            tk.Frame(shell, bg=self.ui["border_soft"], height=1).pack(
                fill="x", pady=(15, 0)
            )

            slaves = [child for child in win.pack_slaves() if child is not shell]
            if slaves:
                shell.pack(fill="x", before=slaves[0])
            else:
                shell.pack(fill="x")
            win._tekzite_dialog_header = shell

            # Preserve the content space callers requested before the shared
            # header existed. Small confirmations in particular used to be
            # sized only for their body, so simply inserting a header would
            # squeeze their buttons/message. Grow the window by the header's
            # requested height when the monitor has room, never shrink it.
            try:
                win.update_idletasks()
                current_w = max(1, int(win.winfo_width()))
                current_h = max(1, int(win.winfo_height()))
                header_h = max(1, int(shell.winfo_reqheight()))
                screen_h = max(current_h, int(win.winfo_screenheight()))
                target_h = max(current_h, min(current_h + header_h, max(current_h, screen_h - 72)))
                if target_h > current_h:
                    x, y = int(win.winfo_x()), int(win.winfo_y())
                    win.geometry(f"{current_w}x{target_h}+{x}+{y}")
            except Exception:
                pass

            # Only Windows needs the DWM z-order repair. On Linux, delayed
            # focus_force() calls on override-redirect dialogs can fight the
            # desktop compositor/window manager after the user has moved on.
            # Keep every Linux desktop compositor-neutral.
            if os.name == "nt":
                try:
                    win.after(20, lambda w=win: self._raise_toplevel_above_dwm(w, hold_ms=360)
                              if w.winfo_exists() else None)
                except Exception:
                    pass
            else:
                try:
                    win.after(20, lambda w=win: w.winfo_exists() and w.lift())
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def _new_animated_toplevel(self, parent=None, *, duration=165, slide=14, branded=True, auto_animate=True):
        """Create an app-owned Toplevel with automatic open/close motion.

        The destroy method is wrapped immediately, before callers wire buttons,
        so Close/Escape actions across Settings, managers, inspectors and tools
        all receive the same fade/slide exit animation without per-dialog code.
        """
        win = tk.Toplevel(parent or self.root)
        # Keep Linux secondary windows managed for reliable compositor focus.
        # Motif hints remove decorations without bypassing the WM. Windows keeps
        # the existing override-redirect shell.
        try:
            if sys.platform.startswith("linux"):
                win.overrideredirect(False)
                win.after(1, lambda w=win: self._apply_linux_managed_frameless(w)
                          if w.winfo_exists() else None)
            else:
                win.overrideredirect(True)
        except Exception:
            pass
        original_destroy = win.destroy
        win._tekzite_original_destroy = original_destroy
        win._tekzite_motion_closing = False
        win._tekzite_motion_duration = int(duration)
        win._tekzite_motion_slide = int(slide)
        try:
            win.attributes("-alpha", 0.0 if self._motion_enabled() else 1.0)
        except Exception:
            pass

        def animated_destroy():
            if getattr(win, "_tekzite_motion_closing", False):
                return
            if not self._motion_enabled():
                try: original_destroy()
                except Exception: pass
                return
            self._animate_toplevel_out(win, original_destroy,
                                       duration=max(90, int(duration * 0.72)),
                                       slide=max(6, int(slide * 0.72)))
        win.destroy = animated_destroy
        try:
            win.protocol("WM_DELETE_WINDOW", animated_destroy)
        except Exception:
            pass
        win._tekzite_branded_dialog = bool(branded)
        win._tekzite_auto_animate = bool(auto_animate)
        def prepare_dialog(w=win):
            try:
                if not w.winfo_exists():
                    return
                if getattr(w, "_tekzite_branded_dialog", False):
                    self._apply_about_style_to_dialog(w)
                # v10.5.39: every ordinary Tekzite dialog is positioned by one
                # shared screen-center path after its final header/content size
                # is known, but before the opening animation captures geometry.
                # Settings opts out because it has a larger custom size; its
                # layout path calls the exact same centering helper explicitly.
                if getattr(w, "_tekzite_auto_animate", True):
                    self._center_dialog_on_screen(w)
                    self._animate_toplevel_in(w, duration=duration, slide=slide)
            except Exception:
                pass
        try:
            # Do not use after_idle here. Dialog builders commonly call
            # update_idletasks() while measuring their requested size; that also
            # drains idle callbacks and could start the animation before the
            # caller has assigned the final geometry. The timer runs after the
            # builder returns, applies the shared About-style shell, then animates.
            win.after(1, prepare_dialog)
        except Exception:
            pass
        return win

    def _animate_toplevel_in(self, win, duration=165, slide=14):
        """Fade and gently lift an app-owned window into place."""
        try:
            if not win.winfo_exists():
                return
            win.update_idletasks()
            final_x, final_y = int(win.winfo_x()), int(win.winfo_y())
            width, height = max(1, int(win.winfo_width())), max(1, int(win.winfo_height()))
        except Exception:
            return
        if not self._motion_enabled():
            try: win.attributes("-alpha", 1.0)
            except Exception: pass
            return
        token = time.monotonic_ns()
        win._tekzite_motion_token = token
        steps = max(7, min(15, int(duration // 12)))
        interval = max(8, int(duration) // steps)
        try:
            win.geometry(f"{width}x{height}+{final_x}+{final_y + int(slide)}")
            win.attributes("-alpha", 0.02)
        except Exception:
            pass

        def frame(i=1):
            try:
                if not win.winfo_exists() or getattr(win, "_tekzite_motion_token", None) != token:
                    return
                t = self._ease_out_cubic(i / float(steps))
                y = int(round(final_y + (1.0 - t) * int(slide)))
                win.geometry(f"{width}x{height}+{final_x}+{y}")
                win.attributes("-alpha", max(0.02, min(1.0, t)))
                if i < steps:
                    win.after(interval, lambda: frame(i + 1))
                else:
                    win.attributes("-alpha", 1.0)
                    win.geometry(f"{width}x{height}+{final_x}+{final_y}")
            except Exception:
                pass
        frame()

    def _animate_toplevel_out(self, win, on_done=None, duration=115, slide=10):
        """Fade/settle an app-owned window out, then destroy it safely."""
        try:
            if not win.winfo_exists():
                if on_done: on_done()
                return
            win._tekzite_motion_closing = True
            win.update_idletasks()
            x, y = int(win.winfo_x()), int(win.winfo_y())
            width, height = max(1, int(win.winfo_width())), max(1, int(win.winfo_height()))
            try: start_alpha = float(win.attributes("-alpha"))
            except Exception: start_alpha = 1.0
        except Exception:
            if on_done:
                try: on_done()
                except Exception: pass
            return
        if not self._motion_enabled():
            if on_done:
                try: on_done()
                except Exception: pass
            return
        token = time.monotonic_ns()
        win._tekzite_motion_token = token
        steps = max(6, min(12, int(duration // 11)))
        interval = max(8, int(duration) // steps)

        def finish():
            if on_done:
                try: on_done()
                except Exception: pass

        def frame(i=1):
            try:
                if not win.winfo_exists() or getattr(win, "_tekzite_motion_token", None) != token:
                    return
                t = self._ease_out_cubic(i / float(steps))
                alpha = max(0.0, start_alpha * (1.0 - t))
                yy = int(round(y + t * int(slide)))
                win.geometry(f"{width}x{height}+{x}+{yy}")
                win.attributes("-alpha", alpha)
                if i < steps:
                    win.after(interval, lambda: frame(i + 1))
                else:
                    finish()
            except Exception:
                finish()
        frame()

    def _animate_main_window_in(self, duration=190):
        if not getattr(self, "_startup_motion_enabled", False):
            try: self.root.attributes("-alpha", 1.0)
            except Exception: pass
            return
        steps = 13
        interval = max(9, int(duration) // steps)
        def frame(i=1):
            try:
                if not self.root.winfo_exists():
                    return
                t = self._ease_out_cubic(i / float(steps))
                self.root.attributes("-alpha", max(0.02, min(1.0, t)))
                if i < steps:
                    self.root.after(interval, lambda: frame(i + 1))
                else:
                    self.root.attributes("-alpha", 1.0)
            except Exception:
                pass
        frame()

    def _animate_notebook_page(self, notebook, duration=145):
        """Give Settings/Customize page changes a small horizontal settle."""
        if not self._motion_enabled():
            return
        try:
            selected = notebook.select()
            if not selected:
                return
            page = notebook.nametowidget(selected)
            base_padx = int(getattr(page, "_tekzite_base_padx", int(page.cget("padx") or 0)))
            page._tekzite_base_padx = base_padx
        except Exception:
            return
        steps = 8
        interval = max(9, int(duration) // steps)
        token = time.monotonic_ns()
        page._tekzite_page_motion_token = token
        def frame(i=1):
            try:
                if not page.winfo_exists() or getattr(page, "_tekzite_page_motion_token", None) != token:
                    return
                t = self._ease_out_cubic(i / float(steps))
                page.configure(padx=base_padx + int(round((1.0 - t) * 10)))
                if i < steps:
                    page.after(interval, lambda: frame(i + 1))
                else:
                    page.configure(padx=base_padx)
            except Exception:
                pass
        frame()

    def _show_message(self, kind, title, message, *, parent=None):
        """Animated Tekzite-owned replacement for app message boxes."""
        parent = parent or self.root
        win = self._new_animated_toplevel(parent, duration=150, slide=12)
        win.title(str(title or "Tekzite"))
        win.transient(parent)
        win.resizable(False, False)
        win.configure(bg=self.ui["bg"])
        result = {"value": "ok"}
        accent = {"info": self.ui["accent"], "warning": "#f3b85b", "error": self.ui["danger"]}.get(kind, self.ui["accent"])
        outer = tk.Frame(win, bg=self.ui["bg"], padx=24, pady=18)
        outer.pack(fill="both", expand=True)
        message_row = tk.Frame(outer, bg=self.ui["bg"]); message_row.pack(fill="x")
        badge = tk.Canvas(message_row, width=34, height=34, bg=self.ui["bg"], highlightthickness=0, bd=0)
        badge.pack(side="left", anchor="n", padx=(0, 12))
        badge.create_oval(2, 2, 32, 32, fill=self.ui["chrome_2"], outline=accent, width=2)
        badge.create_text(17, 17, text={"info":"i","warning":"!","error":"×"}.get(kind,"i"), fill=accent,
                          font=(self._ui_display_font_family, self._font_size(11), "bold"))
        tk.Label(message_row, text=str(message or ""), bg=self.ui["bg"], fg=self.ui["text"],
                 font=(self._ui_font_family, self._font_size(10)), justify="left", anchor="w",
                 wraplength=500).pack(side="left", fill="x", expand=True, pady=(3, 0))
        buttons = tk.Frame(outer, bg=self.ui["bg"]); buttons.pack(fill="x")
        ok = tk.Button(buttons, text="OK", command=win.destroy, bg=self.ui["accent"], fg="#ffffff",
                       activebackground=self.ui["accent_hover"], activeforeground="#ffffff",
                       relief="flat", bd=0, padx=22, pady=8, cursor="hand2")
        ok.pack(side="right")
        win.bind("<Return>", lambda _e: win.destroy())
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        width = max(390, min(600, int(outer.winfo_reqwidth()) + 12))
        height = max(180, int(outer.winfo_reqheight()) + 8)
        try:
            px, py = int(parent.winfo_rootx()), int(parent.winfo_rooty())
            pw, ph = int(parent.winfo_width()), int(parent.winfo_height())
            win.geometry(f"{width}x{height}+{px + max(0,(pw-width)//2)}+{py + max(0,(ph-height)//2)}")
        except Exception:
            win.geometry(f"{width}x{height}")
        try: win.grab_set()
        except Exception: pass
        ok.focus_set()
        win.wait_window()
        return result["value"]

    def _ask_yes_no(self, title, message, *, parent=None):
        parent = parent or self.root
        win = self._new_animated_toplevel(parent, duration=150, slide=12)
        win.title(str(title or "Tekzite")); win.transient(parent); win.resizable(False, False); win.configure(bg=self.ui["bg"])
        result = {"value": False}
        outer = tk.Frame(win, bg=self.ui["bg"], padx=22, pady=18); outer.pack(fill="both", expand=True)
        tk.Label(outer, text=str(message or ""), bg=self.ui["bg"], fg=self.ui["text"],
                 font=(self._ui_font_family, self._font_size(10)), justify="left", anchor="w", wraplength=520).pack(fill="x", pady=(2, 20))
        row = tk.Frame(outer, bg=self.ui["bg"]); row.pack(fill="x")
        def choose(value):
            result["value"] = bool(value); win.destroy()
        no = tk.Button(row, text="No", command=lambda: choose(False), bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", bd=0, padx=18, pady=8, cursor="hand2")
        yes = tk.Button(row, text="Yes", command=lambda: choose(True), bg=self.ui["accent"], fg="#ffffff", relief="flat", bd=0, padx=20, pady=8, cursor="hand2")
        yes.pack(side="right"); no.pack(side="right", padx=(0, 8))
        win.bind("<Escape>", lambda _e: choose(False)); win.bind("<Return>", lambda _e: choose(True))
        win.update_idletasks(); width=max(400,min(610,int(outer.winfo_reqwidth())+12)); height=max(180,int(outer.winfo_reqheight())+8)
        try:
            px,py=int(parent.winfo_rootx()),int(parent.winfo_rooty()); pw,ph=int(parent.winfo_width()),int(parent.winfo_height())
            win.geometry(f"{width}x{height}+{px+max(0,(pw-width)//2)}+{py+max(0,(ph-height)//2)}")
        except Exception: win.geometry(f"{width}x{height}")
        try: win.grab_set()
        except Exception: pass
        yes.focus_set(); win.wait_window(); return bool(result["value"])

    def _ask_string_animated(self, title, prompt, *, initialvalue="", parent=None):
        parent = parent or self.root
        win = self._new_animated_toplevel(parent, duration=150, slide=12)
        win.title(str(title or "Tekzite")); win.transient(parent); win.resizable(False, False); win.configure(bg=self.ui["bg"])
        result = {"value": None}; value = tk.StringVar(value=str(initialvalue or ""))
        outer=tk.Frame(win,bg=self.ui["bg"],padx=22,pady=18); outer.pack(fill="both",expand=True)
        tk.Label(outer,text=str(prompt or ""),bg=self.ui["bg"],fg=self.ui["muted"],font=(self._ui_font_family,self._font_size(10)),anchor="w").pack(fill="x",pady=(2,7))
        entry=tk.Entry(outer,textvariable=value,bg=self.ui["field"],fg=self.ui["text"],insertbackground=self.ui["text"],selectbackground=self.ui["accent"],selectforeground="#ffffff",relief="flat",bd=0,highlightthickness=1,highlightbackground=self.ui["border"],highlightcolor=self.ui["border_focus"],font=(self._ui_font_family,self._font_size(10)))
        entry.pack(fill="x",ipady=8)
        row=tk.Frame(outer,bg=self.ui["bg"]); row.pack(fill="x",pady=(18,0))
        def accept(): result["value"]=value.get(); win.destroy()
        tk.Button(row,text="Cancel",command=win.destroy,bg=self.ui["chrome_2"],fg=self.ui["text"],relief="flat",bd=0,padx=18,pady=8,cursor="hand2").pack(side="right")
        tk.Button(row,text="OK",command=accept,bg=self.ui["accent"],fg="#ffffff",relief="flat",bd=0,padx=20,pady=8,cursor="hand2").pack(side="right",padx=(0,8))
        win.bind("<Escape>",lambda _e: win.destroy()); win.bind("<Return>",lambda _e: accept())
        win.update_idletasks(); width=470; height=max(190,int(outer.winfo_reqheight())+8)
        try:
            px,py=int(parent.winfo_rootx()),int(parent.winfo_rooty()); pw,ph=int(parent.winfo_width()),int(parent.winfo_height())
            win.geometry(f"{width}x{height}+{px+max(0,(pw-width)//2)}+{py+max(0,(ph-height)//2)}")
        except Exception: win.geometry(f"{width}x{height}")
        try: win.grab_set()
        except Exception: pass
        entry.focus_set(); entry.selection_range(0,"end"); win.wait_window(); return result["value"]

    def _install_global_motion_bindings(self):
        """Animate ordinary Tk controls that are not custom Canvas widgets."""
        def button_enter(event):
            w = event.widget
            if not self._motion_enabled():
                return
            try:
                if str(w.cget("state")) == "disabled":
                    return
                if not hasattr(w, "_tekzite_motion_base_bg"):
                    w._tekzite_motion_base_bg = w.cget("bg")
                    w._tekzite_motion_base_relief = w.cget("relief")
                base = str(w._tekzite_motion_base_bg or "").lower()
                if base == str(self.ui.get("accent") or "").lower():
                    target = self.ui["accent_hover"]
                elif base == str(self.ui.get("danger") or "").lower():
                    target = self.ui["danger"]
                else:
                    target = self.ui["chrome_hover"]
                self._animate_widget_color(w, "bg", target, duration=95, steps=7)
            except Exception:
                pass

        def button_leave(event):
            w = event.widget
            try:
                base = getattr(w, "_tekzite_motion_base_bg", None)
                if base:
                    self._animate_widget_color(w, "bg", base, duration=125, steps=8)
                relief = getattr(w, "_tekzite_motion_base_relief", None)
                if relief is not None:
                    w.configure(relief=relief)
            except Exception:
                pass

        def button_press(event):
            w = event.widget
            if not self._motion_enabled():
                return
            try:
                if str(w.cget("state")) != "disabled":
                    if not hasattr(w, "_tekzite_motion_base_relief"):
                        w._tekzite_motion_base_relief = w.cget("relief")
                    w.configure(relief="sunken")
            except Exception:
                pass

        def button_release(event):
            w = event.widget
            try:
                relief = getattr(w, "_tekzite_motion_base_relief", "flat")
                w.configure(relief=relief)
            except Exception:
                pass

        def entry_focus(event, focused):
            w = event.widget
            if not self._motion_enabled():
                return
            # The omnibox has its own rounded-shell focus state plus an
            # unfocused Pillow preview. Animating the hidden Entry background
            # independently can leak a field_focus-colored band through the
            # preview during focus transitions, so leave this one to the
            # dedicated omnibox renderer.
            if w is getattr(self, "address", None):
                return
            try:
                if not hasattr(w, "_tekzite_motion_base_bg"):
                    w._tekzite_motion_base_bg = w.cget("bg")
                target = self.ui.get("field_focus") if focused else w._tekzite_motion_base_bg
                self._animate_widget_color(w, "bg", target, duration=110 if focused else 145, steps=8)
            except Exception:
                pass

        try:
            self.root.bind_class("Button", "<Enter>", button_enter, add="+")
            self.root.bind_class("Button", "<Leave>", button_leave, add="+")
            self.root.bind_class("Button", "<ButtonPress-1>", button_press, add="+")
            self.root.bind_class("Button", "<ButtonRelease-1>", button_release, add="+")
            self.root.bind_class("Entry", "<FocusIn>", lambda e: entry_focus(e, True), add="+")
            self.root.bind_class("Entry", "<FocusOut>", lambda e: entry_focus(e, False), add="+")
        except Exception:
            pass

    def _animate_loading_icon(self, label, tab_id, frame_index=0):
        if self.preferences.get("quiet_mode", False) or not self._custom("animations", True):
            return
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

    def _redraw_address_shell(self):
        """Paint the omnibox as one rounded modern surface."""
        canvas = getattr(self, "address_backdrop", None)
        if canvas is None:
            return
        try:
            canvas.delete("all")
            w = max(12, int(self.address_shell.winfo_width()))
            h = max(12, int(self.address_shell.winfo_height()))
            fill = self.ui["field_focus"] if self._address_focused else self.ui["field"]
            outline = self.ui["border_focus"] if self._address_focused else self.ui["border"]
            radius = min(self._ui_metric("control_corner_radius", 16), max(6, h // 2))
            self._rounded_canvas_rect(canvas, 1, 1, w - 1, h - 1, radius,
                                      fill=fill, outline=outline, width=1.25)
            self.address_inner.configure(bg=fill)
            self.address_text_host.configure(bg=fill)
            self.address.configure(bg=fill)
            self.address_preview.configure(bg=fill)
            self.site_info_button.configure(bg=fill, activebackground=fill)
            self.bookmark_button.configure(bg=fill, activebackground=fill)
            self._schedule_address_preview_render()
        except Exception:
            pass

    def _on_omnibox_text_changed(self, *_args):
        self._schedule_address_preview_render()
        if getattr(self, "_omnibox_update_suspended", False):
            return
        if getattr(self, "_address_focus_active", False):
            self._schedule_omnibox_suggestions()

    def _schedule_omnibox_suggestions(self, delay_ms=28):
        if not self.preferences.get("omnibox_suggestions_enabled", True):
            self._hide_omnibox_suggestions()
            return
        try:
            if self._omnibox_suggestion_after_id is not None:
                self.root.after_cancel(self._omnibox_suggestion_after_id)
        except Exception:
            pass
        try:
            self._omnibox_suggestion_after_id = self.root.after(
                max(0, int(delay_ms)), self._refresh_omnibox_suggestions
            )
        except Exception:
            self._omnibox_suggestion_after_id = None

    def _refresh_omnibox_suggestions(self):
        self._omnibox_suggestion_after_id = None
        try:
            if (not self.preferences.get("omnibox_suggestions_enabled", True)
                    or not self._address_focus_active
                    or self.root.focus_get() is not self.address):
                self._hide_omnibox_suggestions()
                return False
        except Exception:
            if not self._address_focus_active:
                self._hide_omnibox_suggestions()
                return False
        query = str(self.url_var.get() or "").strip()
        items = omnibox_suggestions(
            query,
            visits=getattr(self, "visits", []),
            bookmarks=getattr(self, "bookmarks", []),
            tabs=getattr(self, "tabs", []),
            recent_inputs=getattr(self, "_omnibox_recent_inputs", []),
            limit=6,
        )
        self._omnibox_suggestions = items
        if not items:
            self._hide_omnibox_suggestions()
            return False
        current_value = None
        if 0 <= self._omnibox_suggestion_index < len(items):
            current_value = items[self._omnibox_suggestion_index].get("value")
        if current_value:
            self._omnibox_suggestion_index = next(
                (i for i, item in enumerate(items) if item.get("value") == current_value), -1
            )
        else:
            self._omnibox_suggestion_index = -1
        popup = self._omnibox_suggestion_popup
        if popup is None:
            popup = _OmniboxSuggestionPopup(self)
            self._omnibox_suggestion_popup = popup
        return bool(popup.show(items, self._omnibox_suggestion_index))

    def _hide_omnibox_suggestions(self, return_break=False):
        try:
            if self._omnibox_suggestion_after_id is not None:
                self.root.after_cancel(self._omnibox_suggestion_after_id)
        except Exception:
            pass
        self._omnibox_suggestion_after_id = None
        popup = getattr(self, "_omnibox_suggestion_popup", None)
        if popup is not None:
            popup.hide()
        self._omnibox_suggestions = []
        self._omnibox_suggestion_index = -1
        return "break" if return_break else None

    def _hide_omnibox_suggestions_if_inactive(self):
        if getattr(self, "_omnibox_popup_pointer_down", False):
            try:
                self.root.after(80, self._hide_omnibox_suggestions_if_inactive)
            except Exception:
                pass
            return
        try:
            if self.root.focus_get() is self.address:
                return
        except Exception:
            pass
        self._hide_omnibox_suggestions()

    def _move_omnibox_suggestion(self, direction):
        if not self.preferences.get("omnibox_suggestions_enabled", True):
            return None
        if not self._omnibox_suggestions:
            self._refresh_omnibox_suggestions()
        items = self._omnibox_suggestions
        if not items:
            return "break"
        direction = 1 if int(direction) >= 0 else -1
        current = int(self._omnibox_suggestion_index)
        if current < 0:
            current = -1 if direction > 0 else 0
        current = (current + direction) % len(items)
        self._omnibox_suggestion_index = current
        popup = getattr(self, "_omnibox_suggestion_popup", None)
        if popup is not None:
            popup.set_selected(current)
        return "break"

    def _remember_omnibox_input(self, value):
        value = str(value or "").strip()[:32768]
        if not value:
            return
        rows = [row for row in getattr(self, "_omnibox_recent_inputs", []) if str(row).casefold() != value.casefold()]
        self._omnibox_recent_inputs = [value] + rows[:99]

    def _activate_omnibox_suggestion(self, index, *, navigate=False):
        try:
            item = self._omnibox_suggestions[int(index)]
        except Exception:
            return "break"
        value = str(item.get("value") or "").strip()
        if not value:
            return "break"
        self._omnibox_update_suspended = True
        try:
            self.url_var.set(value)
            self.address.icursor(tk.END)
            self.address.selection_clear()
        finally:
            self._omnibox_update_suspended = False
        self._omnibox_suggestion_index = int(index)
        self._hide_omnibox_suggestions()
        if navigate:
            self._remember_omnibox_input(value)
            self._release_address_focus_for_navigation()
            self.navigate_to(value, add_history=True)
        else:
            try:
                self.address.focus_set()
            except Exception:
                pass
        return "break"

    def _accept_omnibox_suggestion(self, event=None):
        if not self._omnibox_suggestions:
            return None
        index = self._omnibox_suggestion_index
        if index < 0:
            index = 0
        return self._activate_omnibox_suggestion(index, navigate=False)

    def _on_omnibox_return(self, event=None):
        if self._omnibox_suggestions and self._omnibox_suggestion_index >= 0:
            return self._activate_omnibox_suggestion(self._omnibox_suggestion_index, navigate=True)
        self._hide_omnibox_suggestions()
        self.navigate()
        return "break"

    def _set_address_shell_focus(self, focused):
        self._address_focused = bool(focused)
        self._redraw_address_shell()
        if focused:
            self._set_address_preview_visible(False)
        else:
            self._schedule_address_preview_render()
            try:
                self.root.after_idle(lambda: self._set_address_preview_visible(
                    not bool(self.root.focus_get() is self.address)
                ))
            except Exception:
                self._set_address_preview_visible(True)

    def _set_address_preview_visible(self, visible):
        preview = getattr(self, "address_preview", None)
        if preview is None:
            return
        try:
            if visible:
                self._render_address_preview()
                preview.lift()
            else:
                self.address.lift()
        except Exception:
            pass

    def _schedule_address_preview_render(self):
        if not hasattr(self, "address_preview"):
            return
        try:
            if self._address_preview_after_id is not None:
                self.root.after_cancel(self._address_preview_after_id)
        except Exception:
            pass
        try:
            self._address_preview_after_id = self.root.after_idle(self._render_address_preview)
        except Exception:
            self._address_preview_after_id = None

    def _address_preview_font(self, pixel_size):
        """Return a Windows Segoe font for grayscale FreeType rendering."""
        candidates = []
        if os.name == "nt":
            windir = Path(os.environ.get("WINDIR") or r"C:\Windows")
            candidates.extend([
                windir / "Fonts" / "segoeui.ttf",
                windir / "Fonts" / "segoeuivariable.ttf",
            ])
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return ImageFont.truetype(str(candidate), max(8, int(pixel_size)))
            except Exception:
                pass
        try:
            return ImageFont.truetype("DejaVuSans.ttf", max(8, int(pixel_size)))
        except Exception:
            return ImageFont.load_default()

    def _render_address_preview(self):
        self._address_preview_after_id = None
        preview = getattr(self, "address_preview", None)
        host = getattr(self, "address_text_host", None)
        if preview is None or host is None:
            return False
        try:
            w = max(1, int(host.winfo_width()))
            h = max(1, int(host.winfo_height()))
            if w < 4 or h < 4:
                return False
            # The preview is visible only while the real Entry is not being
            # edited. Match the canvas' *actual* current background rather than
            # relying on focus state that can briefly lag during focus animation.
            fill = str(preview.cget("bg") or self.ui["field"])
            try:
                scaling = float(self.root.tk.call("tk", "scaling"))
            except Exception:
                scaling = 1.333333333
            # v10.5.20: render the resting URL at a higher internal resolution
            # and downsample it back into the omnibox. The previous 1x Pillow
            # path could look jagged or uneven again after the broader GUI
            # animation/styling changes, especially on Windows DPI scaling.
            oversample = max(2, int(round(max(1.0, scaling))))
            image = Image.new("RGB", (w * oversample, h * oversample), fill)
            draw = ImageDraw.Draw(image)
            point_size = max(10, int(self._custom("font_size", 10)) + 1)
            font = self._address_preview_font(round(point_size * max(1.0, scaling) * oversample))
            value = str(self.url_var.get() or "")
            # Draw once, clipped by the image, so extremely long URLs cannot
            # force a huge off-screen bitmap or expensive measurement loop.
            bbox = draw.textbbox((0, 0), value, font=font)
            text_h = max(1, int(bbox[3] - bbox[1]))
            y = max(0, int((h * oversample - text_h) / 2 - bbox[1]))
            draw.text((0, y), value, font=font, fill=self.ui["text"])
            if oversample > 1:
                image = image.resize((w, h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self._address_preview_photo = photo
            preview.delete("all")
            preview.create_image(0, 0, image=photo, anchor="nw")
            return True
        except Exception:
            return False

    def _activate_address_preview(self, event=None):
        self._on_address_pointer_down(event)
        self._set_address_preview_visible(False)
        try:
            # Keep the normal Tk focus path for existing behavior/tests, then
            # add the stronger Linux native-focus reclamation underneath it.
            self.address.focus_set()
            self.address.focus_force()
            if sys.platform.startswith("linux"):
                try:
                    self.root.tk.call("focus", "-force", self.address._w)
                except Exception:
                    pass
            self.address.icursor(f"@{max(0, int(getattr(event, 'x', 0)))}")
        except Exception:
            pass
        return "break"

    def _show_address_preview_context_menu(self, event):
        self._activate_address_preview(event)
        return self._show_address_context_menu(event)

    def _rounded_canvas_rect(self, canvas, x1, y1, x2, y2, radius, **kwargs):
        radius = max(2, min(int(radius), int((x2 - x1) / 2), int((y2 - y1) / 2)))
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _tab_open_width(self, tab_id, target_width):
        """Return the current width for an opening-tab expansion animation."""
        target_width = max(1, int(target_width))
        started = self._tab_open_animation_started.get(tab_id)
        if started is None or not self._motion_enabled():
            return target_width, True
        duration = max(0.08, float(self._tab_open_animation_duration))
        elapsed = max(0.0, time.monotonic() - float(started))
        t = min(1.0, elapsed / duration)
        eased = self._ease_out_cubic(t)
        start_width = min(target_width, max(28, self._ui_padding(34)))
        width = int(round(start_width + (target_width - start_width) * eased))
        return max(1, width), t >= 1.0

    def _animate_opening_tab_widget(self, tab_id, widget, target_width, redraw=None):
        """Expand a newly-created tab and naturally slide the inline + button."""
        if tab_id not in self._tab_open_animation_started:
            return False
        if not self._motion_enabled():
            self._tab_open_animation_started.pop(tab_id, None)
            try:
                widget.configure(width=max(1, int(target_width)))
                if redraw:
                    redraw()
            except Exception:
                pass
            return False

        def frame():
            try:
                if not widget.winfo_exists():
                    return
            except Exception:
                return
            width, done = self._tab_open_width(tab_id, target_width)
            try:
                widget.configure(width=width)
                if redraw:
                    redraw()
            except Exception:
                return
            if done:
                self._tab_open_animation_started.pop(tab_id, None)
                try:
                    widget.configure(width=max(1, int(target_width)))
                    if redraw:
                        redraw()
                except Exception:
                    pass
                return
            try:
                self.root.after(12, frame)
            except Exception:
                pass

        try:
            self.root.after_idle(frame)
        except Exception:
            frame()
        return True

    def _draw_soft_tab(self, canvas, tab, active, hovered=False):
        try:
            canvas.delete("all")
            width = max(40, int(canvas.cget("width")))
            height = max(28, int(canvas.cget("height")))
            fill = self.ui["field"] if active else (self.ui["field_focus"] if hovered else self.ui["chrome"])
            outline = self.ui["border_focus"] if active else (self.ui["border"] if hovered else self.ui["border_soft"])
            tab_radius = min(self._ui_metric("control_corner_radius", 16), max(8, int(height * 0.48)))
            self._rounded_canvas_rect(canvas, 1, 1, width - 1, height - 1, tab_radius, fill=fill, outline=outline, width=1.2)
            if active and self._custom("show_tab_active_indicator", True):
                pill_w = max(24, min(64, int(width * 0.30)))
                x1 = int((width - pill_w) / 2)
                self._rounded_canvas_rect(canvas, x1, height - 5, x1 + pill_w, height - 2, 2, fill=self.ui["accent"], outline=self.ui["accent"])
            icon_x = 16 if tab.get("pinned") else 18
            icon_photo = tab.get("favicon_photo") if self._custom("show_tab_favicons", True) else None
            if icon_photo:
                canvas.create_image(icon_x, height / 2, image=icon_photo, anchor="center")
            else:
                glyph = "☾" if tab.get("sleeping") else ("◌" if tab.get("loading") else "◇")
                canvas.create_text(icon_x, height / 2, text=glyph, fill=self.ui["accent_hover"] if tab.get("loading") else self.ui["muted_dim"], font=(self._ui_font_family, max(7, int(self._custom("tab_font_size", 9)))))
            title = str(tab.get("title") or "New Tab")
            title_chars = max(6, int(self._custom("tab_title_chars", 28)))
            if tab.get("pinned"):
                title = ""
            else:
                title = title[:title_chars]
            close_visible = (not tab.get("pinned")) and self._custom("show_tab_close_buttons", True)
            close_space = 28 if close_visible else 10
            canvas.create_text(icon_x + 15, height / 2, text=title, anchor="w", fill=self.ui["text"] if active or hovered else self.ui["muted"], font=(self._ui_font_family, max(7, int(self._custom("tab_font_size", 9)))))
            if close_visible:
                close_x = width - 16
                close_fill = self.ui["text"] if hovered else self.ui["muted_dim"]
                canvas.create_text(close_x, height / 2, text="×", fill=close_fill, font=(self._ui_font_family, max(9, int(self._custom("tab_font_size", 9)) + 2)), tags=("close",))
            canvas._tekzite_close_visible = close_visible
            canvas._tekzite_close_x = width - close_space
        except Exception:
            pass

    def _tab_pixel_width(self, title, pinned=False):
        """Return the shared tab width for soft and classic tab styles."""
        scale = max(0.75, float(self._custom("ui_scale", 1.0)))
        if pinned:
            return max(44, int(48 * scale))
        title = str(title or "New Tab")
        title_chars = min(len(title), max(6, int(self._custom("tab_title_chars", 28))))
        min_width = max(90, int(self._custom("tab_min_width", 175)))
        max_width = max(min_width, int(self._custom("tab_max_width", 330)))
        natural = int(78 + title_chars * 8.2)
        return max(int(min_width * scale), min(int(max_width * scale), int(natural * scale)))

    def _create_soft_tab(self, tab, active):
        title = str(tab.get("title") or "New Tab")
        width = self._tab_pixel_width(title, pinned=bool(tab.get("pinned")))
        initial_width, _opening_done = self._tab_open_width(tab.get("id"), width)
        height = max(30, self._ui_metric("tab_bar_height", 52) - self._ui_padding(12))
        canvas = tk.Canvas(self.tab_items, width=initial_width, height=height, bg=self.ui["chrome"], highlightthickness=0, bd=0, cursor="hand2")
        canvas.pack(side="left", padx=(0, self._ui_padding(5)), pady=(self._ui_padding(1), self._ui_padding(1)))
        self._draw_soft_tab(canvas, tab, active, hovered=False)

        def redraw(hovered=False, c=canvas, t=tab, a=active):
            self._draw_soft_tab(c, t, a, hovered=hovered)

        canvas.bind("<Enter>", lambda event: redraw(True))
        canvas.bind("<Leave>", lambda event: redraw(False))
        def left_click(event, tid=tab["id"], c=canvas):
            if getattr(c, "_tekzite_close_visible", False) and event.x >= getattr(c, "_tekzite_close_x", 10**9):
                self._close_tab(tid)
            else:
                self._switch_tab(tid)
        canvas.bind("<ButtonRelease-1>", left_click)
        canvas.bind("<ButtonRelease-2>", lambda event=None, tid=tab["id"]: self._close_tab(tid))
        canvas.bind("<Button-3>", lambda event=None, tid=tab["id"]: self._show_tab_context_menu(event, tid))
        self._animate_opening_tab_widget(tab.get("id"), canvas, width, redraw=lambda: redraw(False))
        return canvas

    def _place_new_tab_button_inline(self):
        """Place + immediately beside the visible tab run."""
        button = getattr(self, "new_tab_button", None)
        items = getattr(self, "tab_items", None)
        if button is None or items is None:
            return
        try:
            button.pack_forget()
            if not self._custom("show_new_tab_button", True):
                return
            siblings = [child for child in items.winfo_children() if child is not button]
            opts = {
                "side": "left",
                "fill": "y",
                "pady": (self._ui_padding(1), self._ui_padding(1)),
            }
            if self._custom("new_tab_button_position", "right") == "left":
                opts["padx"] = (0, self._ui_padding(5))
                if siblings:
                    opts["before"] = siblings[0]
            else:
                opts["padx"] = (self._ui_padding(1), 0)
                if siblings:
                    opts["after"] = siblings[-1]
            button.pack(**opts)
        except Exception:
            pass

    def _refresh_tab_strip(self):
        if self.tab_items is None:
            return
        # Preserve the inline + button while rebuilding dynamic tab widgets.
        try:
            self.new_tab_button.pack_forget()
        except Exception:
            pass
        for child in self.tab_items.winfo_children():
            if child is not getattr(self, "new_tab_button", None):
                child.destroy()

        groups = self._normalized_tab_groups()
        group_rows = groups.items() if self._custom("show_tab_group_chips", True) else ()
        for group_name, meta in group_rows:
            count = sum(1 for tab in self.tabs if tab.get("group") == group_name)
            if not count:
                continue
            chip = tk.Button(
                self.tab_items, text=("▸ " if meta.get("collapsed") else "▾ ") + f"{group_name} ({count})",
                command=lambda g=group_name: self._toggle_tab_group(g),
                bg=self.ui["field"], fg=meta.get("color", self.ui["accent"]),
                activebackground=self.ui["field_focus"], activeforeground=self.ui["text"],
                relief="flat", bd=0, highlightthickness=1, highlightbackground=self.ui["border_soft"], font=(self._ui_font_family, max(7, int(self._custom("tab_font_size", 9)) - 1), "bold"), padx=self._ui_padding(8), pady=self._ui_padding(3), cursor="hand2",
            )
            chip.pack(side="left", padx=(0, 3), fill="y")

        for tab in self.tabs:
            group_name = str(tab.get("group") or "")
            group_meta = groups.get(group_name, {})
            if group_name and group_meta.get("collapsed") and tab.get("id") != self.active_tab_id:
                continue
            active = tab.get("id") == self.active_tab_id
            if self._custom("tab_style", "soft") == "soft":
                self._create_soft_tab(tab, active)
                continue
            normal_bg = self.ui["field"] if active else self.ui["chrome"]
            hover_bg = self.ui["field_focus"]
            normal_fg = self.ui["text"] if active else self.ui["muted"]
            normal_border = self.ui["border"] if active else self.ui["border_soft"]

            target_tab_width = self._tab_pixel_width(str(tab.get("title") or "New Tab"), pinned=bool(tab.get("pinned")))
            initial_tab_width, _opening_done = self._tab_open_width(tab.get("id"), target_tab_width)
            frame = tk.Frame(
                self.tab_items,
                bg=normal_bg,
                highlightthickness=1,
                highlightbackground=normal_border,
                width=initial_tab_width,
            )
            frame.pack(side="left", padx=(0, 5), pady=(self._ui_padding(2), self._ui_padding(2)), fill="y")
            frame.pack_propagate(False)

            body = tk.Frame(frame, bg=normal_bg)
            body.pack(side="top", fill="both", expand=True, padx=self._ui_padding(2))

            # v8.0: favicon/loading glyph and live page title. Keep the icon in
            # its own label so the title remains compact as tabs get narrower.
            icon_photo = tab.get("favicon_photo") if self._custom("show_tab_favicons", True) else None
            icon = tk.Label(
                body,
                image=icon_photo if icon_photo else "",
                text="" if icon_photo else ("☾" if tab.get("sleeping") else ("◌" if tab.get("loading") else "◇")),
                compound="left", bg=normal_bg, fg=self.ui["accent_hover"] if tab.get("loading") else self.ui["muted_dim"],
                font=(self._ui_font_family, max(7, int(self._custom("tab_font_size", 9)))), padx=self._ui_padding(8), pady=self._ui_padding(5), cursor="hand2",
            )
            icon.pack(side="left")
            title = str(tab.get("title") or "New Tab")
            title_chars = max(6, int(self._custom("tab_title_chars", 28)))
            label = tk.Label(
                body,
                text=(title[:1] if tab.get("pinned") else title[:title_chars]),
                bg=normal_bg,
                fg=normal_fg,
                font=(self._ui_font_family, max(7, int(self._custom("tab_font_size", 9)))),
                padx=(self._ui_padding(2) if icon_photo else 0),
                pady=self._ui_padding(5),
                cursor="hand2",
            )
            label.pack(side="left")
            for click_widget in (frame, body, icon, label):
                click_widget.bind("<Button-1>", lambda event=None, tid=tab["id"]: self._switch_tab(tid))
                click_widget.bind("<Button-2>", lambda event=None, tid=tab["id"]: self._close_tab(tid))
                click_widget.bind("<Button-3>", lambda event=None, tid=tab["id"]: self._show_tab_context_menu(event, tid))

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
                font=(self._ui_font_family, max(7, int(self._custom("tab_font_size", 9)))),
                cursor="hand2",
                padx=self._ui_padding(5),
                pady=0,
            )
            if not tab.get("pinned") and self._custom("show_tab_close_buttons", True):
                close.pack(side="right", fill="y")

            indicator = tk.Frame(frame, bg=self.ui["accent"] if active else normal_bg, height=max(1, self._ui_padding(2)))
            if self._custom("show_tab_active_indicator", True):
                indicator.pack(side="bottom", fill="x")

            def set_hover(_event=None, *, inside=True, fr=frame, bd=body, ic=icon, lb=label, cl=close, ind=indicator,
                          is_active=active, base=normal_bg, base_fg=normal_fg, base_border=normal_border):
                bg = hover_bg if inside and not is_active else base
                border = self.ui["border_focus"] if (inside and is_active) else (self.ui["border"] if inside else base_border)
                for w in (fr, bd, ic, lb, cl):
                    self._animate_widget_color(w, "bg", bg, 105 if inside else 145)
                self._animate_widget_color(fr, "highlightbackground", border, 105 if inside else 145)
                self._animate_widget_color(lb, "fg", self.ui["text"] if inside else base_fg, 105 if inside else 145)
                self._animate_widget_color(cl, "fg", self.ui["muted"] if inside else self.ui["muted_dim"], 105 if inside else 145)
                if not is_active:
                    self._animate_widget_color(ind, "bg", bg, 105 if inside else 145)

            for widget in (frame, body, icon, label):
                widget.bind("<Enter>", lambda e=None, fn=set_hover: fn(inside=True))
                widget.bind("<Leave>", lambda e=None, fn=set_hover: fn(inside=False))
            close.bind("<Enter>", lambda e=None, c=close: (
                self._animate_widget_color(c, "bg", self.ui["danger"], 90),
                self._animate_widget_color(c, "fg", "#ffffff", 90),
            ))
            close.bind("<Leave>", lambda e=None, fn=set_hover: fn(inside=False))

            if active:
                # Give the newly-active tab a short accent settle rather than a hard flash.
                try:
                    indicator.configure(bg=self.ui["chrome_hover"])
                    self._animate_widget_color(indicator, "bg", self.ui["accent"], 150)
                except Exception:
                    pass
            if tab.get("loading") and not icon_photo:
                self._animate_loading_icon(icon, tab.get("id"), 0)
            self._animate_opening_tab_widget(tab.get("id"), frame, target_tab_width)

        self._place_new_tab_button_inline()

    def _decode_favicon_photo(self, data_b64):
        """Decode a site favicon under strict size/format limits.

        Favicons are website-controlled input. Limit both compressed bytes and
        decoded dimensions before pixel conversion so a tiny compressed image
        cannot turn into a large memory allocation in the Tekzite UI process.
        """
        try:
            raw = base64.b64decode(str(data_b64 or ""), validate=False)
            if not raw or len(raw) > 524288:
                return None
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as opened:
                    fmt = str(opened.format or "").upper()
                    if fmt not in {"PNG", "ICO", "JPEG", "GIF", "WEBP"}:
                        return None
                    width, height = map(int, opened.size)
                    if (
                        width <= 0 or height <= 0
                        or width > 2048 or height > 2048
                        or width * height > 4_194_304
                    ):
                        return None
                    opened.seek(0)
                    opened.load()
                    image = opened.convert("RGBA")
            image.thumbnail((16, 16), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            x = (16 - image.width) // 2
            y = (16 - image.height) // 2
            canvas.alpha_composite(image, (x, y))
            return ImageTk.PhotoImage(canvas)
        except Exception:
            return None

    @staticmethod
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

    def _suspend_chromium_for_external_auth(self):
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
        self._dwm_pending_force_resize = False
        self._dwm_pending_input_metrics_refresh = False
        self._chromium_frame_target_id = None
        self._chromium_pending_motion = None
        self._chromium_pending_wheel = None
        self._chromium_pending_drag = None
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        return True

    def _launch_google_auth_worker(self, launch_url, return_url):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        try:
            self._google_auth_launch_future = self._executor.submit(
                start_standalone_auth_chromium, launch_url, return_url
            )
        except Exception as exc:
            self._google_auth_handoff_active = False
            self.status_var.set(f"Could not open Google sign-in window: {exc}")
            return
        self.root.after(40, self._poll_google_auth_launch)

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
        self._suspend_chromium_for_external_auth()

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

        self._paint_google_auth_handoff()
        self.status_var.set("Google sign-in: complete authentication in Chromium; Tekzite will close it automatically")
        self._refresh_tab_strip()

        # Let Tk finish destroying/hiding every native DWM surface before the
        # worker closes Chromium. This avoids a source-HWND teardown racing
        # callbacks still running on the UI thread.
        try:
            self.root.after(90, self._launch_google_auth_worker, launch_url, return_url)
        except Exception:
            self._launch_google_auth_worker(launch_url, return_url)
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
        self.status_var.set("Google sign-in window is open; Tekzite will close it when authentication finishes")
        # v10.5.69: the live HWND completion signal is cheap and authoritative.
        # Poll it quickly so a visibly completed YouTube sign-in does not linger
        # for the old 220 ms cadence. Slow cookie/history fallbacks still run in
        # the executor and retain their own settle guard.
        self.root.after(70, self._poll_google_auth_window)

    def _poll_google_auth_window(self):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        handle = getattr(self, "_google_auth_handle", None) or {}
        try:
            running = bool(standalone_auth_chromium_running(handle))
        except Exception:
            running = False

        if running:
            # Detect the live returned auth HWND off the Tk thread first; the
            # cookie/history profile checks are slower fallbacks. A confirmed
            # live YouTube return closes immediately, while disk-only signals
            # keep their conservative settle guard.
            close_future = getattr(self, "_google_auth_close_future", None)
            if close_future is not None and close_future.done():
                self._google_auth_close_future = None
                close_future = None

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
                            # The first close is already a synchronous, cooperative
                            # SC_CLOSE/WM_CLOSE against the exact auth HWND. This is
                            # still a clean Chromium shutdown, but avoids leaving a
                            # fully authenticated YouTube window sitting on screen.
                            self._google_auth_close_future = self._executor.submit(
                                close_standalone_auth_chromium, handle, True
                            )
                        except Exception:
                            self._google_auth_close_future = None
            else:
                # A posted WM_CLOSE can occasionally be swallowed while Chromium
                # is finishing account UI work. Retry it and then escalate only
                # to a synchronous SC_CLOSE/WM_CLOSE request. Never taskkill the
                # auth browser: that dirties Chromium's shared profile and makes
                # it show the restore-pages crash bubble on the next launch.
                requested_at = float(handle.get("auto_close_requested_at") or time.monotonic())
                elapsed = max(0.0, time.monotonic() - requested_at)
                if close_future is None and elapsed >= 1.6:
                    cooperative_escalation = elapsed >= 3.8
                    self.status_var.set(
                        "Finishing Google sign-in…" if not cooperative_escalation
                        else "Google sign-in complete; closing Chromium cleanly…"
                    )
                    try:
                        self._google_auth_close_future = self._executor.submit(
                            close_standalone_auth_chromium, handle, cooperative_escalation
                        )
                    except Exception:
                        self._google_auth_close_future = None
            self.root.after(70, self._poll_google_auth_window)
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

    def _finish_google_auth_handoff(self, browser_closed=True):
        if not getattr(self, "_google_auth_handoff_active", False):
            return
        self._google_auth_handoff_active = False
        self._google_auth_handle = None
        self._google_auth_launch_future = None
        self._google_auth_release_future = None
        self._google_auth_success_future = None
        self._google_auth_close_future = None
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
            self._google_auth_refresh_pending_url = return_url
            self.url_var.set(return_url)
            self._refresh_tab_strip()
            self.status_var.set("Returning from Google sign-in…")
            self.navigate_to(return_url, add_history=False, reuse_existing=False)
        else:
            self._google_auth_refresh_pending_url = None
            self.status_var.set("Google sign-in window closed")

    def _refresh_after_google_auth(self, generation, target_id, expected_url):
        """Reload the returned page once after Chromium has reopened the profile."""
        if generation != self._navigation_generation:
            return
        tab = self._active_tab()
        if tab is None or tab.get("chromium_target_id") != target_id:
            return
        if self._canonical_tab_url(tab.get("url")) != self._canonical_tab_url(expected_url):
            return
        self.status_var.set("Applying Google sign-in session…")
        self.navigate_to(expected_url, add_history=False, reuse_existing=False)

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
                previous_url = str(tab.get("url") or "")
                if self._maybe_start_google_auth_handoff(live_url, previous_url, tab):
                    return
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
            audible = bool(info.get("audible", False))
            if audible != bool(tab.get("audible", False)):
                tab["audible"] = audible
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
            self._record_page_visit(tab)
            if tab.get("id") == self.active_tab_id:
                self._refresh_standard_toolbar_state()
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
            tab["pinned"] = bool(snap.get("pinned"))
            tab["group"] = str(snap.get("group") or "")
            self.tabs.sort(key=lambda t: not t.get("pinned", False))
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
            self._find_bar_visible = True
            self._repack_browser_chrome()
            self._animate_widget_height(self.find_bar, 0, self._ui_metric("find_bar_height", 46), duration=155)
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
                current = self._ui_metric("find_bar_height", 46)
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
            self._remember_omnibox_input(value)
            self._release_address_focus_for_navigation()
            self.navigate_to(value, add_history=True)
        return "break"

    def _make_modern_menu(self, parent=None, *, font_size=None):
        """Create Tekzite's animated rounded popup menu surface.

        Unlike the old native ``tk.Menu`` wrapper this popup is rendered in a
        tiny borderless Tk window, so opening, hover and press feedback can be
        animated consistently across the menu bar, hamburger and context menus.
        """
        return _AnimatedPopupMenu(self, parent or self.root, font_size=font_size)

    @staticmethod
    def _menu_item_text(label, icon=""):
        label = str(label or "")
        icon = str(icon or "").strip()
        return f"  {icon}   {label}  " if icon else f"  {label}  "

    def _popup_menu_below(self, button, menu, *, min_width_offset=0):
        """Toggle an animated chrome menu directly under its menu-bar button."""
        try:
            self.root.update_idletasks()
            if isinstance(menu, _AnimatedPopupMenu) and menu.is_posted():
                menu.dismiss(include_parent=False)
                return
            active = getattr(self, "_active_popup_menu", None)
            if isinstance(active, _AnimatedPopupMenu) and active is not menu:
                active.dismiss(include_parent=False)
            x = int(button.winfo_rootx()) + int(min_width_offset or 0)
            y = int(button.winfo_rooty()) + int(button.winfo_height()) + self._ui_padding(3)
            if hasattr(button, "set_selected"):
                button.set_selected(True)
            if isinstance(menu, _AnimatedPopupMenu):
                menu._anchor_button = button
            menu.tk_popup(max(0, x), max(0, y))
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _show_address_context_menu(self, event):
        menu = self._make_modern_menu(self.root)
        menu.add_command(label=self._menu_item_text("Cut", "✂"), command=lambda: self.address.event_generate("<<Cut>>"))
        menu.add_command(label=self._menu_item_text("Copy", "▣"), command=lambda: self.address.event_generate("<<Copy>>"))
        menu.add_command(label=self._menu_item_text("Paste", "▤"), command=lambda: self.address.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label=self._menu_item_text("Paste and Go", "→"), command=self._paste_and_go)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except Exception: pass
        return "break"

    def _cancel_pending_tab_switch(self):
        """Invalidate an in-flight/scheduled tab activation without waiting.

        v10.5.32 also cancels the short close-handoff grace timer. That matters
        for the exact close-then-+ gesture: if Chromium activation has not begun,
        Tekzite now prevents it from beginning at all instead of merely marking
        its eventual result stale.
        """
        pending = getattr(self, "_tab_switch_pending_id", None) is not None
        handoff_after = getattr(self, "_closed_tab_handoff_after_id", None)
        retire_target = getattr(self, "_closed_tab_handoff_retire_target", None)
        if handoff_after is not None:
            try:
                self.root.after_cancel(handoff_after)
            except Exception:
                pass
            self._closed_tab_handoff_after_id = None
            self._closed_tab_handoff_retire_target = None
            if retire_target:
                self._queue_closed_target_retirement(retire_target)
            pending = True
        if not pending:
            return False
        self._tab_switch_serial += 1
        self._tab_switch_pending_id = None
        future = getattr(self, "_tab_switch_future", None)
        if future is not None:
            try:
                future.cancel()
            except Exception:
                pass
        return True

    def _new_tab(self, url=None, switch=True, navigate=True):
        # v10.5.32: the + button gets an exclusive interaction window. Any
        # closed Chromium target waiting to be destroyed is pushed farther out,
        # so opening the new tab never races renderer/compositor teardown.
        self._defer_closed_target_retirement(1800)
        # v10.5.31: a user opening a new tab wins immediately over the
        # replacement activation started by an active-tab close. Previously the
        # late replacement commit could steal selection back, making the +
        # button appear to lag until Chromium finished switching targets.
        if switch:
            self._cancel_pending_tab_switch()
        had_tabs = bool(self.tabs)
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
            "group": "",
            "sleeping": False,
            "last_active": time.monotonic(),
            "audible": False,
        }
        self._next_tab_id += 1
        self.tabs.append(tab)
        if had_tabs and self._motion_enabled():
            self._tab_open_animation_started[tab["id"]] = time.monotonic()
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
        if switch:
            self.update_history_buttons()
        if switch and navigate and url:
            self.navigate_to(url)
        elif switch and navigate and not url:
            if getattr(self, "preferences", DEFAULT_PREFERENCES).get("new_tab") == "homepage":
                # Paint the fresh tab before Chromium navigation begins. This is
                # especially important immediately after a page tab was closed.
                tab_id = tab["id"]
                homepage = self._homepage_url()
                def open_homepage_if_still_current():
                    if self.active_tab_id == tab_id and any(t.get("id") == tab_id for t in self.tabs):
                        self.navigate_to(homepage)
                try:
                    self.root.after(16 if self._motion_enabled() else 1, open_homepage_if_still_current)
                except Exception:
                    open_homepage_if_still_current()
            else:
                self._focus_address()
        return tab

    def _capture_active_tab_state(self):
        tab = self._active_tab()
        if tab is None:
            return
        # Do not replace the committed URL with unfinished address-bar edits.
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
            if (tab.get("loaded") or tab.get("sleeping")) and self._canonical_tab_url(tab.get("url")) == key:
                return tab
        return None

    def _commit_tab_switch(self, target, *, ui_already_selected=False):
        """Commit a Chromium target after activation without blocking Tekzite chrome.

        Normal tab clicks update chrome here. Active-tab close already selected the
        replacement synchronously before Chromium activation starts, so that path
        can skip a second tab-strip/address rebuild and only commit presentation.
        """
        if not ui_already_selected:
            self._capture_active_tab_state()
            self._navigation_generation += 1
            self.active_tab_id = target["id"]
            self.history = list(target.get("history") or [])
            target["history"] = self.history
            self.history_index = int(target.get("history_index", -1))
            self.url_var.set(target.get("url") or "")
            self.update_history_buttons()
            self._refresh_tab_strip()
        else:
            # The close handler already committed logical selection. Do not rebuild
            # Tk widgets again while the pointer release/new-tab click may be next
            # in the event queue.
            self._navigation_generation += 1
            self.active_tab_id = target["id"]
        target["last_active"] = time.monotonic()
        target["sleeping"] = False

        self._current_document = None
        presentation = target.get("presentation") or (
            "software" if self._use_chromium_software_surface_for_url(target.get("url", "")) else "native"
        )
        if target.get("software_fallback_reason") == "visible-surface":
            presentation = "software"
            target["presentation"] = "software"

        fast_native_switch = bool(
            presentation == "native"
            and self._embedded_mode
            and self._chromium_dwm_mode
            and self._dwm_surface_ready
            and self.edge_host.winfo_ismapped()
        )
        if presentation == "software":
            self._set_chromium_presentation_fast("software", target["chromium_target_id"])
            self._show_chromium_software_surface(target["chromium_target_id"])
        elif fast_native_switch:
            self._chromium_frame_target_id = target["chromium_target_id"]
            self._chromium_software_mode = False
            # Zoom verification is intentionally outside the visual switch path.
            self.root.after(120, lambda tid=target["chromium_target_id"]: self._apply_chromium_zoom(tid))
        else:
            self._set_chromium_presentation_fast("native", target["chromium_target_id"])
            self._show_embedded_host()
            self._schedule_embedded_surface_wake()
            self._schedule_chromium_zoom_apply(target_id=target["chromium_target_id"])
        self.status_var.set(f"Switched to existing tab | {target.get('url','')}")
        return True

    def _recover_failed_tab_activation(self, target):
        """Reload a tab whose Chromium target vanished after helper failure."""
        self._capture_active_tab_state()
        self._navigation_generation += 1
        self.active_tab_id = target["id"]
        target["last_active"] = time.monotonic()
        target["sleeping"] = False
        self.history = list(target.get("history") or [])
        target["history"] = self.history
        self.history_index = int(target.get("history_index", -1))
        target["chromium_target_id"] = None
        target["loaded"] = False
        target["loading"] = False
        target["ready_state"] = ""
        self.url_var.set(target.get("url") or "")
        self.update_history_buttons()
        self._refresh_tab_strip()
        url = str(target.get("url") or "")
        if url:
            self.status_var.set("Chromium tab recovered; reloading page…")
            self.navigate_to(url, add_history=False, reuse_existing=False)
        else:
            self._show_native_canvas()
            self._focus_address()
        return True

    def _switch_tab(self, tab_id, on_committed=None, *, force_activate=False, ui_already_selected=False):
        target = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if target is None:
            return False

        # A second click can reverse a still-running switch. Do not treat the
        # currently selected Tk tab as a no-op while Chromium is moving elsewhere.
        if tab_id == self.active_tab_id and self._tab_switch_pending_id is None and not force_activate:
            if callable(on_committed):
                try:
                    on_committed()
                except Exception:
                    pass
            return True

        self._wake_tab_if_needed(target)
        if target.get("engine") == "chromium" and target.get("chromium_target_id"):
            self._tab_switch_serial += 1
            serial = self._tab_switch_serial
            self._tab_switch_pending_id = tab_id
            target_id = target["chromium_target_id"]
            switch_started = time.monotonic()
            future = self._tab_switch_executor.submit(activate_embedded_chromium_target, target_id)
            self._tab_switch_future = future
            callback_fired = False

            def finish_callback_once():
                nonlocal callback_fired
                if callback_fired:
                    return
                callback_fired = True
                if callable(on_committed):
                    try:
                        on_committed()
                    except Exception:
                        pass

            def finish_switch():
                # v10.5.31: stop polling a superseded activation immediately.
                # This is especially important when the user hits + right after
                # closing the active tab. The old 8 ms polling loop could live
                # for the full activation timeout, while its eventual commit
                # could also steal focus back from the freshly-created tab.
                if serial != self._tab_switch_serial:
                    if getattr(self, "_tab_switch_future", None) is future:
                        self._tab_switch_future = None
                    finish_callback_once()
                    return
                if not future.done():
                    # v10.5.28: never let one wedged Chromium activation leave
                    # Tekzite in a permanent pending-tab state. Active-tab close
                    # now hides the old DWM source first, so a bounded fallback
                    # can safely recover the replacement without freezing chrome.
                    if time.monotonic() - switch_started >= 4.0:
                        if serial != self._tab_switch_serial:
                            return
                        self._tab_switch_serial += 1
                        self._tab_switch_pending_id = None
                        if getattr(self, "_tab_switch_future", None) is future:
                            self._tab_switch_future = None
                        try:
                            future.cancel()
                        except Exception:
                            pass
                        current_target = next((t for t in self.tabs if t.get("id") == tab_id), None)
                        self._show_native_canvas()
                        if current_target is not None:
                            self.status_var.set("Tab switch timed out; recovering…")
                            self._recover_failed_tab_activation(current_target)
                            finish_callback_once()
                        else:
                            self.status_var.set("Tab switch timed out")
                            finish_callback_once()
                        return
                    self.root.after(8, finish_switch)
                    return
                # Ignore stale UI commits. The single-worker executor guarantees
                # newer activation requests run after older ones, so the final
                # Chromium target also matches the latest requested tab.
                if serial != self._tab_switch_serial:
                    finish_callback_once()
                    return
                self._tab_switch_pending_id = None
                if getattr(self, "_tab_switch_future", None) is future:
                    self._tab_switch_future = None
                try:
                    activated = bool(future.result())
                except Exception:
                    activated = False
                if not activated:
                    current_target = next((t for t in self.tabs if t.get("id") == tab_id), None)
                    if current_target is not None:
                        # Drop the stale DWM/native presentation before recovery.
                        # This guarantees an active-tab close never destroys the
                        # source HWND while Tekzite is still visibly mirroring it.
                        self._show_native_canvas()
                        self._recover_failed_tab_activation(current_target)
                        finish_callback_once()
                    else:
                        self.status_var.set("Tab switch failed")
                        finish_callback_once()
                    return
                current_target = next((t for t in self.tabs if t.get("id") == tab_id), None)
                if current_target is None or current_target.get("chromium_target_id") != target_id:
                    finish_callback_once()
                    return
                try:
                    self._commit_tab_switch(current_target, ui_already_selected=ui_already_selected)
                except Exception:
                    self.status_var.set("Tab switch presentation failed")
                    finish_callback_once()
                    return
                finish_callback_once()

            self.root.after(1, finish_switch)
            return True

        # Blank/unloaded tab has no Chromium activation cost. Commit it directly.
        self._capture_active_tab_state()
        self._navigation_generation += 1
        self._tab_switch_serial += 1
        self._tab_switch_pending_id = None
        self.active_tab_id = tab_id
        self.history = list(target.get("history") or [])
        target["history"] = self.history
        self.history_index = int(target.get("history_index", -1))
        self.url_var.set(target.get("url") or "")
        self.update_history_buttons()
        self._refresh_tab_strip()
        self._show_native_canvas()
        self._current_document = None
        try:
            self.canvas.delete("all")
        except Exception:
            pass
        self.status_var.set("Ready")
        if target.pop("restore_pending", False):
            self.navigate_to(target["url"], reuse_existing=False)
        if callable(on_committed):
            try:
                on_committed()
            except Exception:
                pass
        return True

    def _schedule_sleeping_tabs(self, delay_ms=30000):
        if getattr(self, "_closing", False):
            return
        try:
            if self._sleeping_tabs_after_id is not None:
                self.root.after_cancel(self._sleeping_tabs_after_id)
        except Exception:
            pass
        try:
            self._sleeping_tabs_after_id = self.root.after(max(1000, int(delay_ms)), self._sleeping_tabs_tick)
        except Exception:
            self._sleeping_tabs_after_id = None

    def _sleeping_tabs_tick(self):
        self._sleeping_tabs_after_id = None
        if getattr(self, "_closing", False):
            return
        if self.preferences.get("sleeping_tabs_enabled", True):
            timeout = max(5, min(240, int(self.preferences.get("sleeping_tabs_minutes", 30)))) * 60.0
            now = time.monotonic()
            for tab in list(self.tabs):
                if tab.get("id") == self.active_tab_id or tab.get("pinned") or tab.get("sleeping") or tab.get("audible"):
                    continue
                if not tab.get("chromium_target_id") or not tab.get("url"):
                    continue
                last_active = float(tab.get("last_active") or now)
                if now - last_active >= timeout:
                    self._sleep_tab(tab)
        self._schedule_sleeping_tabs(30000)

    def _sleep_tab(self, tab):
        if not isinstance(tab, dict) or tab.get("id") == self.active_tab_id or tab.get("pinned"):
            return False
        target_id = tab.get("chromium_target_id")
        if not target_id or not tab.get("url"):
            return False
        try:
            close_embedded_chromium_target(target_id)
        except Exception:
            return False
        tab["chromium_target_id"] = None
        tab["loaded"] = False
        tab["loading"] = False
        tab["ready_state"] = ""
        tab["sleeping"] = True
        tab["restore_pending"] = True
        self._refresh_tab_strip()
        return True

    def _wake_tab_if_needed(self, tab):
        if not tab or not tab.get("sleeping"):
            return False
        tab["sleeping"] = False
        tab["restore_pending"] = bool(tab.get("url"))
        tab["last_active"] = time.monotonic()
        return True

    def _normalized_tab_groups(self):
        groups = self.preferences.get("tab_groups", {})
        if not isinstance(groups, dict):
            groups = {}
        cleaned = {}
        for name, meta in groups.items():
            name = str(name or "").strip()[:32]
            if not name:
                continue
            meta = meta if isinstance(meta, dict) else {}
            color = str(meta.get("color") or "#7965ff")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                color = "#7965ff"
            cleaned[name] = {"color": color, "collapsed": bool(meta.get("collapsed", False))}
        return cleaned

    def _persist_tab_groups(self):
        self.preferences["tab_groups"] = self._normalized_tab_groups()
        try:
            self._persist_preferences()
        except Exception as exc:
            self.status_var.set(f"Tab groups changed for this session; save failed: {exc}")

    def _create_tab_group(self, tab_id=None):
        name = self._ask_string_animated("New Tab Group", "Group name:", parent=self.root)
        if not name:
            return
        name = str(name).strip()[:32]
        if not name:
            return
        groups = self._normalized_tab_groups()
        if name not in groups:
            palette = ("#7965ff", "#31b7a3", "#df8b3a", "#db5f80", "#5b9cf5", "#a576d6")
            groups[name] = {"color": palette[len(groups) % len(palette)], "collapsed": False}
        self.preferences["tab_groups"] = groups
        if tab_id is not None:
            tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
            if tab is not None:
                tab["group"] = name
        self._persist_tab_groups()
        self._refresh_tab_strip()

    def _assign_tab_group(self, tab_id, group):
        tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if tab is None:
            return
        group = str(group or "")
        if group and group not in self._normalized_tab_groups():
            return
        tab["group"] = group
        self._refresh_tab_strip()

    def _toggle_tab_group(self, group):
        groups = self._normalized_tab_groups()
        if group not in groups:
            return
        groups[group]["collapsed"] = not groups[group].get("collapsed", False)
        self.preferences["tab_groups"] = groups
        self._persist_tab_groups()
        self._refresh_tab_strip()

    def _show_tab_groups(self):
        win = self._new_animated_toplevel(self.root)
        win.title("Tekzite Tab Groups")
        win.geometry("520x390")
        win.transient(self.root)
        win.configure(bg=self.ui["bg"])
        tree = ttk.Treeview(win, columns=("Group", "Tabs", "State"), show="headings", selectmode="browse")
        for col, width in (("Group", 230), ("Tabs", 80), ("State", 120)):
            tree.heading(col, text=col); tree.column(col, width=width)
        tree.pack(fill="both", expand=True, padx=12, pady=12)
        buttons = tk.Frame(win, bg=self.ui["bg"]); buttons.pack(fill="x", padx=12, pady=(0, 12))
        def refresh():
            tree.delete(*tree.get_children())
            groups = self._normalized_tab_groups()
            for index, (name, meta) in enumerate(groups.items()):
                count = sum(1 for tab in self.tabs if tab.get("group") == name)
                tree.insert("", "end", iid=str(index), values=(name, count, "collapsed" if meta.get("collapsed") else "expanded"), tags=(name,))
        def selected_name():
            selected = tree.selection()
            if not selected: return None
            return str(tree.item(selected[0], "values")[0])
        def toggle():
            name = selected_name()
            if name: self._toggle_tab_group(name); refresh()
        def delete():
            name = selected_name()
            if not name: return
            groups = self._normalized_tab_groups(); groups.pop(name, None); self.preferences["tab_groups"] = groups
            for tab in self.tabs:
                if tab.get("group") == name: tab["group"] = ""
            self._persist_tab_groups(); self._refresh_tab_strip(); refresh()
        tk.Button(buttons, text="New Group", command=lambda: (self._create_tab_group(), refresh()), bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(buttons, text="Expand / Collapse", command=toggle, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat").pack(side="left", padx=4)
        tk.Button(buttons, text="Delete", command=delete, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat").pack(side="left", padx=4)
        refresh()
        return "break"

    def _duplicate_tab(self, tab_id):
        tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if tab is None:
            return None
        url = str(tab.get("url") or "").strip()
        return self._new_tab(url=url or None, switch=True, navigate=bool(url))

    def _close_other_tabs(self, tab_id):
        for other in list(self.tabs):
            if other.get("id") != tab_id and not other.get("pinned"):
                self._close_tab(other.get("id"))
        self._switch_tab(tab_id)

    def _close_tabs_to_right(self, tab_id):
        ids = [t.get("id") for t in self.tabs]
        try:
            index = ids.index(tab_id)
        except ValueError:
            return
        for other_id in ids[index + 1:]:
            if not next(t for t in self.tabs if t["id"] == other_id).get("pinned"):
                self._close_tab(other_id)

    def _show_tab_context_menu(self, event, tab_id):
        tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if tab is None:
            return
        menu = self._make_modern_menu(self.root)
        menu.add_command(label=self._menu_item_text("New Tab", "+"), command=self._new_tab, accelerator="Ctrl+T")
        menu.add_command(label=self._menu_item_text("Unpin Tab" if tab.get("pinned") else "Pin Tab", "◆"), command=lambda: self._toggle_pin(tab_id))
        menu.add_command(label=self._menu_item_text("Duplicate Tab", "▣"), command=lambda: self._duplicate_tab(tab_id))
        group_menu = self._make_modern_menu(menu)
        group_menu.add_command(label=self._menu_item_text("New Group…", "+"), command=lambda: self._create_tab_group(tab_id))
        groups = self._normalized_tab_groups()
        if groups:
            group_menu.add_separator()
            for group_name in groups:
                group_menu.add_command(label=self._menu_item_text(group_name, "•"), command=lambda g=group_name: self._assign_tab_group(tab_id, g))
        if tab.get("group"):
            group_menu.add_separator()
            group_menu.add_command(label=self._menu_item_text("Remove from Group", "×"), command=lambda: self._assign_tab_group(tab_id, ""))
        menu.add_cascade(label=self._menu_item_text("Move to Group", "›"), menu=group_menu)
        menu.add_command(label=self._menu_item_text("Reopen Closed Tab", "↶"), command=self._restore_closed_tab, accelerator="Ctrl+Shift+T")
        menu.add_separator()
        url = str(tab.get("url") or "")
        menu.add_command(label=self._menu_item_text("Copy Tab URL", "⧉"), command=lambda u=url: self._clipboard_set(u), state=("normal" if url else "disabled"))
        menu.add_separator()
        menu.add_command(label=self._menu_item_text("Close Tab", "×"), command=lambda: self._close_tab(tab_id), accelerator="Ctrl+W")
        menu.add_command(label=self._menu_item_text("Close Other Tabs", "×"), command=lambda: self._close_other_tabs(tab_id), state=("normal" if len(self.tabs) > 1 else "disabled"))
        ids = [t.get("id") for t in self.tabs]
        has_right = tab_id in ids and ids.index(tab_id) < len(ids) - 1
        menu.add_command(label=self._menu_item_text("Close Tabs to the Right", "→"), command=lambda: self._close_tabs_to_right(tab_id), state=("normal" if has_right else "disabled"))
        self._popup_context_menu(menu, event)

    def _queue_closed_target_retirement(self, target_id, delay_ms=1800):
        """Retire closed Chromium targets only after an interaction grace period.

        Chromium target destruction can trigger renderer/compositor teardown in
        the browser process. Even when requested from a Python worker, that work
        can momentarily contend with creation/activation of the very next tab.
        Keep the dead target parked and invisible for a short period, then close
        it when the user has stopped interacting with the tab strip.
        """
        target_id = str(target_id or "").strip()
        if not target_id:
            return False
        queue = getattr(self, "_closed_target_retire_queue", None)
        if queue is None:
            queue = set()
            self._closed_target_retire_queue = queue
        queue.add(target_id)
        return self._defer_closed_target_retirement(delay_ms)

    def _defer_closed_target_retirement(self, delay_ms=1800):
        queue = getattr(self, "_closed_target_retire_queue", None)
        if not queue:
            return False
        after_id = getattr(self, "_closed_target_retire_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
            self._closed_target_retire_after_id = None

        def drain():
            self._closed_target_retire_after_id = None
            pending = list(getattr(self, "_closed_target_retire_queue", set()))
            self._closed_target_retire_queue.clear()
            for tid in pending:
                self._retire_chromium_target_when_detached(tid)

        try:
            self._closed_target_retire_after_id = self.root.after(max(250, int(delay_ms)), drain)
            return True
        except Exception:
            # Minimal/test Tk fallback. Production always has root.after.
            drain()
            return True

    def _retire_chromium_target(self, target_id):
        """Close an obsolete Chromium target without blocking Tk's UI thread."""
        target_id = str(target_id or "").strip()
        if not target_id:
            return

        def retire():
            try:
                close_embedded_chromium_target(target_id)
            except Exception:
                pass

        executor = getattr(self, "_executor", None)
        if executor is not None:
            try:
                executor.submit(retire)
                return
            except Exception:
                pass
        # Lightweight/test fallback. Production BrowserApp always owns the
        # Chromium executor, so the normal path above stays off Tk's thread.
        retire()

    def _retire_chromium_target_when_detached(self, target_id, attempt=0):
        """Retire a closed target only after it is no longer the visible source.

        A close can be superseded by an immediate new-tab or another tab switch.
        Never destroy the HWND/CDP target while Tekzite still considers it the
        current presentation source. This check is intentionally timer-based and
        non-blocking so the Tk event loop keeps accepting clicks throughout.
        """
        target_id = str(target_id or "").strip()
        if not target_id:
            return
        still_visible = bool(
            (bool(getattr(self, "_embedded_mode", False)) or bool(getattr(self, "_chromium_software_mode", False)))
            and str(getattr(self, "_chromium_frame_target_id", "") or "") == target_id
        )
        if still_visible and attempt < 120:
            try:
                self.root.after(25, lambda tid=target_id, n=attempt + 1: self._retire_chromium_target_when_detached(tid, n))
                return
            except Exception:
                pass
        self._retire_chromium_target(target_id)

    def _select_replacement_tab_chrome(self, replacement):
        """Select a replacement tab using Tk-only state updates.

        This helper deliberately contains no Chromium, CDP, DWM or Win32 calls.
        It is safe to run inside the tab close mouse/key callback and returns as
        soon as the visible Tekzite chrome has moved to the replacement tab.
        """
        self.active_tab_id = replacement["id"]
        replacement["last_active"] = time.monotonic()
        replacement["sleeping"] = False
        self.history = list(replacement.get("history") or [])
        replacement["history"] = self.history
        self.history_index = int(replacement.get("history_index", -1))
        self._current_document = None
        try:
            self.url_var.set(replacement.get("url") or "")
        except Exception:
            pass
        try:
            self.update_history_buttons()
        except Exception:
            pass
        self._refresh_tab_strip()

    def _schedule_closed_tab_handoff(self, replacement, old_target_id):
        """Hand off the page only after a short, cancellable interaction grace.

        The previous after-idle handoff could start Chromium activation almost
        immediately after the close click. If the user then hit +, Tekzite's UI
        was logically free but Chromium was already switching/tearing down page
        machinery. v10.5.32 leaves a brief tab-strip grace window so an immediate
        new-tab action cancels the handoff before Chromium work starts at all.
        """
        replacement_id = replacement.get("id")
        self._tab_switch_serial += 1
        reservation = self._tab_switch_serial
        self._tab_switch_pending_id = replacement_id

        # Cancel an older not-yet-started close handoff, but keep its target in
        # the deferred retirement queue.
        old_after = getattr(self, "_closed_tab_handoff_after_id", None)
        if old_after is not None:
            try:
                self.root.after_cancel(old_after)
            except Exception:
                pass
            previous_retire = getattr(self, "_closed_tab_handoff_retire_target", None)
            if previous_retire:
                self._queue_closed_target_retirement(previous_retire)

        self._closed_tab_handoff_retire_target = str(old_target_id or "") or None

        def retire_after_handoff(tid=old_target_id):
            # Do not tear Chromium down while the user is likely to click + next.
            self._queue_closed_target_retirement(tid, 1800)

        def begin_handoff():
            self._closed_tab_handoff_after_id = None
            self._closed_tab_handoff_retire_target = None
            if (
                reservation != self._tab_switch_serial
                or self._tab_switch_pending_id != replacement_id
                or self.active_tab_id != replacement_id
            ):
                retire_after_handoff()
                return
            current = next((t for t in self.tabs if t.get("id") == replacement_id), None)
            if current is None:
                retire_after_handoff()
                return
            # A blank replacement needs no Chromium activation at all.
            if not current.get("chromium_target_id"):
                self._tab_switch_pending_id = None
                self._show_native_canvas()
                retire_after_handoff()
                return
            self._switch_tab(
                replacement_id,
                on_committed=retire_after_handoff,
                force_activate=True,
                ui_already_selected=True,
            )

        try:
            # Roughly one tab animation beat. Fast close->+ gestures now land
            # before Chromium activation begins, not while it is already busy.
            self._closed_tab_handoff_after_id = self.root.after(180, begin_handoff)
        except Exception:
            begin_handoff()

    def _close_tab(self, tab_id):
        """Close a tab without running Chromium work inside the close callback.

        v10.5.31 treats the GUI and Chromium as two independent phases. The tab
        disappears and the replacement becomes clickable immediately. Only after
        Tk returns to its event loop do we activate the replacement target and
        retire the closed target in background work.
        """
        self._tab_open_animation_started.pop(tab_id, None)
        tab = next((t for t in self.tabs if t.get("id") == tab_id), None)
        if tab is None:
            return

        if tab.get("url") or tab.get("loaded"):
            snap = {k: tab.get(k) for k in ("url", "title", "history", "history_index", "pinned", "group")}
            self._closed_tabs.append(snap)
            if len(self._closed_tabs) > 20:
                self._closed_tabs = self._closed_tabs[-20:]

        target_id = str(tab.get("chromium_target_id") or "")
        index = self.tabs.index(tab)
        was_active = tab_id == self.active_tab_id

        if self._tab_switch_pending_id == tab_id:
            self._tab_switch_serial += 1
            self._tab_switch_pending_id = None

        self.tabs.remove(tab)

        if not self.tabs:
            # Build the fresh blank tab first. DWM detach/target retirement are
            # deferred so Ctrl+W or clicking × never enters Win32/CDP work from
            # inside the close event itself.
            self.active_tab_id = None
            self._navigation_generation += 1
            fresh = {
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
                "group": "",
                "sleeping": False,
                "last_active": time.monotonic(),
                "audible": False,
            }
            self._next_tab_id += 1
            self.tabs.append(fresh)
            self._select_replacement_tab_chrome(fresh)
            # _hide_dwm_host now uses ShowWindowAsync, so this is a Tk-fast path
            # and can make the blank tab visible without waiting on Chromium.
            self._show_native_canvas()
            self._queue_closed_target_retirement(target_id, 1800)
            try:
                self.root.after_idle(self._focus_address)
            except Exception:
                pass
            return

        if was_active:
            replacement = self.tabs[min(index, len(self.tabs) - 1)]
            self._select_replacement_tab_chrome(replacement)
            try:
                self.status_var.set("Ready")
            except Exception:
                pass
            self._schedule_closed_tab_handoff(replacement, target_id)
        else:
            self._refresh_tab_strip()
            # Renderer teardown is intentionally idle-debounced too. Closing an
            # inactive page must not make the next + click pay Chromium's cost.
            self._queue_closed_target_retirement(target_id, 1800)

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

    def _on_dwm_keyboard_sink_key(self, event):
        """Consume Tk sink keys while the native DWM poller owns page input.

        v10.5.46 forwarded from this callback, but the user's failing machine
        demonstrated that Tk can own a focused child HWND without delivering a
        useful KeyPress stream.  Keep these counters as diagnostics and let the
        foreground-only native poller be the authoritative DWM keyboard source.
        """
        self._dwm_keyboard_sink_messages += 1
        char = getattr(event, "char", "") or ""
        keysym = getattr(event, "keysym", "") or ""
        state = int(getattr(event, "state", 0) or 0)
        self._dwm_keyboard_sink_last = (keysym, char, state)
        if char and char.isprintable():
            self._dwm_keyboard_sink_chars += 1
        if getattr(self, "_dwm_keyboard_poll_active", False):
            return "break"
        return self._on_chromium_surface_key(event)

    @staticmethod
    def _dwm_keyboard_poll_vks():
        """Virtual keys worth sampling while a DWM page owns keyboard input."""
        return (
            0x08, 0x09, 0x0D, 0x1B, 0x20,
            0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E,
            *range(0x30, 0x5B),       # 0-9 and A-Z
            *range(0x60, 0x70),       # numpad
            *range(0x70, 0x7C),       # F1-F12
            *range(0xBA, 0xC1),       # OEM punctuation
            *range(0xDB, 0xDF),       # OEM punctuation
            0xE2,                     # OEM 102 key
        )

    def _stop_dwm_keyboard_poll(self):
        after_id = getattr(self, "_dwm_keyboard_poll_after_id", None)
        self._dwm_keyboard_poll_after_id = None
        self._dwm_keyboard_poll_active = False
        self._dwm_keyboard_poll_down = {}
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass

    def _schedule_dwm_keyboard_poll(self, delay=0):
        """Start the safe foreground-only native keyboard fallback."""
        if os.name != "nt" or not (self._embedded_mode and self._chromium_dwm_mode):
            return False
        self._dwm_keyboard_poll_active = True
        if self._dwm_keyboard_poll_after_id is None:
            try:
                self._dwm_keyboard_poll_after_id = self.root.after(
                    max(0, int(delay)), self._poll_dwm_keyboard
                )
            except Exception:
                self._dwm_keyboard_poll_active = False
                return False
        return True

    def _dwm_keyboard_modifiers(self, user32):
        get_async = user32.GetAsyncKeyState
        control = bool(int(get_async(0x11)) & 0x8000)
        shift = bool(int(get_async(0x10)) & 0x8000)
        alt = bool(int(get_async(0x12)) & 0x8000)
        meta = bool((int(get_async(0x5B)) | int(get_async(0x5C))) & 0x8000)
        return control, shift, alt, meta

    def _dwm_vk_to_text(self, user32, vk, *, control=False, shift=False, alt=False):
        """Translate one Windows VK through the active layout without hooks."""
        try:
            import ctypes
            from ctypes import wintypes
            BYTE = ctypes.c_ubyte
            keyboard_state = (BYTE * 256)()
            user32.GetKeyboardState.argtypes = [ctypes.POINTER(BYTE)]
            user32.GetKeyboardState.restype = wintypes.BOOL
            user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
            user32.GetKeyboardLayout.restype = ctypes.c_void_p
            user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
            user32.MapVirtualKeyExW.restype = wintypes.UINT
            user32.ToUnicodeEx.argtypes = [
                wintypes.UINT, wintypes.UINT, ctypes.POINTER(BYTE), wintypes.LPWSTR,
                ctypes.c_int, wintypes.UINT, ctypes.c_void_p,
            ]
            user32.ToUnicodeEx.restype = ctypes.c_int
            user32.GetKeyState.argtypes = [ctypes.c_int]
            user32.GetKeyState.restype = ctypes.c_short
            if not user32.GetKeyboardState(keyboard_state):
                return ""
            # GetKeyboardState reflects the thread queue. The whole reason this
            # path exists is that the Tk queue can miss DWM-page keys, so stamp
            # the physical modifier/current-key state into the translation map.
            keyboard_state[int(vk) & 0xFF] |= 0x80
            for mod_vk, down in ((0x10, shift), (0x11, control), (0x12, alt)):
                keyboard_state[mod_vk] = (keyboard_state[mod_vk] & 0x01) | (0x80 if down else 0)
            if int(user32.GetKeyState(0x14)) & 0x0001:  # Caps Lock
                keyboard_state[0x14] |= 0x01
            hkl = user32.GetKeyboardLayout(0)
            scan = int(user32.MapVirtualKeyExW(int(vk), 0, hkl) or 0)
            buf = ctypes.create_unicode_buffer(8)
            # Flag 4 asks modern Windows not to mutate the kernel dead-key
            # buffer while we translate, which keeps this polling path isolated.
            count = int(user32.ToUnicodeEx(int(vk), scan, keyboard_state, buf, len(buf), 4, hkl))
            if count <= 0:
                return ""
            return "".join(buf[:count])
        except Exception:
            return ""

    def _dispatch_dwm_polled_vk(self, user32, vk):
        """Translate and forward one physically observed DWM-page key press."""
        control, shift, alt, meta = self._dwm_keyboard_modifiers(user32)
        vk = int(vk)
        self._dwm_keyboard_poll_events += 1
        self._dwm_keyboard_poll_last = (vk, bool(control), bool(shift), bool(alt), bool(meta))

        # Keep OS/shell combinations out of the browser input bridge.
        if meta or (alt and vk in {0x09, 0x1B, 0x73}) or (control and vk == 0x1B):
            return False

        modifiers = (8 if shift else 0) | (2 if control else 0) | (1 if alt else 0) | (4 if meta else 0)

        # Editing shortcuts belong to the focused webpage. Paste uses the same
        # insertText route as the rest of Tekzite so clipboard text does not
        # depend on an off-screen Chromium HWND owning the Windows clipboard UI.
        if control and not alt and 0x41 <= vk <= 0x5A:
            letter = chr(vk)
            if letter == "V":
                try:
                    text = self.root.clipboard_get()
                except Exception:
                    text = ""
                if text:
                    self._submit_chromium_input(
                        dispatch_embedded_chromium_key, text=text, event_type="insertText",
                        target_id=self._chromium_frame_target_id, refresh=True,
                    )
                return True
            if letter in {"A", "C", "X", "Z", "Y"}:
                self._submit_chromium_input(
                    dispatch_embedded_chromium_key, letter.lower(), event_type="keyDown",
                    modifiers=modifiers, windows_vk=vk, code=f"Key{letter}",
                    target_id=self._chromium_frame_target_id,
                )
                self._submit_chromium_input(
                    dispatch_embedded_chromium_key, letter.lower(), event_type="keyUp",
                    modifiers=modifiers, windows_vk=vk, code=f"Key{letter}",
                    target_id=self._chromium_frame_target_id, refresh=True,
                )
                return True
            return False

        text = self._dwm_vk_to_text(
            user32, vk, control=control, shift=shift, alt=alt
        )
        altgr_text = bool(text and control and alt)
        if text and all(ch.isprintable() for ch in text) and (not (control or alt) or altgr_text):
            self._dwm_keyboard_poll_chars += len(text)
            self._submit_chromium_input(
                dispatch_embedded_chromium_key, text=text, event_type="insertText",
                target_id=self._chromium_frame_target_id, refresh=True,
            )
            return True

        special = {
            0x08: ("Backspace", "Backspace"), 0x09: ("Tab", "Tab"),
            0x0D: ("Enter", "Enter"), 0x1B: ("Escape", "Escape"),
            0x21: ("PageUp", "PageUp"), 0x22: ("PageDown", "PageDown"),
            0x23: ("End", "End"), 0x24: ("Home", "Home"),
            0x25: ("ArrowLeft", "ArrowLeft"), 0x26: ("ArrowUp", "ArrowUp"),
            0x27: ("ArrowRight", "ArrowRight"), 0x28: ("ArrowDown", "ArrowDown"),
            0x2E: ("Delete", "Delete"),
        }
        if vk in special:
            key, code = special[vk]
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
            return True
        return False

    def _poll_dwm_keyboard(self):
        """Poll physical keys only while Tekzite's DWM webpage owns input."""
        self._dwm_keyboard_poll_after_id = None
        if not (os.name == "nt" and self._embedded_mode and self._chromium_dwm_mode
                and self._dwm_surface_ready and self._chromium_page_keyboard_active
                and not self._address_focus_active):
            self._dwm_keyboard_poll_active = False
            self._dwm_keyboard_poll_down = {}
            return
        next_delay = 8
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short

            foreground = user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            if foreground:
                user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
            ours = bool(foreground and int(pid.value) == int(os.getpid()))
            self._dwm_keyboard_poll_foreground = ours
            if not ours:
                self._dwm_keyboard_poll_down = {}
                next_delay = 40
            else:
                now = time.monotonic()
                down = self._dwm_keyboard_poll_down
                for vk in self._dwm_keyboard_poll_vks():
                    raw = int(user32.GetAsyncKeyState(int(vk))) & 0xFFFF
                    held = bool(raw & 0x8000)
                    pressed_since_poll = bool(raw & 0x0001)
                    if vk not in down:
                        if held or pressed_since_poll:
                            self._dispatch_dwm_polled_vk(user32, vk)
                            if held:
                                down[vk] = now + 0.42
                    elif not held:
                        down.pop(vk, None)
                    elif now >= float(down.get(vk) or 0.0):
                        # Match a normal Windows-style repeat closely enough for
                        # text editing while keeping this loop deterministic.
                        self._dispatch_dwm_polled_vk(user32, vk)
                        down[vk] = now + 0.035
            self._dwm_keyboard_poll_error = None
        except Exception as exc:
            self._dwm_keyboard_poll_error = f"{type(exc).__name__}: {exc}"
            self._dwm_keyboard_poll_active = False
            self._dwm_keyboard_poll_down = {}
            return
        if self._dwm_keyboard_poll_active:
            try:
                self._dwm_keyboard_poll_after_id = self.root.after(next_delay, self._poll_dwm_keyboard)
            except Exception:
                self._dwm_keyboard_poll_active = False

    def _ensure_dwm_keyboard_sink(self):
        """Create the DWM keyboard focus target lazily, after a real page click.

        This deliberately uses a normal Tk child rather than v10.5.44's raw
        STATIC HWND + Python WNDPROC subclass.  Tk owns the native window and
        its message procedure for the full widget lifetime, removing the crash
        path while still giving Windows a concrete HWND to focus.
        """
        if os.name != "nt" or not (self._embedded_mode and self._chromium_dwm_mode):
            return None
        sink = self._dwm_keyboard_sink_widget
        try:
            if sink is not None and int(sink.winfo_exists()):
                return sink
        except Exception:
            pass
        try:
            sink = tk.Entry(
                self.edge_host,
                width=1,
                bg=self.ui.get("bg", "#000000"),
                fg=self.ui.get("bg", "#000000"),
                insertbackground=self.ui.get("bg", "#000000"),
                highlightthickness=0, bd=0, takefocus=True,
                exportselection=False,
            )
            # Keep the focus target mapped so Windows can focus it, but make it
            # physically negligible and lower it beneath the interactive plane.
            sink.place(x=-2, y=-2, width=1, height=1)
            try:
                sink.lower()
            except Exception:
                pass
            sink.bind("<KeyPress>", self._on_dwm_keyboard_sink_key)
            sink.bind("<FocusIn>", lambda _e: setattr(self, "_dwm_keyboard_sink_focused", True))
            sink.bind("<FocusOut>", lambda _e: setattr(self, "_dwm_keyboard_sink_focused", False))
            hwnd = int(sink.winfo_id())
            self._dwm_keyboard_sink_widget = sink
            self._dwm_keyboard_sink_hwnd = hwnd or None
            self._dwm_keyboard_sink_create_count += 1
            return sink
        except Exception:
            self._dwm_keyboard_sink_widget = None
            self._dwm_keyboard_sink_hwnd = None
            self._dwm_keyboard_sink_focused = False
            return None

    def _focus_dwm_keyboard_sink(self):
        """Give a clicked DWM page real Windows focus without touching bootstrap."""
        if os.name != "nt" or not (self._embedded_mode and self._chromium_dwm_mode):
            return False
        if not self._dwm_surface_ready or self._address_focus_active:
            return False
        sink = self._ensure_dwm_keyboard_sink()
        if sink is None:
            return False
        try:
            # Keep Tk's own focus model in sync first so its KeyPress binding
            # receives translated characters, IME output and keyboard layout.
            sink.focus_force()
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
            user32.SetFocus.argtypes = [wintypes.HWND]
            user32.SetFocus.restype = wintypes.HWND
            user32.GetFocus.argtypes = []
            user32.GetFocus.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.SetActiveWindow.argtypes = [wintypes.HWND]
            user32.SetActiveWindow.restype = wintypes.HWND
            hwnd = int(self._dwm_keyboard_sink_hwnd or sink.winfo_id())
            # This runs only in direct response to a page click, so activating
            # Tekzite here follows normal Windows foreground-focus rules and
            # cannot race the Chromium bootstrap.
            inner = int(self.root.winfo_id())
            top = int(user32.GetAncestor(wintypes.HWND(inner), 2) or inner)  # GA_ROOT
            user32.SetForegroundWindow(wintypes.HWND(top))
            user32.SetActiveWindow(wintypes.HWND(top))
            user32.SetFocus(wintypes.HWND(hwnd))
            focused = int(user32.GetFocus() or 0)
            self._dwm_keyboard_sink_focused = focused == hwnd
            if self._dwm_keyboard_sink_focused:
                self._dwm_keyboard_sink_focus_count += 1
            return bool(self._dwm_keyboard_sink_focused)
        except Exception:
            # Tk focus is still a useful fallback if Win32 focus introspection
            # is unavailable on a particular Windows build.
            try:
                focused = self.root.focus_get() is sink
            except Exception:
                focused = False
            self._dwm_keyboard_sink_focused = bool(focused)
            if focused:
                self._dwm_keyboard_sink_focus_count += 1
            return bool(focused)

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

            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
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
            WS_EX_LAYERED = 0x00080000
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            hwnd = user32.CreateWindowExW(
                WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED,
                "STATIC", "", WS_POPUP,
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
            self._dwm_host_owner_hwnd = owner
            self._dwm_host_size = (1, 1)
            self._dwm_host_region_signature = None
            self._dwm_host_visible = False
            self._dwm_host_alpha = None
            self._dwm_host_rect = None
            return hwnd_i
        except Exception:
            self._dwm_host = None
            self._dwm_host_size = (1, 1)
            raise

    def _repair_dwm_host_owner_and_style(self, hwnd=None):
        """Keep the raw DWM popup owned by the current Tekzite top-level HWND.

        Toggling ``overrideredirect`` for taskbar minimize/restore can change the
        native Tk wrapper relationship on Windows.  If the DWM popup keeps the
        old owner, Windows may treat it as an independent top-level window and
        surface it ahead of Tekzite when the taskbar button is clicked.

        Reassert both ownership and the non-activating tool-window style.  This
        operation never focuses or raises the DWM popup.
        """
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
            hwnd_i = int(hwnd or self._dwm_host or 0)
            if not hwnd_i or not user32.IsWindow(wintypes.HWND(hwnd_i)):
                return False

            self.root.update_idletasks()
            inner = int(self.root.winfo_id())
            GA_ROOT = 2
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            owner = int(user32.GetAncestor(wintypes.HWND(inner), GA_ROOT) or inner)
            if not owner:
                return False

            GWLP_HWNDPARENT = -8
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_LAYERED = 0x00080000
            WS_EX_NOACTIVATE = 0x08000000
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long

            user32.SetWindowLongPtrW(
                wintypes.HWND(hwnd_i), GWLP_HWNDPARENT, ctypes.c_ssize_t(owner)
            )
            exstyle = int(user32.GetWindowLongW(wintypes.HWND(hwnd_i), GWL_EXSTYLE))
            wanted = (exstyle | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED) & ~WS_EX_APPWINDOW
            if wanted != exstyle:
                user32.SetWindowLongW(wintypes.HWND(hwnd_i), GWL_EXSTYLE, wanted)

            # Commit style/owner changes without activating, moving or changing
            # the z-order of the presentation surface.
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                wintypes.HWND(hwnd_i), wintypes.HWND(0), 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            self._dwm_host_owner_hwnd = owner
            return True
        except Exception:
            return False

    def _destroy_dwm_host_for_taskbar(self):
        """Destroy the transient DWM destination before/after taskbar minimize.

        A DWM thumbnail is bound to a specific destination HWND.  Reusing that
        HWND across Tk's override-redirect -> iconify -> restore transition can
        leave DWM with a numerically valid but visually detached destination.
        v10.5.54 deliberately gives every restore a brand-new destination HWND.
        """
        hwnd_i = int(self._dwm_host or 0)
        if not hwnd_i:
            return False
        destroyed = False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
            hwnd = wintypes.HWND(hwnd_i)
            if user32.IsWindow(hwnd):
                SW_HIDE = 0
                try:
                    user32.ShowWindow(hwnd, SW_HIDE)
                except Exception:
                    pass
                user32.DestroyWindow.argtypes = [wintypes.HWND]
                user32.DestroyWindow.restype = wintypes.BOOL
                destroyed = bool(user32.DestroyWindow(hwnd))
        except Exception:
            destroyed = False
        self._dwm_host = None
        self._dwm_host_owner_hwnd = None
        self._dwm_host_size = (1, 1)
        self._dwm_host_rect = None
        self._dwm_host_region_signature = None
        self._dwm_host_visible = False
        self._dwm_host_alpha = None
        self._dwm_host_wndproc = None
        self._dwm_host_original_wndproc = None
        return destroyed

    def _suspend_dwm_host_for_minimize(self):
        """Retire the DWM destination before Windows iconifies Tekzite."""
        self._dwm_host_suspended_for_minimize = True
        self._cancel_dwm_host_reveal()
        if self._dwm_restore_recovery_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_restore_recovery_after_id)
            except Exception:
                pass
            self._dwm_restore_recovery_after_id = None
        if self._dwm_geometry_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_geometry_after_id)
            except Exception:
                pass
            self._dwm_geometry_after_id = None
        self._dwm_pending_resize = False
        self._dwm_pending_force_resize = False
        self._dwm_pending_input_metrics_refresh = False
        self._destroy_dwm_host_for_taskbar()

    def _restore_dwm_host_after_taskbar(self):
        """Create a new DWM destination and reattach Chromium after restore."""
        try:
            if str(self.root.state()) == "iconic":
                return False
        except Exception:
            return False

        self._apply_frameless_app_style()
        if not (self._embedded_mode and self._chromium_dwm_mode):
            self._dwm_host_suspended_for_minimize = False
            return True

        self._dwm_host_suspended_for_minimize = True
        self._dwm_reveal_pending = False
        self._dwm_restore_recovery_success = None
        if self._dwm_restore_recovery_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_restore_recovery_after_id)
            except Exception:
                pass
        try:
            # Give Tk one layout beat to finish restoring its native wrapper.
            self._dwm_restore_recovery_after_id = self.root.after(
                55, self._recover_dwm_host_after_taskbar, 1
            )
        except Exception:
            self._dwm_restore_recovery_after_id = None
            return False
        return True

    def _recover_dwm_host_after_taskbar(self, attempt=1):
        """Attach the live Chromium session to a fresh DWM destination HWND."""
        self._dwm_restore_recovery_after_id = None
        try:
            if str(self.root.state()) == "iconic":
                self._dwm_restore_recovery_after_id = self.root.after(
                    90, self._recover_dwm_host_after_taskbar, attempt
                )
                return False
        except Exception:
            return False

        if not (self._embedded_mode and self._chromium_dwm_mode):
            self._dwm_host_suspended_for_minimize = False
            return False

        ok = False
        try:
            self.root.update_idletasks()
            # A failed previous attempt must not poison the next one.
            if self._dwm_host:
                self._destroy_dwm_host_for_taskbar()

            host = int(self._ensure_dwm_host())
            self._repair_dwm_host_owner_and_style(host)
            self._dwm_surface_ready = False
            host_size = self._sync_dwm_host_geometry(show=False, transparent=True)
            if host_size is None:
                host_size = (
                    max(1, int(self.content_frame.winfo_width())),
                    max(1, int(self.content_frame.winfo_height())),
                )
            w, h = max(1, int(host_size[0])), max(1, int(host_size[1]))

            # attach_embedded_chromium updates engine.session['embedded_parent']
            # to this new HWND, primes Chromium's DComp source, and registers a
            # thumbnail against the new destination before anything is shown.
            request_embedded_chromium_dwm_reregister()
            attach_embedded_chromium(host, w, h)
            self._dwm_last_chromium_viewport = (w, h)
            self._dwm_surface_ready = True
            self._dwm_host_suspended_for_minimize = False
            self._dwm_reveal_pending = True
            # Re-arm the proven keyboard/input lane before this new destination
            # is ever made visible, matching the normal startup reveal contract.
            self._arm_dwm_input_surface()
            self._sync_dwm_host_geometry(show=True, transparent=True)
            self._schedule_dwm_host_reveal(delay=65)
            ok = True
        except Exception:
            self._dwm_surface_ready = False
            self._dwm_host_suspended_for_minimize = True
            self._destroy_dwm_host_for_taskbar()
            ok = False

        self._dwm_restore_recovery_count += 1
        self._dwm_restore_recovery_success = bool(ok)
        if not ok:
            if int(attempt) < 4:
                try:
                    delay = 95 + (int(attempt) * 65)
                    self._dwm_restore_recovery_after_id = self.root.after(
                        delay, self._recover_dwm_host_after_taskbar, int(attempt) + 1
                    )
                except Exception:
                    self._dwm_restore_recovery_after_id = None
            return False

        # Confirm exact geometry again after Tk/DWM have both consumed the new
        # destination. These are resize-only and never re-use the old HWND.
        try:
            self.root.after(120, lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))
            self.root.after(280, lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))
        except Exception:
            pass
        self._schedule_dwm_pointer_bridge(delay=1)
        return True

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
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
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
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                SWP_NOOWNERZORDER = 0x0200
                SWP_NOZORDER = 0x0004
                flags = SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOZORDER
                old_rect = self._dwm_host_rect
                same_size = bool(old_rect and tuple(old_rect[2:]) == (w, h))
                if same_size:
                    flags |= SWP_NOSIZE
                    user32.SetWindowPos(
                        wintypes.HWND(hwnd), wintypes.HWND(0), x, y, 0, 0, flags,
                    )
                else:
                    user32.SetWindowPos(
                        wintypes.HWND(hwnd), wintypes.HWND(0), x, y, w, h, flags,
                    )
                self._dwm_host_rect = rect
            self._dwm_host_size = (w, h)
            self._apply_dwm_host_rounding(hwnd, w, h)

            LWA_ALPHA = 0x00000002
            target_alpha = 0 if transparent else 255
            if target_alpha != self._dwm_host_alpha:
                try:
                    user32.SetLayeredWindowAttributes.argtypes = [
                        wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD
                    ]
                    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
                    user32.SetLayeredWindowAttributes(
                        wintypes.HWND(hwnd), wintypes.COLORREF(0), ctypes.c_ubyte(target_alpha), LWA_ALPHA,
                    )
                    self._dwm_host_alpha = int(target_alpha)
                except Exception:
                    pass

            # Startup/restore rule: the raw DWM destination remains completely
            # hidden until Chromium is ready, and it must never be remapped while
            # Tekzite itself is iconic.  A queued geometry callback can otherwise
            # resurrect this separate popup after the real taskbar window hides.
            root_iconic = False
            try:
                root_iconic = str(self.root.state()) == "iconic"
            except Exception:
                pass
            should_show = bool(
                show and self._dwm_surface_ready
                and not self._dwm_host_suspended_for_minimize
                and not root_iconic
            )
            if should_show and not self._dwm_host_visible:
                SW_SHOWNOACTIVATE = 4
                user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                self._dwm_host_visible = True
            elif not should_show and self._dwm_host_visible:
                SW_HIDE = 0
                try:
                    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
                    user32.ShowWindowAsync.restype = wintypes.BOOL
                    user32.ShowWindowAsync(wintypes.HWND(hwnd), SW_HIDE)
                except Exception:
                    user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
                self._dwm_host_visible = False
            return (w, h)
        except Exception:
            return None

    def _cancel_dwm_host_reveal(self):
        if self._dwm_reveal_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_reveal_after_id)
            except Exception:
                pass
            self._dwm_reveal_after_id = None

    def _reveal_dwm_host(self):
        self._dwm_reveal_after_id = None
        if not (self._embedded_mode and self._chromium_dwm_mode and self._dwm_surface_ready):
            self._dwm_reveal_pending = False
            return False
        self._dwm_reveal_pending = False
        self._sync_dwm_host_geometry(show=True, transparent=False)
        return True

    def _schedule_dwm_host_reveal(self, delay=45):
        self._cancel_dwm_host_reveal()
        try:
            self._dwm_reveal_after_id = self.root.after(max(1, int(delay)), self._reveal_dwm_host)
        except Exception:
            self._dwm_reveal_after_id = None

    def _schedule_dwm_geometry_sync(self, resize=False, delay=8, *, force_resize=False, refresh_input_metrics=False):
        """Coalesce DWM geometry near a 120 Hz cadence without resize spam.

        ``force_resize`` is reserved for viewport transitions that need a real
        Chromium/DWM recrop even when the final width/height equals the cached
        viewport. ``refresh_input_metrics`` runs only after that geometry work
        has completed, so pointer scaling can never sample the pre-resize host.
        """
        if not self._embedded_mode or not self._chromium_dwm_mode:
            return
        self._dwm_pending_resize = bool(self._dwm_pending_resize or resize)
        self._dwm_pending_force_resize = bool(self._dwm_pending_force_resize or force_resize)
        self._dwm_pending_input_metrics_refresh = bool(
            self._dwm_pending_input_metrics_refresh or refresh_input_metrics
        )
        if self._dwm_geometry_after_id is not None:
            return

        def _flush():
            self._dwm_geometry_after_id = None
            do_resize = bool(self._dwm_pending_resize)
            force_now = bool(self._dwm_pending_force_resize)
            refresh_metrics_now = bool(self._dwm_pending_input_metrics_refresh)
            self._dwm_pending_resize = False
            self._dwm_pending_force_resize = False
            self._dwm_pending_input_metrics_refresh = False
            # v10.5.38: the DWM popup rectangle is the authoritative visible
            # viewport.  During maximize/restore Tk can resize content_frame one
            # layout pass before edge_host, so reading edge_host here could keep
            # the DWM thumbnail at the old size while its destination HWND had
            # already grown, exposing a large white remainder.  Resize Chromium
            # from the exact host rectangle we just committed instead.
            host_size = self._sync_dwm_host_geometry(
                show=True, transparent=bool(self._dwm_reveal_pending)
            )
            if do_resize:
                try:
                    if host_size is not None:
                        w, h = map(int, host_size)
                    else:
                        w = max(1, int(self.content_frame.winfo_width()))
                        h = max(1, int(self.content_frame.winfo_height()))
                    viewport = (max(1, w), max(1, h))
                    if force_now or viewport != self._dwm_last_chromium_viewport:
                        resize_embedded_chromium(*viewport)
                        self._dwm_last_chromium_viewport = viewport
                except Exception:
                    pass
            if refresh_metrics_now:
                try:
                    tab = self._active_tab()
                    target_id = tab.get("chromium_target_id") if tab else self._chromium_frame_target_id
                    self._executor.submit(
                        refresh_embedded_chromium_dwm_input_metrics,
                        target_id,
                        0.8,
                    )
                except Exception:
                    pass

        try:
            # v9.7: while the user is dragging the top-level window, 60 Hz is
            # plenty for DWM destination tracking and avoids feeding the
            # compositor a 120 Hz stream on top of Tk's own move traffic. The
            # final drag release performs an immediate exact sync.
            effective_delay = max(16 if self._window_drag_active else 1, int(delay))
            self._dwm_geometry_after_id = self.root.after(effective_delay, _flush)
        except Exception:
            self._dwm_geometry_after_id = None

    def _hide_dwm_host(self):
        self._cancel_dwm_host_reveal()
        if self._dwm_pointer_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_pointer_after_id)
            except Exception:
                pass
            self._dwm_pointer_after_id = None
        self._dwm_pointer_inside = False
        self._dwm_pointer_last_screen_xy = None
        self._dwm_pointer_last_page_xy = None
        self._chromium_left_button_down = False
        self._chromium_drag_selecting = False
        self._chromium_press_point = None
        self._chromium_pending_drag = None
        if self._chromium_drag_after_id is not None:
            try:
                self.root.after_cancel(self._chromium_drag_after_id)
            except Exception:
                pass
            self._chromium_drag_after_id = None
        self._chromium_dwm_mode = False
        self._dwm_surface_ready = False
        self._dwm_reveal_pending = False
        self._dwm_host_visible = False
        if self._dwm_geometry_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_geometry_after_id)
            except Exception:
                pass
            self._dwm_geometry_after_id = None
        self._dwm_pending_resize = False
        self._dwm_pending_force_resize = False
        self._dwm_pending_input_metrics_refresh = False
        if os.name != "nt" or not self._dwm_host:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32
            SW_HIDE = 0
            hwnd = wintypes.HWND(int(self._dwm_host))
            # ShowWindow can synchronously wait on the native window/compositor
            # path. For tab-close/new-tab transitions we only need to enqueue a
            # hide, so prefer ShowWindowAsync and return to Tk immediately.
            try:
                user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.ShowWindowAsync.restype = wintypes.BOOL
                user32.ShowWindowAsync(hwnd, SW_HIDE)
            except Exception:
                user32.ShowWindow(hwnd, SW_HIDE)
        except Exception:
            pass

    def _set_chromium_presentation_fast(self, mode, target_id=None):
        """Change presentation state without ever waiting on CDP from Tk.

        The old path could spend seconds clearing Chromium device metrics on the
        GUI thread just after an active tab closed. That made the whole Tekzite
        window stop processing clicks even though target activation itself was
        already on a worker. Mark the live session immediately, then do the CDP
        housekeeping on the shared Chromium executor.
        """
        normalized = "software" if str(mode).lower() == "software" else "native"
        try:
            set_embedded_chromium_presentation(normalized, target_id, defer_io=True)
        except Exception:
            pass
        if normalized == "native":
            executor = getattr(self, "_executor", None)
            if executor is not None:
                try:
                    executor.submit(set_embedded_chromium_presentation, normalized, target_id, False)
                except Exception:
                    pass
        return normalized

    def _show_native_canvas(self):
        if not self._embedded_mode and not self._chromium_software_mode:
            return
        self._embedded_mode = False
        self._chromium_software_mode = False
        self._hide_dwm_host()
        self._chromium_frame_target_id = None
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
        # Linux Preview intentionally uses the existing CDP software compositor
        # as its primary renderer. Chromium itself runs headless, so this works
        # under X11, XWayland and native Wayland without unsafe cross-process
        # window reparenting. Windows keeps the user-selectable DWM/software path.
        if os.name != "nt":
            return True
        mode = str(getattr(self, "preferences", DEFAULT_PREFERENCES).get(
            "chromium_presentation", "native"
        )).strip().lower()
        return mode == "software"

    def _show_chromium_software_surface(self, target_id=None):
        self._hide_dwm_host()
        self._set_chromium_presentation_fast("software", target_id)
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
        """Return the stable software viewport, never a transient Tk size.

        Also repair a missed Tk <Configure> notification. On Linux a late shell
        repack can leave the latched Chromium bitmap shorter than the actual
        Canvas, exposing the Canvas background as a black strip at the bottom.
        Keep rendering the last committed size until the real widget size has
        remained stable long enough to commit it.
        """
        size = self._chromium_viewport_size
        w = max(1, int(self.chromium_surface.winfo_width()))
        h = max(1, int(self.chromium_surface.winfo_height()))
        actual = (w, h)
        if size and self._chromium_viewport_is_sane(*size):
            committed = (int(size[0]), int(size[1]))
            if self._chromium_viewport_is_sane(*actual) and actual != committed:
                self._chromium_pending_viewport_size = actual
                if self._chromium_viewport_after_id is None:
                    try:
                        self._chromium_viewport_after_id = self.root.after(
                            min(120, int(self._chromium_viewport_debounce_ms)),
                            self._commit_chromium_software_viewport,
                        )
                    except Exception:
                        self._chromium_viewport_after_id = None
            return committed
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
        if target_id:
            try:
                self._executor.submit(warm_embedded_chromium_io_channels, target_id, 1.5)
            except Exception:
                pass
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
            self._set_chromium_presentation_fast("native", target_id)
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
                self._set_chromium_presentation_fast("software", target_id)
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

    def _dwm_local_to_chromium_xy(self, x, y):
        """Map a point in the visible DWM destination to Chromium page CSS pixels.

        Both Tk events and the v10.5.4 native pointer watchdog use this exact
        transform.  Keeping one mapping function prevents the visual DWM crop,
        browser zoom and pointer hit testing from drifting into different
        coordinate systems.
        """
        x = max(0.0, float(x))
        y = max(0.0, float(y))
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

            # v10.5.6: DWM/Win32 positions are native window pixels; CDP
            # pointer APIs use CSS viewport pixels.  The live scale includes
            # Windows DPI/device scaling *and* Chromium page zoom.  Using only
            # the saved zoom percentage caused the exact "click above the
            # input" symptom on scaled displays.
            scale_x, scale_y = get_embedded_chromium_input_scale()
            scale_x = float(scale_x or 1.0)
            scale_y = float(scale_y or 1.0)
            if scale_x > 0.0 and abs(scale_x - 1.0) > 1e-6:
                x /= scale_x
            if scale_y > 0.0 and abs(scale_y - 1.0) > 1e-6:
                y /= scale_y
        except Exception:
            pass
        return x, y

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
            return self._dwm_local_to_chromium_xy(x, y)
        src = self._chromium_frame_source_size
        dst = self._chromium_frame_display_size
        if src and dst and dst[0] > 0 and dst[1] > 0:
            x *= float(src[0]) / float(dst[0])
            y *= float(src[1]) / float(dst[1])
            # A software screenshot is in device pixels but CDP input is in
            # CSS pixels. Browser zoom changes that ratio, so divide by the
            # live contract scale before dispatching clicks/hover/wheel.
            scale_x, scale_y = get_embedded_chromium_software_input_scale()
            scale_x = max(0.01, float(scale_x or 1.0))
            scale_y = max(0.01, float(scale_y or 1.0))
            x /= scale_x
            y /= scale_y
            css_w = float(src[0]) / scale_x
            css_h = float(src[1]) / scale_y
            # Keep the point inside Chromium's CSS viewport. elementFromPoint()
            # and Input.dispatchMouseEvent behave better at width-1/height-1
            # than exactly on the exclusive lower/right edge.
            x = min(x, max(0.0, css_w - 1.0))
            y = min(y, max(0.0, css_h - 1.0))
        return x, y

    def _note_dwm_tk_pointer_delivery(self, x=None, y=None):
        """Remember a DWM pointer point that Windows successfully delivered to Tk."""
        if self._chromium_dwm_mode:
            self._dwm_tk_pointer_event_at = time.monotonic()
            if x is not None and y is not None:
                self._dwm_pointer_last_page_xy = (round(float(x), 3), round(float(y), 3))

    def _queue_chromium_hover_xy(self, x, y):
        """Coalesce a page-space hover point onto Chromium's dedicated hover lane."""
        self._chromium_pending_motion = (float(x), float(y))
        self._mark_chromium_interaction(0.45)
        if self._chromium_motion_after_id is None:
            self._chromium_motion_after_id = self.root.after(
                self._chromium_motion_interval_ms, self._flush_chromium_surface_motion
            )

    def _dispatch_chromium_press_xy(self, x, y):
        """Send one left press in already-mapped Chromium page coordinates."""
        if not self._chromium_input_surface_active():
            return None
        # State matching also de-duplicates the native DWM fallback if the same
        # physical press reaches Tk a moment later.
        if self._chromium_left_button_down:
            return "break"
        self._address_focus_active = False
        self._chromium_page_keyboard_active = True
        try:
            if self._chromium_dwm_mode:
                # v10.5.46: the sink is created only as a consequence of this
                # real user click. Nothing native is added to the bootstrap path.
                if not self._focus_dwm_keyboard_sink():
                    self.root.focus_force()
                    self.edge_host.focus_set()
                self._schedule_dwm_keyboard_poll(0)
            else:
                # Linux's frameless root and Settings are both override-redirect
                # windows. focus_set() only changes Tk's internal focus chain and
                # can leave X11/XWayland keyboard ownership on the Settings
                # toplevel. Reclaim the real application focus on every page
                # click before routing keys to Chromium.
                if sys.platform.startswith("linux"):
                    self.root.focus_force()
                    self.chromium_surface.focus_force()
                    try:
                        self.root.tk.call("focus", "-force", self.chromium_surface._w)
                    except Exception:
                        pass
                else:
                    self.chromium_surface.focus_set()
        except Exception:
            pass
        self._cancel_embedded_surface_wakes()
        self._mark_chromium_interaction(1.0)
        x, y = float(x), float(y)
        self._chromium_left_button_down = True
        self._chromium_drag_selecting = False
        self._chromium_press_point = (x, y)
        self._chromium_press_click_count = _next_pointer_click_count(
            self._chromium_last_click_release_at,
            self._chromium_last_click_point,
            self._chromium_last_click_count,
            time.monotonic(),
            (x, y),
        )
        # Move first on the same ordered input worker. Sites that reveal or
        # arm controls on hover therefore see the pointer at the exact pixel
        # before the button transition arrives. mouseMoved deliberately uses
        # clickCount=0; only actual button transitions carry click semantics.
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseMoved", x, y,
            button="none", buttons=0, click_count=0,
            target_id=self._chromium_frame_target_id,
        )
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mousePressed", x, y,
            button="left", buttons=1, click_count=self._chromium_press_click_count,
            target_id=self._chromium_frame_target_id,
        )
        if self._chromium_dwm_mode:
            # v10.5.43: DWM is only a visual mirror, so there is no native
            # Chromium HWND beneath the pointer to establish edit focus for us.
            # Queue an explicit point-focus on the same ordered CDP input lane
            # immediately after mousePressed. If the point is an input/textarea/
            # contenteditable this guarantees Input.insertText has a real target.
            # Because keyboard packets share this executor, fast typing cannot
            # overtake the focus operation.
            self._submit_chromium_input(
                focus_embedded_chromium_point, x, y,
                target_id=self._chromium_frame_target_id, timeout=2,
            )
        return "break"

    def _flush_pending_chromium_drag_before_release(self):
        """Queue the newest drag point before its release on the ordered lane."""
        if self._chromium_drag_after_id is not None:
            try:
                self.root.after_cancel(self._chromium_drag_after_id)
            except Exception:
                pass
            self._chromium_drag_after_id = None
        pending = self._chromium_pending_drag
        self._chromium_pending_drag = None
        if pending is None:
            return
        x, y = map(float, pending)
        self._chromium_drag_future = self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseMoved", x, y,
            button="left", buttons=1, click_count=0,
            target_id=self._chromium_frame_target_id,
        )

    def _dispatch_chromium_release_xy(self, x, y):
        """Send one left release in already-mapped Chromium page coordinates."""
        if not self._chromium_input_surface_active():
            return None
        if not self._chromium_left_button_down:
            return "break"
        self._mark_chromium_interaction(1.0)
        x, y = float(x), float(y)
        # A coalesced drag may still have one newest point waiting in Tk. Queue
        # that move first; the single-threaded input executor guarantees the
        # subsequent mouseReleased cannot overtake it.
        self._flush_pending_chromium_drag_before_release()
        click_count = max(1, int(self._chromium_press_click_count or 1))
        was_drag = bool(self._chromium_drag_selecting)
        self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseReleased", x, y,
            button="left", buttons=0, click_count=click_count,
            target_id=self._chromium_frame_target_id, refresh=True,
        )
        self._chromium_left_button_down = False
        self._chromium_drag_selecting = False
        self._chromium_press_point = None
        if was_drag:
            # A selection/slider drag must not become click #1 of a later
            # accidental double-click sequence.
            self._chromium_last_click_release_at = 0.0
            self._chromium_last_click_point = None
            self._chromium_last_click_count = 0
        else:
            self._chromium_last_click_release_at = time.monotonic()
            self._chromium_last_click_point = (x, y)
            self._chromium_last_click_count = click_count
        self._chromium_press_click_count = 1
        return "break"

    def _dispatch_chromium_drag_xy(self, x, y):
        """Coalesce a held-left pointer drag while preserving final ordering."""
        if not self._chromium_input_surface_active() or not self._chromium_left_button_down:
            return None
        x, y = float(x), float(y)
        start = self._chromium_press_point
        if start is not None:
            dx = x - float(start[0])
            dy = y - float(start[1])
            if (dx * dx + dy * dy) >= 4.0:
                self._chromium_drag_selecting = True
        self._mark_chromium_interaction(0.6)
        self._chromium_pending_drag = (x, y)
        if self._chromium_drag_after_id is None:
            try:
                self._chromium_drag_after_id = self.root.after(4, self._flush_chromium_drag_motion)
            except Exception:
                self._chromium_drag_after_id = None
                self._flush_chromium_drag_motion()
        self._chromium_cursor_point = (x, y)
        return "break"

    def _flush_chromium_drag_motion(self):
        """Keep only the newest held-left move while Chromium is consuming one."""
        self._chromium_drag_after_id = None
        if not self._chromium_input_surface_active() or not self._chromium_left_button_down:
            self._chromium_pending_drag = None
            return
        if self._chromium_drag_future is not None and not self._chromium_drag_future.done():
            self._chromium_drag_after_id = self.root.after(4, self._flush_chromium_drag_motion)
            return
        pending = self._chromium_pending_drag
        self._chromium_pending_drag = None
        if pending is None:
            return
        x, y = map(float, pending)
        self._chromium_drag_future = self._submit_chromium_input(
            dispatch_embedded_chromium_mouse, "mouseMoved", x, y,
            button="left", buttons=1, click_count=0,
            target_id=self._chromium_frame_target_id,
        )
        if self._chromium_pending_drag is not None and self._chromium_drag_after_id is None:
            self._chromium_drag_after_id = self.root.after(4, self._flush_chromium_drag_motion)

    def _schedule_dwm_pointer_bridge(self, delay=8):
        """Arm the Windows pointer fallback for the visible DWM destination."""
        if os.name != "nt" or not (self._embedded_mode and self._chromium_dwm_mode and self._dwm_surface_ready):
            return False
        if self._dwm_pointer_after_id is not None:
            return True
        try:
            self._dwm_pointer_after_id = self.root.after(max(1, int(delay)), self._poll_dwm_pointer_bridge)
            return True
        except Exception:
            self._dwm_pointer_after_id = None
            return False

    def _poll_dwm_pointer_bridge(self):
        """Repair any DWM pointer event Windows failed to pass through to Tk.

        ``WM_NCHITTEST -> HTTRANSPARENT`` remains the normal zero-overhead input
        route.  This poller only emits hover packets when Tk has gone quiet, and
        only emits button transitions when Tekzite's tracked state disagrees
        with the physical left button.  That makes it a fallback rather than a
        second competing input source.
        """
        self._dwm_pointer_after_id = None
        if getattr(self, "_closing", False):
            return
        if not (os.name == "nt" and self._embedded_mode and self._chromium_dwm_mode
                and self._dwm_surface_ready and self._dwm_host_visible and self._dwm_host):
            return
        next_delay = 24
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._dwm_user32 or ctypes.WinDLL("user32", use_last_error=True)
            self._dwm_user32 = user32

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short

            pt = POINT()
            if not user32.GetCursorPos(ctypes.byref(pt)):
                raise OSError(ctypes.get_last_error(), "GetCursorPos failed")
            sx, sy = int(pt.x), int(pt.y)
            rect = self._dwm_host_rect
            if not rect:
                raise RuntimeError("DWM host geometry unavailable")
            rx, ry, rw, rh = map(int, rect)
            rw, rh = max(1, rw), max(1, rh)
            inside = (rx <= sx < rx + rw and ry <= sy < ry + rh)
            physical_left_down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)

            # Continue tracking a drag that started inside even if the pointer
            # leaves the viewport, so Chromium always receives the matching
            # mouseReleased transition.  Coordinates clamp to the visible edge.
            tracking = bool(inside or self._chromium_left_button_down)
            if tracking:
                lx = min(max(float(sx - rx), 0.0), float(rw - 1))
                ly = min(max(float(sy - ry), 0.0), float(rh - 1))
                x, y = self._dwm_local_to_chromium_xy(lx, ly)
                transitioned = False

                page_point = (round(float(x), 3), round(float(y), 3))
                if physical_left_down and not self._chromium_left_button_down and inside:
                    self._dispatch_chromium_press_xy(x, y)
                    self._dwm_pointer_last_page_xy = page_point
                    transitioned = True
                elif (not physical_left_down) and self._chromium_left_button_down:
                    self._dispatch_chromium_release_xy(x, y)
                    self._dwm_pointer_last_page_xy = page_point
                    transitioned = True

                point_changed = self._dwm_pointer_last_page_xy != page_point
                tk_quiet_for = time.monotonic() - float(self._dwm_tk_pointer_event_at or 0.0)
                if point_changed and not transitioned and tk_quiet_for >= 0.018:
                    if physical_left_down and self._chromium_left_button_down:
                        self._dispatch_chromium_drag_xy(x, y)
                        self._dwm_pointer_last_page_xy = page_point
                    elif inside:
                        self._queue_chromium_hover_xy(x, y)
                        self._dwm_pointer_last_page_xy = page_point

                self._dwm_pointer_last_screen_xy = (sx, sy)
                next_delay = 8
            else:
                self._dwm_pointer_last_screen_xy = (sx, sy)
                self._dwm_pointer_last_page_xy = None

            if self._dwm_pointer_inside and not inside and not self._chromium_left_button_down:
                self._chromium_cursor_point = None
                self._apply_chromium_cursor("default")
            self._dwm_pointer_inside = bool(inside)
        except Exception:
            # Pointer fallback is intentionally non-fatal. Tk's regular input
            # plane remains active even if a Win32 probe is unavailable.
            next_delay = 32
        finally:
            self._schedule_dwm_pointer_bridge(delay=next_delay)

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
        x, y = self._surface_xy(event)
        self._note_dwm_tk_pointer_delivery(x, y)
        return self._dispatch_chromium_press_xy(x, y)

    def _on_chromium_surface_release(self, event):
        # mouseReleased is emitted by _dispatch_chromium_release_xy; keeping the
        # actual CDP packet in the shared helper also de-duplicates the DWM
        # native fallback against ordinary Tk delivery.
        if not self._chromium_input_surface_active():
            return None
        x, y = self._surface_xy(event)
        self._note_dwm_tk_pointer_delivery(x, y)
        return self._dispatch_chromium_release_xy(x, y)

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
        self._note_dwm_tk_pointer_delivery(x, y)
        return self._dispatch_chromium_drag_xy(x, y)

    def _on_chromium_surface_motion(self, event):
        if not self._chromium_input_surface_active():
            return None
        x, y = self._surface_xy(event)
        self._note_dwm_tk_pointer_delivery(x, y)
        self._queue_chromium_hover_xy(x, y)
        return None

    def _flush_chromium_surface_motion(self):
        self._chromium_motion_after_id = None
        if not self._chromium_input_surface_active():
            self._chromium_pending_motion = None
            self._chromium_motion_future = None
            return
        # Keep at most one hover packet in flight. If Chromium is busy, retain
        # only the newest coordinates instead of building a stale motion queue.
        if self._chromium_motion_future is not None and not self._chromium_motion_future.done():
            self._chromium_motion_after_id = self.root.after(
                self._chromium_motion_interval_ms, self._flush_chromium_surface_motion
            )
            return
        motion = self._chromium_pending_motion
        self._chromium_pending_motion = None
        if motion is None:
            self._chromium_motion_future = None
            return
        x, y = motion
        try:
            self._chromium_motion_future = self._chromium_hover_executor.submit(
                dispatch_embedded_chromium_mouse, "mouseMoved", x, y,
                target_id=self._chromium_frame_target_id, purpose="hover"
            )
        except Exception:
            self._chromium_motion_future = None
        self._chromium_cursor_point = (x, y)
        self._request_chromium_cursor_probe()
        if self._chromium_pending_motion is not None:
            self._chromium_motion_after_id = self.root.after(
                self._chromium_motion_interval_ms, self._flush_chromium_surface_motion
            )

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
            self._chromium_cursor_future = self._chromium_cursor_executor.submit(
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

    def _on_chromium_surface_linux_wheel(self, event):
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

    def _on_chromium_surface_wheel(self, event):
        if not self._chromium_input_surface_active():
            return None
        self._mark_chromium_interaction(1.0)
        x, y = self._surface_xy(event)
        self._note_dwm_tk_pointer_delivery(x, y)
        delta = -float(getattr(event, "delta", 0) or 0)
        state = int(getattr(event, "state", 0) or 0)
        shift = bool(state & 0x0001)
        control = bool(state & 0x0004)
        alt = bool(state & 0x0008)
        modifiers = (8 if shift else 0) | (2 if control else 0) | (1 if alt else 0)
        # Shift+wheel is horizontal scrolling in Chromium. Keep the axis and
        # modifier state all the way through CDP so nested scrollers behave as
        # they do in a normal browser.
        dx, dy = (delta, 0.0) if shift else (0.0, delta)
        # v8.7/v10.5.7: keep wheel bursts out of the click/keyboard FIFO and
        # coalesce both axes while one scroll packet is in flight.
        if self._chromium_pending_wheel is None:
            self._chromium_pending_wheel = [x, y, 0.0, 0.0, modifiers]
        self._chromium_pending_wheel[0] = x
        self._chromium_pending_wheel[1] = y
        self._chromium_pending_wheel[2] += dx
        self._chromium_pending_wheel[3] += dy
        self._chromium_pending_wheel[4] = modifiers
        if self._chromium_wheel_after_id is None:
            self._chromium_wheel_after_id = self.root.after(1, self._flush_chromium_wheel)
        return "break"


    def _flush_chromium_wheel(self):
        self._chromium_wheel_after_id = None
        if not self._chromium_input_surface_active():
            self._chromium_pending_wheel = None
            return
        if self._chromium_scroll_future is not None and not self._chromium_scroll_future.done():
            self._chromium_wheel_after_id = self.root.after(2, self._flush_chromium_wheel)
            return
        pending = self._chromium_pending_wheel
        self._chromium_pending_wheel = None
        if not pending:
            return
        x, y, delta_x, delta_y, modifiers = pending
        try:
            self._chromium_scroll_future = self._chromium_scroll_executor.submit(
                dispatch_embedded_chromium_mouse, "mouseWheel", x, y,
                delta_x=delta_x, delta_y=delta_y, modifiers=modifiers,
                target_id=self._chromium_frame_target_id,
                timeout=2, purpose="scroll",
            )
        except Exception:
            self._chromium_scroll_future = None
        if self._chromium_pending_wheel is not None and self._chromium_wheel_after_id is None:
            self._chromium_wheel_after_id = self.root.after(1, self._flush_chromium_wheel)


    def _on_root_chromium_key(self, event):
        """Fallback keyboard lane for DWM presentation.

        Tk can leave focus on the toplevel after a click through the transparent
        DWM host. When the last pointer click belonged to the page, keep routing
        keys to Chromium unless Tekzite's address bar is actively editing.
        """
        if not (self._chromium_dwm_mode and self._chromium_page_keyboard_active):
            return None
        if getattr(self, "_dwm_keyboard_poll_active", False):
            return "break"
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

        if state & 0x0004 and keysym.lower() == "j":
            return self._show_downloads()
        if state & 0x0004 and keysym.lower() == "h":
            return self._show_history()
        if state & 0x0004 and keysym.lower() == "d":
            return self._bookmark_current_page()
        if state & 0x0004 and state & 0x0001 and keysym.lower() == "o":
            return self._show_bookmarks()

        # Tk modifier masks -> CDP Input modifier bits.
        shift = bool(state & 0x0001)
        control = bool(state & 0x0004)
        alt = bool(state & 0x0008)
        modifiers = (8 if shift else 0) | (2 if control else 0) | (1 if alt else 0)

        # Ordinary text goes through Input.insertText so IME/layout differences
        # between Tk and Chromium do not corrupt what the user typed. Modified
        # printable keys are dispatched as real key events for Ctrl+C/V/A etc.
        altgr_text = bool(char and char.isprintable() and control and alt)
        if char and char.isprintable() and (not (control or alt) or altgr_text):
            # On many European Windows layouts AltGr is reported by Tk as
            # Ctrl+Alt. Treat an actual printable character as text so @, €,
            # braces and similar layout characters reach Chromium correctly.
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
        menu = self._make_modern_menu(self.root)
        menu.add_command(label=self._menu_item_text("Back", "←"), command=self.go_back)
        menu.add_command(label=self._menu_item_text("Forward", "→"), command=self.go_forward)
        menu.add_command(label=self._menu_item_text("Reload", "↻"), command=self._reload_current)
        menu.add_separator()
        return menu

    def _finish_page_context_menu(self, menu, *, link_url="", selected_text="", image_url="", editable=False):
        link_url = str(link_url or "")
        selected_text = str(selected_text or "")
        image_url = str(image_url or "")
        if link_url:
            menu.insert_command(0, label=self._menu_item_text("Open Link", "↗"), command=lambda u=link_url: self.navigate_to(u))
            menu.insert_command(1, label=self._menu_item_text("Open Link in New Tab", "+"), command=lambda u=link_url: self._new_tab(url=u, switch=True, navigate=True))
            menu.insert_command(2, label=self._menu_item_text("Copy Link Address", "⧉"), command=lambda u=link_url: self._clipboard_set(u))
            menu.insert_separator(3)
        if selected_text:
            menu.add_command(label=self._menu_item_text("Copy Selected Text", "▣"), command=lambda t=selected_text: self._clipboard_set(t))
            query = quote_plus(selected_text[:500])
            menu.add_command(label=self._menu_item_text("Search Selected Text", "⌕"), command=lambda q=query: self._new_tab(url=f"https://www.startpage.com/do/search?q={q}", switch=True, navigate=True))
        if image_url:
            menu.add_command(label=self._menu_item_text("Copy Image Address", "▧"), command=lambda u=image_url: self._clipboard_set(u))
        if selected_text or image_url:
            menu.add_separator()
        if editable:
            menu.add_command(label=self._menu_item_text("Cut", "✂"), command=lambda: self._edit_shortcut("x"))
            menu.add_command(label=self._menu_item_text("Copy", "▣"), command=lambda: self._edit_shortcut("c"))
            menu.add_command(label=self._menu_item_text("Paste", "▤"), command=lambda: self._edit_shortcut("v"))
            menu.add_separator()
        menu.add_command(label=self._menu_item_text("Home", "⌂"), command=self._go_home)
        menu.add_command(label=self._menu_item_text("Copy Page URL", "⧉"), command=lambda: self._clipboard_set(self.url_var.get()))
        menu.add_command(label=self._menu_item_text("Inspect HTML", "</>"), command=self.inspect_html)
        return menu

    def _popup_context_menu(self, menu, event=None):
        try:
            if event is not None and hasattr(event, "x_root") and hasattr(event, "y_root"):
                x_root, y_root = int(event.x_root), int(event.y_root)
            else:
                x_root, y_root = self._screen_cursor_position(None)
            menu.tk_popup(int(x_root), int(y_root))
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

    def _on_chromium_surface_middle_click(self, event):
        """Open links under the DWM pointer without relying on hidden chrome."""
        if not self._chromium_input_surface_active():
            return None
        x, y = self._surface_xy(event)
        self._note_dwm_tk_pointer_delivery(x, y)
        self._mark_chromium_interaction(0.8)
        target_id = self._chromium_frame_target_id
        future = self._executor.submit(
            get_embedded_chromium_context, x, y, target_id=target_id
        )

        def poll():
            if not future.done():
                self.root.after(10, poll)
                return
            try:
                href = str((future.result() or {}).get("href") or "")
            except Exception:
                href = ""
            if href:
                self._new_tab(url=href, switch=False, navigate=True)
                return
            # No link: preserve page-level auxclick/autoscroll semantics.
            self._submit_chromium_input(
                dispatch_embedded_chromium_mouse, "mousePressed", x, y,
                button="middle", buttons=4, click_count=1, target_id=target_id,
            )
            self._submit_chromium_input(
                dispatch_embedded_chromium_mouse, "mouseReleased", x, y,
                button="middle", buttons=0, click_count=1, target_id=target_id, refresh=True,
            )

        self.root.after(0, poll)
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
        self._chromium_page_keyboard_active = True
        # Focus the exact editable under the right click before querying menu
        # state. This makes Cut/Copy/Paste target the field the user actually
        # clicked, even when another input previously owned Chromium focus.
        root_x, root_y = self._screen_cursor_position(event)

        def resolve_context():
            try:
                focus_embedded_chromium_point(x, y, target_id=target_id, timeout=2)
            except Exception:
                pass
            return get_embedded_chromium_context(x, y, target_id=target_id)

        future = self._executor.submit(resolve_context)

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
        self._dwm_keyboard_sink_focused = False
        self._stop_dwm_keyboard_poll()
        self._cancel_embedded_surface_wakes()
        try:
            # A click on the omnibox must reclaim the real native keyboard
            # focus, not only Tk's per-toplevel focus. This matters on Linux
            # after an override-redirect Settings window has owned focus.
            self.root.focus_force()
            self.address.focus_force()
            if sys.platform.startswith("linux"):
                try:
                    self.root.tk.call("focus", "-force", self.address._w)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _on_address_focus_in(self, event=None):
        self._address_focus_active = True
        self._chromium_page_keyboard_active = False
        self._dwm_keyboard_sink_focused = False
        self._stop_dwm_keyboard_poll()
        self._cancel_embedded_surface_wakes()
        self._schedule_omnibox_suggestions(35)

    def _on_address_focus_out(self, event=None):
        self._address_focus_active = False
        try:
            self.root.after(90, self._hide_omnibox_suggestions_if_inactive)
        except Exception:
            self._hide_omnibox_suggestions()

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
        self._hide_omnibox_suggestions()
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
        if sys.platform.startswith("linux"):
            # Linux always presents Chromium through Tekzite's CDP software
            # compositor. Native HWND wake/activation is a Windows workaround
            # and must never run from a Linux background callback.
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
        if sys.platform.startswith("linux"):
            # Never schedule background focus/activation retries on Linux.
            return False
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
                self._set_chromium_presentation_fast("software", target_id)
            except Exception:
                pass
            if not self._chromium_software_mode or self._chromium_frame_target_id != target_id:
                self._show_chromium_software_surface(target_id)
            return False
        self._set_chromium_presentation_fast("native", tab.get("chromium_target_id") if tab else None)
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
        self._cancel_dwm_host_reveal()
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
        # produced a usable frame. Keep the host transparent for one short
        # compositor beat so Tekzite never flashes the raw white DWM surface.
        self._dwm_surface_ready = True
        self._dwm_reveal_pending = True
        # v9.0: arm Tk-to-Chromium keyboard ownership *before* exposing the
        # DWM frame. This removes the final few-instruction window where the
        # page could be visible while the root still owned keyboard input.
        if self._chromium_dwm_mode:
            self._arm_dwm_input_surface()
        self._sync_dwm_host_geometry(show=True, transparent=True)
        self._schedule_dwm_host_reveal(delay=45)
        self.root.after(140, self._reveal_dwm_host)
        # v10.5.4: keep a native pointer fallback armed while the DWM popup is
        # visible.  Normal operation still uses Tk's edge_host bindings; this
        # only fills in a missing move/press/release if Windows fails to pass a
        # hit through the separate top-level thumbnail destination.
        self._schedule_dwm_pointer_bridge(delay=1)
        # v9.2: non-critical I/O lanes warm only after the first frame is visible.
        # This keeps scroll/hover WebSocket setup off the startup reveal path.
        if tab and tab.get("chromium_target_id"):
            try:
                self._executor.submit(
                    warm_embedded_chromium_io_channels,
                    tab.get("chromium_target_id"), 0.8, ("scroll", "hover")
                )
            except Exception:
                pass
        self.root.after_idle(lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))
        try:
            (self.edge_host if self._chromium_dwm_mode else self.chromium_surface).focus_set()
        except Exception:
            pass
        # Keep two guarded retries for Windows activation timing; they no
        # longer establish initial ownership, only repair rare focus churn.
        if self._chromium_dwm_mode:
            for delay in (20, 75):
                try:
                    self.root.after(delay, self._arm_dwm_input_surface)
                except Exception:
                    pass
        return True

    def _arm_dwm_input_surface(self):
        """Mark a visible DWM page ready without creating/focusing the sink.

        v10.5.44 created its raw native keyboard window from this delayed
        bootstrap retry.  That fixed typing but made startup depend on a Python
        Win32 WNDPROC lifetime.  v10.5.46 keeps bootstrap inert: the safe Tk
        sink is created only after the first real page click.
        """
        if not (self._embedded_mode and self._chromium_dwm_mode and self._dwm_surface_ready):
            return False
        try:
            if self._address_focus_active or self.root.focus_get() is self.address:
                return False
        except Exception:
            if self._address_focus_active:
                return False
        self._address_focus_active = False
        self._chromium_page_keyboard_active = True
        return True

    def _on_edge_host_configure(self, event):
        if not self._embedded_mode:
            return
        if self._chromium_dwm_mode:
            # Size changes need a Chromium viewport update, but coalesce the
            # noisy Tk Configure burst into one ~60 Hz operation.
            self._schedule_dwm_geometry_sync(resize=True, delay=8)
            return
        resize_embedded_chromium(
            max(1, int(getattr(event, "width", 1))),
            max(1, int(getattr(event, "height", 1))),
        )

    def _on_root_configure_native_overlay(self, event=None):
        try:
            if getattr(event, "widget", self.root) is not self.root:
                return
            self._apply_window_rounding()
        except Exception:
            pass
        if not self._embedded_mode:
            return
        if self._chromium_software_mode:
            try:
                width = max(1, int(self.chromium_surface.winfo_width()))
                height = max(1, int(self.chromium_surface.winfo_height()))
                candidate = (width, height)
                if (self._chromium_viewport_is_sane(*candidate)
                        and candidate != self._chromium_viewport_size):
                    self._chromium_pending_viewport_size = candidate
                    if self._chromium_viewport_after_id is not None:
                        try:
                            self.root.after_cancel(self._chromium_viewport_after_id)
                        except Exception:
                            pass
                    self._chromium_viewport_after_id = self.root.after(
                        min(120, int(self._chromium_viewport_debounce_ms)),
                        self._commit_chromium_software_viewport,
                    )
            except Exception:
                pass
            return
        try:
            if self._chromium_dwm_mode:
                # v9.8 live dragging moves the top-level HWND and DWM destination
                # together. Do not schedule a second compositor chase from the
                # resulting Tk Configure notification.
                if self._window_drag_active and self._native_drag_dwm_offset is not None:
                    return
                # v10.5.38: distinguish a pure move from a real top-level size
                # change.  Tk emits <Configure> for both.  Moves keep the cheap
                # destination-only path; maximize/restore/snap explicitly request
                # a Chromium/DWM viewport reconciliation.
                root_size = (
                    max(1, int(getattr(event, "width", self.root.winfo_width()))),
                    max(1, int(getattr(event, "height", self.root.winfo_height()))),
                )
                size_changed = root_size != self._dwm_last_root_configure_size
                self._dwm_last_root_configure_size = root_size
                if size_changed:
                    self._schedule_dwm_geometry_sync(resize=True, delay=8)
                else:
                    self._schedule_dwm_geometry_sync(resize=False, delay=8)
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
        """Verify that the *screen-visible* native Chromium surface presents pixels.

        v10.5.68 treats this as a cold/new-target diagnostic, not a hot-navigation
        watchdog.  A page still loading is allowed to pass through flat compositor
        frames without being called stalled, and a completed page must produce two
        consecutive blank samples before the DComp source is diagnosed as stuck.
        """
        if generation != self._navigation_generation or not self._embedded_mode:
            return
        if self._chromium_software_mode or not cdp_visual:
            return
        tab = self._active_tab()
        if tab is None or tab.get("chromium_target_id") != target_id:
            return
        if tab.get("native_surface_probe_generation") != generation:
            tab["native_surface_probe_generation"] = generation
            tab["native_surface_blank_confirmations"] = 0
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
                tab["native_surface_blank_confirmations"] = 0
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

            # A renderer swap is allowed to be flat while the live page is still
            # loading. Do not count those samples toward a DComp-stall diagnosis.
            if bool(tab.get("loading")):
                tab["native_surface_blank_confirmations"] = 0
                if int(attempt) < 6:
                    self.root.after(320, self._probe_visible_embedded_surface,
                                    generation, target_id, cdp_visual, int(attempt) + 1)
                return

            confirmations = int(tab.get("native_surface_blank_confirmations") or 0) + 1
            tab["native_surface_blank_confirmations"] = confirmations
            if confirmations < 2:
                # Passive probation only. In DWM mode the historical wake helper
                # deliberately returns immediately, so pretending to "pulse" it here
                # merely delayed a false-positive diagnosis. Keep source geometry
                # untouched and sample once more after the completed page settles.
                self.root.after(420, self._probe_visible_embedded_surface,
                                generation, target_id, cdp_visual, int(attempt) + 1)
                return

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
            # Do not hammer a persistently stalled top-level DComp surface with
            # repeated resize/geometry-sync/repaint pulses. Keep Native authoritative
            # and leave Chromium's current compositor hierarchy untouched until a
            # genuine user-driven geometry change provides a safe recovery boundary.
            try:
                self._set_chromium_presentation_fast("native", target_id)
            except Exception:
                pass
            self.status_var.set("Chromium Native surface stalled after load; holding DComp geometry stable")
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
            self._set_chromium_presentation_fast("software", target_id)
        except Exception:
            pass
        if not self._chromium_software_mode or self._chromium_frame_target_id != target_id:
            self._show_chromium_software_surface(target_id)
        return True

    def _poll_embedded_navigation(self, generation, future, url, add_history):
        if generation != self._navigation_generation:
            return
        if not future.done():
            self.root.after(8, self._poll_embedded_navigation,
                            generation, future, url, add_history)
            return
        try:
            session = future.result()
            hot_native_reuse = bool(session.get("hot_navigation_reused_native_surface"))
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
            pending_auth_refresh = str(getattr(self, "_google_auth_refresh_pending_url", "") or "")
            if (pending_auth_refresh and
                    self._canonical_tab_url(pending_auth_refresh) == self._canonical_tab_url(url)):
                self._google_auth_refresh_pending_url = None
                try:
                    self.root.after(650, self._refresh_after_google_auth,
                                    generation, session.get("target_id"), url)
                except Exception:
                    pass
            if self._use_chromium_software_surface_for_url(url):
                if tab is not None:
                    tab["presentation"] = "software"
                self._show_chromium_software_surface(session.get("target_id"))
            else:
                if tab is not None:
                    tab["presentation"] = "native"
                    tab.pop("software_fallback_reason", None)
                    tab.pop("native_recovery_viewport", None)
                # v10.5.67: a hot navigation/refresh already owns a healthy,
                # visible DWM destination.  Do not tear that surface down and
                # reveal it again on a fixed timer.  Chromium can replace its
                # renderer one compositor beat after Page.navigate returns;
                # hiding + re-showing the destination in that gap exposed the
                # DComp black backing surface and made refreshes intermittently
                # look dead.  Keep the last good destination continuously
                # mapped and let Chromium paint the new document into it.
                if (hot_native_reuse and self._embedded_mode
                        and self._chromium_dwm_mode and self._dwm_host):
                    self._set_chromium_presentation_fast(
                        "native", tab.get("chromium_target_id") if tab else None
                    )
                    self._chromium_frame_target_id = (
                        tab.get("chromium_target_id") if tab else session.get("target_id")
                    )
                    self._chromium_software_mode = False
                    self._dwm_surface_ready = True
                    self._dwm_reveal_pending = False
                    self._cancel_dwm_host_reveal()
                    self._sync_dwm_host_geometry(show=True, transparent=False)
                    self._schedule_dwm_geometry_sync(resize=True, delay=1)
                else:
                    self._show_embedded_host()
                # v5.42: navigation can rebuild Chromium's presenter/chrome after
                # the first committed frame (notably YouTube and consent shells).
                # Re-measure the DWM crop while that geometry settles so title-bar
                # pixels from the previous site can never leak into the mirror.
                # v10.5.68: hot navigation already owns a healthy live DWM source.
                # Do not hit that source with four eager full-recrops while Chromium
                # is replacing its RenderWidgetHost. Three later samples still meet
                # the crop-stability contract, but avoid the 60/180 ms DComp churn
                # that could itself make Native look stalled.
                recrop_delays = (260, 700, 1250) if hot_native_reuse else (60, 180, 420, 850)
                for delay_index, delay_ms in enumerate(recrop_delays):
                    self.root.after(
                        delay_ms,
                        self._refresh_dwm_crop_after_navigation,
                        generation,
                        delay_index,
                    )
                # v10.5.68: never run the old fixed-220ms visible-surface probe on
                # a hot Native/DWM handoff.  open_embedded_chromium returns the same
                # session dictionary on that path, so its attached-frame diagnostics
                # can describe the *previous* document. Sampling the screen during a
                # renderer swap then produced false "native surface stalled" reports.
                # Cold/new-target paths still get the on-screen safety probe below.
                if not hot_native_reuse:
                    visible_probe_expected = bool(
                        session.get("attached_frame_visual")
                        or int(session.get("attached_frame_text_len") or 0) >= 8
                        or int(session.get("first_frame_text_len") or 0) >= 8
                    )
                    self.root.after(260, self._probe_visible_embedded_surface,
                                    generation, session.get("target_id"),
                                    visible_probe_expected)
            self.root.after(1000, lambda current=session: self._start_optional_services(current))
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
        tab = self._active_tab()
        target_id = tab.get("chromium_target_id") if tab is not None else None
        other_targets_exist = any(
            t.get("chromium_target_id")
            for t in self.tabs
            if tab is None or t.get("id") != tab.get("id")
        )
        create_new_target = bool(tab is not None and not target_id and other_targets_exist)
        software_presentation = self._use_chromium_software_surface_for_url(url)
        # v10.5.67: normal navigation and F5/Ctrl+R on an already attached
        # native target keep the current DWM surface visible while Chromium
        # accepts the new navigation.  The old code unconditionally hid the
        # destination here even though the comment above promised to preserve
        # the current frame.  A subsequent 45 ms timed reveal could race a
        # renderer swap and expose a black frame.  Only cold/new-target paths
        # need the hidden preparation ceremony.
        keep_live_native_surface = bool(
            not software_presentation
            and self._embedded_mode
            and self._chromium_dwm_mode
            and self._dwm_surface_ready
            and self._dwm_host
            and target_id
            and not create_new_target
        )
        self._dwm_reveal_pending = False
        self._cancel_dwm_host_reveal()
        if keep_live_native_surface:
            self._sync_dwm_host_geometry(show=True, transparent=False)
        else:
            if not self._embedded_mode:
                self._dwm_surface_ready = False
            self._sync_dwm_host_geometry(show=False, transparent=False)
        parent_hwnd = int(self._ensure_dwm_host()) if not software_presentation else 0
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
            self._website_color_scheme(),
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
            request_embedded_chromium_dwm_recrop()
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
        """Reflow and repair native DWM ownership after restore/deiconify."""
        if self._taskbar_restore_pending:
            # Mapping is evidence that the Tk wrapper is returning, but the
            # override-redirect remap can still take one more beat. Let the
            # visibility watchdog finish the restore contract.
            try:
                if self._taskbar_restore_watchdog_id is None:
                    self._taskbar_restore_watchdog_id = self.root.after(
                        25, self._ensure_root_visible_after_taskbar, 1
                    )
            except Exception:
                pass
        elif self._dwm_host_suspended_for_minimize:
            try:
                self.root.after_idle(self._restore_dwm_host_after_taskbar)
            except Exception:
                self._restore_dwm_host_after_taskbar()
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
            return self._search_url(value)

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
        return self._search_url(value)


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
        self._refresh_standard_toolbar_state()

    def _apply_window_rounding(self):
        """Request native Windows rounded corners without clipping Tk itself.

        v10.5.14 also used ``SetWindowRgn`` on Tk's wrapper HWND.  On some
        Windows/Tk/DPI combinations that region is interpreted in a different
        native coordinate space than ``winfo_width()/winfo_height()``.  The
        result can punch a large transparent hole through Tekzite's own chrome,
        exposing the desktop while the separate DWM page popup stays visible.

        Keep the modern outer shape through Windows 11's native DWM corner
        preference only.  Maximized/fullscreen windows explicitly request
        square corners.  The Chromium content popup keeps its own independent
        rounded region in ``_apply_dwm_host_rounding``.
        """
        if sys.platform != "win32":
            return False
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
                hwnd = int(user32.GetParent(inner) or int(self.root.winfo_id()))

            rounded = not (self._window_maximized or self._fullscreen)
            radius = self._ui_metric("window_corner_radius", 24) if rounded else 0
            signature = (hwnd, int(radius), bool(rounded))
            if signature == self._window_rounding_signature:
                return True

            # Important: never SetWindowRgn() on the Tk root wrapper here.
            # DWM's native corner preference does not remove any Tk client
            # pixels and therefore cannot make the title/tab/toolbar area
            # transparent on scaled displays.
            try:
                user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
                user32.SetWindowRgn.restype = ctypes.c_int
                user32.SetWindowRgn(wintypes.HWND(hwnd), None, True)
            except Exception:
                pass

            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            DWMWCP_ROUND = 2
            preference = ctypes.c_int(DWMWCP_ROUND if rounded and radius else DWMWCP_DONOTROUND)
            try:
                dwmapi = ctypes.windll.dwmapi
                dwmapi.DwmSetWindowAttribute.argtypes = [
                    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
                ]
                dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
                dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(preference), ctypes.sizeof(preference),
                )
            except Exception:
                pass
            self._window_rounding_signature = signature
            return True
        except Exception:
            return False

    def _apply_dwm_host_rounding(self, hwnd, width, height):
        """Clip the live Chromium DWM mirror to a softly rounded content card."""
        if sys.platform != "win32" or not hwnd:
            return False
        try:
            import ctypes
            from ctypes import wintypes
            radius = 0 if self._fullscreen else self._ui_metric("content_corner_radius", 18)
            signature = (int(hwnd), int(width), int(height), int(radius))
            if signature == self._dwm_host_region_signature:
                return True
            user32 = ctypes.windll.user32
            user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
            user32.SetWindowRgn.restype = ctypes.c_int
            if radius <= 0:
                user32.SetWindowRgn(wintypes.HWND(int(hwnd)), None, True)
            else:
                gdi32 = ctypes.windll.gdi32
                gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
                gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
                diameter = max(2, int(radius) * 2)
                region = gdi32.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1, diameter, diameter)
                if region and not user32.SetWindowRgn(wintypes.HWND(int(hwnd)), region, True):
                    gdi32.DeleteObject(region)
            self._dwm_host_region_signature = signature
            return True
        except Exception:
            return False

    def _apply_frameless_app_style(self):
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

    def _make_window_control(self, parent, role, command, close=False):
        size = max(26, self._ui_metric("app_bar_height", 44) - self._ui_padding(10))
        button = tk.Canvas(
            parent,
            width=size,
            height=size,
            bg=self.ui["bg"],
            highlightthickness=0,
            bd=0,
            relief="flat",
            cursor="hand2",
        )
        button._tekzite_close_control = bool(close)
        button._tekzite_role = str(role)
        button._tekzite_command = command
        button._tekzite_hovered = False
        button._tekzite_pressed = False
        button.bind("<Enter>", lambda event, b=button: self._set_window_control_state(b, hovered=True))
        button.bind("<Leave>", lambda event, b=button: self._set_window_control_state(b, hovered=False, pressed=False))
        button.bind("<ButtonPress-1>", lambda event, b=button: self._set_window_control_state(b, hovered=True, pressed=True))
        button.bind("<ButtonRelease-1>", lambda event, b=button: self._invoke_window_control(b, event))
        self._redraw_window_control(button)
        return button

    def _set_window_control_state(self, button, hovered=None, pressed=None):
        if hovered is not None:
            button._tekzite_hovered = bool(hovered)
        if pressed is not None:
            button._tekzite_pressed = bool(pressed)
        self._redraw_window_control(button)

    def _invoke_window_control(self, button, event=None):
        button._tekzite_pressed = False
        inside = True
        try:
            inside = 0 <= int(event.x) <= int(button.winfo_width()) and 0 <= int(event.y) <= int(button.winfo_height())
        except Exception:
            inside = True
        self._redraw_window_control(button)
        if inside:
            try:
                button._tekzite_command()
            except Exception:
                pass

    def _draw_window_control_icon(self, button, role, color, size):
        pad = max(8, int(size * 0.28))
        mid_x = size / 2
        mid_y = size / 2
        if role == "minimize":
            button.create_line(pad, size - pad, size - pad, size - pad, fill=color, width=2.2, capstyle=tk.ROUND)
        elif role == "maximize":
            if self._window_maximized:
                shift = max(3, int(size * 0.12))
                button.create_rectangle(pad + shift, pad, size - pad, size - pad - shift, outline=color, width=1.8)
                button.create_rectangle(pad, pad + shift, size - pad - shift, size - pad, outline=color, width=1.8)
            else:
                button.create_rectangle(pad, pad, size - pad, size - pad, outline=color, width=1.8)
        elif role == "close":
            button.create_line(pad, pad, size - pad, size - pad, fill=color, width=2.2, capstyle=tk.ROUND)
            button.create_line(size - pad, pad, pad, size - pad, fill=color, width=2.2, capstyle=tk.ROUND)

    def _redraw_window_control(self, button):
        try:
            size = max(26, self._ui_metric("app_bar_height", 44) - self._ui_padding(10))
            button.configure(width=size, height=size, bg=self.ui["bg"])
            button.delete("all")
            role = getattr(button, "_tekzite_role", "")
            hovered = bool(getattr(button, "_tekzite_hovered", False))
            pressed = bool(getattr(button, "_tekzite_pressed", False))
            close = bool(getattr(button, "_tekzite_close_control", False))
            if self._custom("window_control_style", "traffic_lights") == "traffic_lights":
                colors = {"close": "#ff5f57", "minimize": "#febc2e", "maximize": "#28c840"}
                base = colors.get(role, self.ui["accent"])
                radius = max(5, int(size * 0.23))
                cx = cy = size / 2
                if hovered:
                    button.create_oval(cx - radius - 2, cy - radius - 2, cx + radius + 2, cy + radius + 2, fill=self.ui["chrome_hover"], outline="")
                button.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill=base, outline=base)
                if hovered or pressed:
                    glyph = "#3a2c2c" if role == "close" else "#263025"
                    mini = max(3, int(radius * 0.48))
                    if role == "close":
                        button.create_line(cx-mini, cy-mini, cx+mini, cy+mini, fill=glyph, width=1.4, capstyle=tk.ROUND)
                        button.create_line(cx+mini, cy-mini, cx-mini, cy+mini, fill=glyph, width=1.4, capstyle=tk.ROUND)
                    elif role == "minimize":
                        button.create_line(cx-mini, cy, cx+mini, cy, fill=glyph, width=1.5, capstyle=tk.ROUND)
                    elif role == "maximize":
                        button.create_line(cx-mini, cy+mini, cx+mini, cy-mini, fill=glyph, width=1.4, capstyle=tk.ROUND)
                        button.create_line(cx+mini, cy-mini, cx+mini-2, cy-mini, fill=glyph, width=1.4)
                return
            if close:
                fill = self.ui["danger"] if hovered else self.ui["field"]
                outline = self.ui["danger"] if hovered else self.ui["border_soft"]
                icon = "#ffffff" if hovered or pressed else self.ui["danger"]
            else:
                fill = self.ui["chrome_hover"] if hovered else self.ui["field"]
                outline = self.ui["accent"] if hovered else self.ui["border_soft"]
                icon = self.ui["text"] if hovered or pressed else self.ui["muted"]
            if pressed:
                fill = self.ui["accent"] if not close else self.ui["danger"]
                outline = fill
                icon = "#ffffff"
            inset = 1
            button.create_rectangle(inset, inset, size - inset, size - inset, fill=fill, outline=outline, width=1)
            self._draw_window_control_icon(button, role, icon, size)
        except Exception:
            pass

    def _refresh_window_controls(self):
        buttons = list(getattr(self, "window_control_buttons", []) or [])
        if not buttons:
            return
        by_role = {getattr(button, "_tekzite_role", ""): button for button in buttons}
        order = ("close", "minimize", "maximize") if self._custom("window_control_style", "traffic_lights") == "traffic_lights" else ("minimize", "maximize", "close")
        for button in buttons:
            try:
                button.pack_forget()
            except Exception:
                pass
        arranged = []
        for role in order:
            button = by_role.get(role)
            if button is None:
                continue
            arranged.append(button)
            button.pack(side="left", padx=(0, self._ui_padding(6)))
            self._redraw_window_control(button)
        if arranged:
            try:
                arranged[-1].pack_configure(padx=(0, 0))
            except Exception:
                pass
        self.window_control_buttons = arranged

    def _build_browser_menus(self, parent):
        menu_specs = [
            ("File", [
                ("New Tab", self._new_tab, "Ctrl+T"),
                ("Close Tab", self._close_active_tab, "Ctrl+W"),
                ("Reopen Closed Tab", self._restore_closed_tab, "Ctrl+Shift+T"),
                ("New Window", self._new_window, "Ctrl+N"),
                ("New Private Window", self._new_private_window, "Ctrl+Shift+N"),
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
                ("Customize Tekzite…", self._show_customize_browser, "Ctrl+Shift+,"),
                ("Reset Interface", lambda: self._reset_interface_customization(confirm=True), "Ctrl+Shift+Alt+R"),
                None,
                ("Fullscreen", self._toggle_fullscreen, "F11"),
                ("Toggle Quiet Mode", self._toggle_quiet_mode, ""),
            ]),
            ("History", [
                ("Search History", self._show_history, "Ctrl+H"),
                ("Back", self.go_back, "Alt+Left"),
                ("Forward", self.go_forward, "Alt+Right"),
                ("Home", self._go_home, ""),
            ]),
            ("Bookmarks", [
                ("Bookmark This Page", self._bookmark_current_page, "Ctrl+D"),
                ("Manage Bookmarks", self._show_bookmarks, "Ctrl+Shift+O"),
            ]),
            ("Tools", [
                ("Downloads", self._show_downloads, "Ctrl+J"),
                ("Toggle Ad Blocking for This Site", self._toggle_site_adblock, ""),
                ("Site Info & Privacy", self._show_site_info, ""),
                ("Privacy Shield", self._show_privacy_shield, ""),
                ("Permissions Manager", self._show_permissions_manager, ""),
                ("Extension Manager", self._show_extension_manager, ""),
                ("Tab Groups", self._show_tab_groups, ""),
                ("Profiles", self._show_profile_manager, ""),
                None,
                ("Task Manager", self._show_task_manager, ""),
                ("Diagnostics", self._show_diagnostics, ""),
                ("Network Connections", self._show_network_connections, ""),
                ("Local Ports & Loopback", self._show_local_ports, ""),
                ("Check for Updates", self._check_for_updates, ""),
                ("Settings", self.show_preferences, "Ctrl+,"),
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
        menu_icons = {
            "New Tab": "+", "Close Tab": "×", "Reopen Closed Tab": "↶",
            "New Window": "□", "New Private Window": "◐", "Open Location": "⌖",
            "Exit": "⏻", "Find in Page": "⌕", "Cut": "✂", "Copy": "▣",
            "Paste": "▤", "Select All": "▦", "Reload": "↻",
            "Focus Address Bar": "⌖", "Customize Tekzite…": "✦", "Reset Interface": "↺",
            "Fullscreen": "⛶", "Toggle Quiet Mode": "◌", "Search History": "◷",
            "Back": "←", "Forward": "→", "Home": "⌂", "Bookmark This Page": "☆",
            "Manage Bookmarks": "▤", "Downloads": "↓", "Toggle Ad Blocking for This Site": "◇",
            "Site Info & Privacy": "◈", "Privacy Shield": "◆", "Permissions Manager": "✓",
            "Extension Manager": "◇", "Tab Groups": "▦", "Profiles": "◉",
            "Task Manager": "▥", "Diagnostics": "⌁", "Network Connections": "↗", "Local Ports & Loopback": "⌘",
            "Check for Updates": "↥", "Settings": "⚙", "Copy All Debug": "⧉",
            "Copy Full Debug": "⧉", "Inspect Chromium HTML": "</>", "About Tekzite": "ⓘ",
        }
        for label, items in menu_specs:
            menu = self._make_modern_menu(self.root)
            for item in items:
                if item is None:
                    menu.add_separator()
                    continue
                item_label, command, accelerator = item
                menu.add_command(
                    label=self._menu_item_text(item_label, menu_icons.get(item_label, "•")),
                    command=command,
                    accelerator=(f"  {accelerator}  " if accelerator else ""),
                )
            if label == "Tools":
                menu.configure(postcommand=lambda m=menu: self._update_site_menu(m))

            button = _RoundedChromeButton(
                parent, label, None,
                surface_bg=self.ui["bg"], hover_bg=self.ui["field_focus"],
                fg=self.ui["muted"], hover_fg=self.ui["text"],
                border=self.ui["bg"], hover_border=self.ui["border_soft"],
                canvas_bg=self.ui["bg"],
                font=(self._ui_font_family, self._font_size(9)),
                padx=self._ui_padding(10), pady=self._ui_padding(5),
                radius=self._ui_metric("control_corner_radius", 16),
                disabled_fg=self.ui["muted_dim"],
            )
            button._command = lambda b=button, m=menu: self._popup_menu_below(b, m)
            self._browser_menu_buttons.append(button)
            self._browser_menus.append(menu)
            button.pack(side="left", padx=(0, self._ui_padding(2)), pady=self._ui_padding(4))


    def _current_native_root_hwnd(self):
        """Return the current Win32 top-level HWND backing the Tk root.

        Windows can replace Tk's native wrapper when Tekzite temporarily drops
        override-redirect in order to iconify.  Never assume a cached HWND from
        before minimize is still the window the user can see afterwards.
        """
        if sys.platform != "win32":
            return 0
        try:
            import ctypes
            from ctypes import wintypes
            user32 = self._native_drag_user32 or ctypes.windll.user32
            inner = int(self.root.winfo_id())
            GA_ROOT = 2
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            return int(user32.GetAncestor(wintypes.HWND(inner), GA_ROOT) or inner)
        except Exception:
            return 0

    def _invalidate_native_window_drag_target(self):
        """Drop cached Win32 drag state after a native Tk wrapper transition."""
        self._native_drag_hwnd = 0
        self._native_drag_last_xy = None
        self._native_drag_dwm_offset = None

    def _prewarm_native_window_drag(self):
        """Resolve/cache the *current* Win32 drag path before the user starts moving."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            self._native_drag_user32 = user32
            self.root.update_idletasks()
            hwnd = int(self._current_native_root_hwnd() or 0)
            if not hwnd:
                raise RuntimeError("Tekzite native root HWND is unavailable")
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.BeginDeferWindowPos.argtypes = [ctypes.c_int]
            user32.BeginDeferWindowPos.restype = wintypes.HANDLE
            user32.DeferWindowPos.argtypes = [
                wintypes.HANDLE, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.DeferWindowPos.restype = wintypes.HANDLE
            user32.EndDeferWindowPos.argtypes = [wintypes.HANDLE]
            user32.EndDeferWindowPos.restype = wintypes.BOOL
            self._native_drag_hwnd = hwnd
            return bool(hwnd)
        except Exception:
            self._native_drag_user32 = None
            self._native_drag_hwnd = 0
            return False

    def _native_move_window_drag(self, x, y):
        """Move Tekzite and its DWM destination together without Tk geometry churn."""
        if sys.platform != "win32":
            return False
        # v10.5.54: minimizing a frameless Tk window can replace its native
        # top-level wrapper. Refresh the cached HWND whenever it no longer
        # matches the currently visible Tekzite root, otherwise the old code
        # could move only the freshly recreated DWM destination.
        live_hwnd = self._current_native_root_hwnd()
        if (not self._native_drag_hwnd or self._native_drag_user32 is None
                or not live_hwnd or int(self._native_drag_hwnd) != int(live_hwnd)):
            if not self._prewarm_native_window_drag():
                return False
        try:
            from ctypes import wintypes
            user32 = self._native_drag_user32
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_NOOWNERZORDER = 0x0200
            flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER
            x, y = int(x), int(y)
            if self._native_drag_last_xy == (x, y):
                return True
            offset = self._native_drag_dwm_offset
            has_dwm = bool(
                offset is not None and self._embedded_mode and self._chromium_dwm_mode
                and self._dwm_host and self._dwm_host_size
            )
            # Move Tekzite and the separate DWM destination in one deferred
            # Win32 batch. This gives Desktop Window Manager one coherent layout
            # commit per drag tick instead of two back-to-back top-level moves.
            if has_dwm:
                dx, dy = offset
                w, h = self._dwm_host_size
                dwm_x, dwm_y = x + int(dx), y + int(dy)
                dwm_w, dwm_h = max(1, int(w)), max(1, int(h))
                hdwp = user32.BeginDeferWindowPos(2)
                if hdwp:
                    hdwp = user32.DeferWindowPos(
                        hdwp, wintypes.HWND(int(self._native_drag_hwnd)), wintypes.HWND(0),
                        x, y, 0, 0, flags,
                    )
                # If the Tekzite root could not be queued, abort the whole
                # batch. Never let the DWM surface become the only window that
                # moves.
                if hdwp:
                    hdwp = user32.DeferWindowPos(
                        hdwp, wintypes.HWND(int(self._dwm_host)), wintypes.HWND(0),
                        dwm_x, dwm_y, dwm_w, dwm_h,
                        flags,
                    )
                if hdwp and user32.EndDeferWindowPos(hdwp):
                    self._dwm_host_rect = (dwm_x, dwm_y, dwm_w, dwm_h)
                    self._native_drag_last_xy = (x, y)
                    return True
            root_moved = bool(user32.SetWindowPos(
                wintypes.HWND(int(self._native_drag_hwnd)), wintypes.HWND(0),
                x, y, 0, 0, flags,
            ))
            if not root_moved:
                self._invalidate_native_window_drag_target()
                return False
            if has_dwm:
                if self._dwm_host_rect != (dwm_x, dwm_y, dwm_w, dwm_h):
                    dwm_moved = bool(user32.SetWindowPos(
                        wintypes.HWND(int(self._dwm_host)), wintypes.HWND(0),
                        dwm_x, dwm_y, dwm_w, dwm_h,
                        flags,
                    ))
                    if dwm_moved:
                        self._dwm_host_rect = (dwm_x, dwm_y, dwm_w, dwm_h)
            self._native_drag_last_xy = (x, y)
            return True
        except Exception:
            return False

    def _start_window_drag(self, event):
        if self._window_maximized or self._fullscreen:
            return
        root_x = int(self.root.winfo_x())
        root_y = int(self.root.winfo_y())
        self._window_drag_offset = (event.x_root - root_x, event.y_root - root_y)
        self._window_drag_active = True
        self._window_drag_pending_xy = None
        self._native_drag_last_xy = None
        # v10.5.54: refresh once at every drag start. The Tk top-level HWND can
        # change across taskbar minimize/restore, so a pre-minimize cache is not
        # safe even when it is non-zero.
        self._prewarm_native_window_drag()
        if self._dwm_host_rect is not None:
            try:
                self._native_drag_dwm_offset = (
                    int(self._dwm_host_rect[0]) - root_x,
                    int(self._dwm_host_rect[1]) - root_y,
                )
            except Exception:
                self._native_drag_dwm_offset = None
        else:
            self._native_drag_dwm_offset = None

    def _flush_window_drag(self):
        """Apply only the newest queued top-level drag position.

        Windows can deliver mouse motion much faster than Tk/DWM need to move a
        top-level window. Keeping only the latest coordinate prevents a backlog
        of root.geometry() calls and corresponding Configure/DWM work.
        """
        self._window_drag_after_id = None
        pending = self._window_drag_pending_xy
        self._window_drag_pending_xy = None
        if pending is None or not self._window_drag_active:
            return
        x, y = pending
        if not self._native_move_window_drag(x, y):
            try:
                self.root.geometry(f"+{int(x)}+{int(y)}")
            except tk.TclError:
                return
        if self._window_drag_pending_xy is not None and self._window_drag_after_id is None:
            self._window_drag_after_id = self.root.after(8, self._flush_window_drag)

    def _drag_window(self, event):
        if self._window_maximized or self._fullscreen:
            return
        dx, dy = self._window_drag_offset
        self._window_drag_pending_xy = (event.x_root - dx, event.y_root - dy)
        if self._window_drag_after_id is None:
            # ~120 Hz maximum Tk position updates. Raw mouse reports above this
            # rate are collapsed to the latest coordinate.
            self._window_drag_after_id = self.root.after(8, self._flush_window_drag)

    def _end_window_drag(self, event=None):
        if not self._window_drag_active:
            return
        if event is not None and not (self._window_maximized or self._fullscreen):
            dx, dy = self._window_drag_offset
            self._window_drag_pending_xy = (event.x_root - dx, event.y_root - dy)
        if self._window_drag_after_id is not None:
            try:
                self.root.after_cancel(self._window_drag_after_id)
            except Exception:
                pass
            self._window_drag_after_id = None
        pending = self._window_drag_pending_xy
        self._window_drag_pending_xy = None
        self._window_drag_active = False
        if pending is not None:
            if not self._native_move_window_drag(pending[0], pending[1]):
                try:
                    self.root.geometry(f"+{int(pending[0])}+{int(pending[1])}")
                except tk.TclError:
                    pass
        self._native_drag_dwm_offset = None
        self._native_drag_last_xy = None
        if self._embedded_mode and self._chromium_dwm_mode:
            self._schedule_dwm_geometry_sync(resize=False, delay=1)

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

    def _rearm_dwm_input_after_maximize(self, force_recrop=False):
        """Rebind DWM hit testing after maximize/restore changes the viewport.

        One transition beat performs a forced native recrop. Later beats only
        refresh the input metrics against the already-settled visible contract.
        This avoids both stale maximized hit testing and repeated DComp churn.
        """
        if not (self._embedded_mode and self._chromium_dwm_mode and self._dwm_surface_ready):
            return False

        # A pending poll can still be using the pre-maximize rectangle. Cancel
        # it and restart from the new host geometry instead of letting one stale
        # sample poison the first click after the viewport jump.
        if self._dwm_pointer_after_id is not None:
            try:
                self.root.after_cancel(self._dwm_pointer_after_id)
            except Exception:
                pass
            self._dwm_pointer_after_id = None
        self._dwm_pointer_inside = False
        self._dwm_pointer_last_screen_xy = None
        self._dwm_pointer_last_page_xy = None
        self._chromium_left_button_down = False
        self._chromium_drag_selecting = False
        self._chromium_press_point = None
        self._chromium_pending_drag = None

        if force_recrop:
            try:
                request_embedded_chromium_dwm_recrop()
            except Exception:
                pass
        if self._dwm_host:
            try:
                self._repair_dwm_host_owner_and_style(self._dwm_host)
            except Exception:
                pass

        # v10.5.70: on the first maximize/restore beat, force resize even when
        # the viewport cache already contains the new size. Otherwise the recrop
        # request can remain pending forever and input metrics keep the old
        # RenderWidgetHost scale. Later beats only remeasure the settled contract.
        self._schedule_dwm_geometry_sync(
            resize=bool(force_recrop),
            delay=1,
            force_resize=bool(force_recrop),
            refresh_input_metrics=True,
        )

        self._arm_dwm_input_surface()
        self._schedule_dwm_pointer_bridge(delay=1)
        return True

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
        self._refresh_window_controls()
        self._window_rounding_signature = None
        self._dwm_host_region_signature = None
        self.root.after_idle(self._apply_window_rounding)
        if self._embedded_mode and self._chromium_dwm_mode:
            # A maximize/restore is both a visual resize and an input-coordinate
            # transition. Reconcile the committed viewport immediately and once
            # again after Tk has finished packing the new geometry. Then re-arm
            # the input bridge across the same transition beats.
            self._schedule_dwm_geometry_sync(resize=True, delay=1)
            self.root.after(70, lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))
            self.root.after_idle(lambda: self._rearm_dwm_input_after_maximize(force_recrop=True))
            self.root.after(55, lambda: self._rearm_dwm_input_after_maximize(force_recrop=False))
            self.root.after(150, lambda: self._rearm_dwm_input_after_maximize(force_recrop=False))

    def _schedule_taskbar_restore_check(self, delay=120):
        if self._taskbar_restore_after_id is not None:
            try:
                self.root.after_cancel(self._taskbar_restore_after_id)
            except Exception:
                pass
        try:
            self._taskbar_restore_after_id = self.root.after(
                max(20, int(delay)), self._restore_frameless_after_minimize
            )
        except Exception:
            self._taskbar_restore_after_id = None

    def _ensure_root_visible_after_taskbar(self, attempt=1):
        """Fail-safe for Tk wrapper races after taskbar restore.

        A restored override-redirect root must be both non-iconic and mapped.
        Windows/Tk can briefly leave it withdrawn while the Python process is
        healthy.  Never accept that as a completed restore.
        """
        self._taskbar_restore_watchdog_id = None
        if not self._taskbar_restore_pending:
            return True
        try:
            if not bool(self.root.winfo_exists()):
                return False
            state = str(self.root.state())
            viewable = bool(self.root.winfo_viewable())
        except Exception:
            if int(attempt) < 8:
                try:
                    self._taskbar_restore_watchdog_id = self.root.after(
                        80, self._ensure_root_visible_after_taskbar, int(attempt) + 1
                    )
                except Exception:
                    pass
            return False

        if state == "iconic":
            # The user has not restored the taskbar window yet.
            self._schedule_taskbar_restore_check(100)
            return False

        if state == "withdrawn" or not viewable:
            try:
                self.root.deiconify()
                if self._taskbar_restore_geometry:
                    self.root.geometry(self._taskbar_restore_geometry)
                self.root.update_idletasks()
            except Exception:
                pass
            if int(attempt) < 8:
                try:
                    self._taskbar_restore_watchdog_id = self.root.after(
                        70, self._ensure_root_visible_after_taskbar, int(attempt) + 1
                    )
                except Exception:
                    pass
            return False

        # The Tk root is genuinely back. This wrapper-repair path is Windows
        # only now; Linux never leaves the WM-managed state.
        try:
            if sys.platform.startswith("linux"):
                self._apply_linux_managed_frameless(self.root)
            else:
                self.root.overrideredirect(True)
                self.root.update_idletasks()
                self._apply_frameless_app_style()
                self._invalidate_native_window_drag_target()
                self._prewarm_native_window_drag()
        except Exception:
            if int(attempt) < 8:
                try:
                    self._taskbar_restore_watchdog_id = self.root.after(
                        70, self._ensure_root_visible_after_taskbar, int(attempt) + 1
                    )
                except Exception:
                    pass
            return False

        self._taskbar_restore_pending = False
        self._taskbar_restore_attempts = 0
        self._taskbar_restore_geometry = None
        self._restore_dwm_host_after_taskbar()
        return True

    def _minimize_window(self):
        # Keep the historical ordering guarantee: if a DWM destination exists,
        # retire it before any iconify call. On Linux this is effectively a cheap
        # no-op cleanup before the native window manager handles minimization.
        self._suspend_dwm_host_for_minimize()
        if os.name != "nt":
            self._dwm_host_suspended_for_minimize = False
            self._invalidate_native_window_drag_target()
            # Linux is now a normal managed WM window, so minimize is native
            # and needs no override-redirect wrapper swap or restore watchdog.
            self._taskbar_restore_pending = False
            self._taskbar_restore_attempts = 0
            self._taskbar_restore_geometry = None
            try:
                self.root.iconify()
            except Exception:
                pass
            return
        # Tk cannot iconify an override-redirect window directly on Windows.
        # Retire the transient DWM destination first, then temporarily expose a
        # normal Tk wrapper for the taskbar. v10.5.54 explicitly tracks the
        # entire round-trip so a transient withdrawn state cannot strand the app.
        self._invalidate_native_window_drag_target()
        self._taskbar_restore_pending = True
        self._taskbar_restore_attempts = 0
        try:
            self._taskbar_restore_geometry = self.root.geometry()
        except Exception:
            self._taskbar_restore_geometry = None
        if self._taskbar_restore_watchdog_id is not None:
            try:
                self.root.after_cancel(self._taskbar_restore_watchdog_id)
            except Exception:
                pass
            self._taskbar_restore_watchdog_id = None
        try:
            self.root.overrideredirect(False)
            self.root.update_idletasks()
            # override-redirect(False) can create a fresh Tk wrapper. Mark that
            # wrapper as an app window before iconifying so the taskbar button
            # cannot vanish during the minimize transition.
            self._apply_frameless_app_style()
            self.root.iconify()
        except Exception:
            # If iconify itself races with Tk, immediately repair visibility
            # instead of leaving the root in a half-withdrawn wrapper state.
            try:
                self.root.deiconify()
            except Exception:
                pass
        self._schedule_taskbar_restore_check(120)

    def _restore_frameless_after_minimize(self):
        self._taskbar_restore_after_id = None
        if not self._taskbar_restore_pending:
            return
        self._taskbar_restore_attempts += 1
        try:
            if not bool(self.root.winfo_exists()):
                return
            state = str(self.root.state())
        except Exception:
            # A transient Tcl/Win32 wrapper error is not a reason to abandon the
            # restore loop. The old implementation returned here permanently.
            self._schedule_taskbar_restore_check(100)
            return

        if state == "iconic":
            self._schedule_taskbar_restore_check(100)
            return

        if state == "withdrawn":
            try:
                self.root.deiconify()
                if self._taskbar_restore_geometry:
                    self.root.geometry(self._taskbar_restore_geometry)
            except Exception:
                pass
            self._schedule_taskbar_restore_check(70)
            return

        try:
            if sys.platform.startswith("linux"):
                self._apply_linux_managed_frameless(self.root)
            else:
                self.root.overrideredirect(True)
                self.root.update_idletasks()
                self._apply_frameless_app_style()
        except Exception:
            self._schedule_taskbar_restore_check(80)
            return

        # If Tk is already genuinely mapped after the frameless wrapper swap,
        # finish immediately. Otherwise the watchdog owns completion. This also
        # preserves v10.5.53's guarantee that the native drag HWND is refreshed
        # before the fresh DWM destination is created.
        try:
            viewable = bool(self.root.winfo_viewable())
        except Exception:
            viewable = False
        if viewable:
            self._invalidate_native_window_drag_target()
            self._prewarm_native_window_drag()
            self._taskbar_restore_pending = False
            self._taskbar_restore_attempts = 0
            self._taskbar_restore_geometry = None
            self._restore_dwm_host_after_taskbar()
            return

        # Do not declare success until the root is actually mapped. Changing
        # override-redirect can itself trigger one more native wrapper remap.
        try:
            self._taskbar_restore_watchdog_id = self.root.after(
                35, self._ensure_root_visible_after_taskbar, 1
            )
        except Exception:
            self._ensure_root_visible_after_taskbar(1)

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        try:
            self.root.attributes("-fullscreen", self._fullscreen)
        except Exception:
            pass
        self._window_rounding_signature = None
        self._dwm_host_region_signature = None
        self.root.after_idle(self._apply_window_rounding)
        if self._embedded_mode and self._chromium_dwm_mode:
            # v10.5.38: maximizing/restoring changes the DWM viewport.  Reconcile
            # immediately and once more after Tk has finished packing children.
            self.root.after_idle(lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))
            self.root.after(70, lambda: self._schedule_dwm_geometry_sync(resize=True, delay=1))

    def _spawn_browser_process(self, *, private=False, profile=None):
        if getattr(sys, "frozen", False):
            command = [sys.executable]
        else:
            command = [sys.executable, os.path.abspath(__file__)]
        selected_profile = _profile_slug(profile or getattr(self, "_profile_name", "Default"))
        if selected_profile != "Default":
            command.extend(["--profile", selected_profile])
        if private:
            command.append("--private")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.Popen(command, creationflags=creationflags)

    def _new_window(self):
        try:
            self._spawn_browser_process(private=False)
        except Exception as exc:
            self.status_var.set(f"Could not open new window: {exc}")

    def _new_private_window(self):
        try:
            self._spawn_browser_process(private=True)
        except Exception as exc:
            self.status_var.set(f"Could not open private window: {exc}")
        return "break"

    def _restart_browser(self):
        # Spawn only after the current Chromium helper has released its profile.
        # Starting the replacement first can make Chromium treat the existing
        # user-data-dir as a handoff/lock conflict.
        self._restart_after_close = True
        return bool(self.on_close())

    def _focus_address(self):
        # Ctrl+L remains an escape hatch even when the user hides the toolbar
        # or address item through customization. Reveal it for the session.
        try:
            if not self.toolbar.winfo_ismapped():
                self.toolbar.pack(fill="x", before=self.chrome_separator)
            if not self.address_shell.winfo_ismapped():
                self.address_shell.pack(side="left", fill="x", expand=True, padx=(self._ui_padding(10), self._ui_padding(9)), pady=self._ui_padding(9))
        except Exception:
            pass
        # v4.80: explicitly take native keyboard ownership back from the
        # cross-process Chromium child before focusing the Tk Entry.
        self._address_focus_active = True
        self._chromium_page_keyboard_active = False
        self._dwm_keyboard_sink_focused = False
        self._stop_dwm_keyboard_poll()
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

    def _stop_loading_current(self):
        tab = self._active_tab() or {}
        target_id = tab.get("chromium_target_id")
        if not target_id:
            return "break"
        try:
            stop_embedded_chromium_loading(target_id=target_id, timeout=2)
            tab["loading"] = False
            tab["ready_state"] = "stopped"
            self.status_var.set("Loading stopped")
        except Exception as exc:
            self.status_var.set(f"Could not stop loading: {exc}")
        self._refresh_standard_toolbar_state()
        self._refresh_tab_strip()
        return "break"

    def _reload_or_stop_current(self):
        tab = self._active_tab() or {}
        if tab.get("loading"):
            return self._stop_loading_current()
        return self._reload_current()

    def _go_home(self):
        self.navigate_to(self._homepage_url())

    def _refresh_standard_toolbar_state(self):
        tab = self._active_tab() or {}
        loading = bool(tab.get("loading"))
        url = str(tab.get("url") or "")
        try:
            self.reload_button.configure(text=self._toolbar_text("reload", loading=loading))
        except Exception:
            pass
        try:
            bookmarked = bool(url and any(item.get("url") == url for item in self.bookmarks))
            self.bookmark_button.configure(
                text="★" if bookmarked else "☆",
                fg=self.ui["accent_hover"] if bookmarked else self.ui["muted"],
            )
        except Exception:
            pass

    def _show_main_menu(self):
        active = getattr(self, "_active_popup_menu", None)
        if (isinstance(active, _AnimatedPopupMenu) and active.is_posted()
                and getattr(active, "_anchor_button", None) is self.main_menu_button):
            active.dismiss(include_parent=False)
            return "break"
        menu = self._make_modern_menu(self.root, font_size=self._font_size(10))
        menu.add_command(label=self._menu_item_text("New Tab", "+"), command=self._new_tab, accelerator="  Ctrl+T  ")
        menu.add_command(label=self._menu_item_text("New Window", "□"), command=self._new_window, accelerator="  Ctrl+N  ")
        menu.add_command(label=self._menu_item_text("New Private Window", "◐"), command=self._new_private_window, accelerator="  Ctrl+Shift+N  ")
        menu.add_separator()
        menu.add_command(label=self._menu_item_text("History", "◷"), command=self._show_history, accelerator="  Ctrl+H  ")
        menu.add_command(label=self._menu_item_text("Downloads", "↓"), command=self._show_downloads, accelerator="  Ctrl+J  ")
        menu.add_command(label=self._menu_item_text("Bookmarks", "☆"), command=self._show_bookmarks, accelerator="  Ctrl+Shift+O  ")
        menu.add_separator()
        menu.add_command(label=self._menu_item_text("Find in Page", "⌕"), command=self._show_find_bar, accelerator="  Ctrl+F  ")
        menu.add_command(label=self._menu_item_text("Reload", "↻"), command=self._reload_current, accelerator="  Ctrl+R  ")
        menu.add_command(label=self._menu_item_text("Home", "⌂"), command=self._go_home)
        menu.add_separator()
        menu.add_command(label=self._menu_item_text("Extensions", "◇"), command=self._show_extension_manager)
        menu.add_command(label=self._menu_item_text("Customize Tekzite…", "✦"), command=self._show_customize_browser, accelerator="  Ctrl+Shift+,  ")
        menu.add_command(label=self._menu_item_text("Settings", "⚙"), command=self.show_preferences, accelerator="  Ctrl+,  ")
        menu.add_command(label=self._menu_item_text("About Tekzite", "ⓘ"), command=self._show_about)
        menu.add_separator()
        menu.add_command(label=self._menu_item_text("Exit", "⏻"), command=self.on_close, accelerator="  Alt+F4  ")
        try:
            self.root.update_idletasks()
            x = self.main_menu_button.winfo_rootx() + self.main_menu_button.winfo_width()
            y = self.main_menu_button.winfo_rooty() + self.main_menu_button.winfo_height()
            if hasattr(self.main_menu_button, "set_selected"):
                self.main_menu_button.set_selected(True)
            if isinstance(menu, _AnimatedPopupMenu):
                menu._anchor_button = self.main_menu_button
            menu.tk_popup(max(0, x - 250), y + self._ui_padding(3))
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

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

    def _website_color_scheme(self):
        return _normalized_website_color_scheme(
            getattr(self, "preferences", DEFAULT_PREFERENCES).get("website_color_scheme", "system")
        )

    def _apply_website_color_scheme_to_all_tabs(self):
        """Update prefers-color-scheme for every live Chromium-backed tab."""
        scheme = self._website_color_scheme()
        applied = False
        for target_id in self._live_chromium_target_ids():
            try:
                applied = bool(
                    set_embedded_chromium_color_scheme(scheme, target_id=target_id)
                ) or applied
            except Exception:
                pass
        return applied

    def _apply_chromium_zoom(self, target_id=None):
        """Apply Chromium page zoom and keep DWM on a 1:1 presentation contract."""
        if os.name != "nt" and self._page_zoom_percent() == 100:
            return True
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
        if os.name != "nt" and self._page_zoom_percent() == 100:
            return True
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
        if os.name != "nt":
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

    def _custom(self, key, default=None):
        custom = getattr(self, "customization", None)
        if not isinstance(custom, dict):
            custom = _normalized_customization(getattr(self, "preferences", DEFAULT_PREFERENCES).get("customization"))
            self.customization = custom
        return custom.get(key, default)

    def _density_factor(self):
        return {"compact": 0.84, "comfortable": 1.0, "spacious": 1.18}.get(str(self._custom("density", "spacious")), 1.0)

    def _ui_metric(self, key, default):
        try:
            value = float(self._custom(key, default))
            scale = float(self._custom("ui_scale", 1.0))
        except Exception:
            value, scale = float(default), 1.0
        return max(1, int(round(value * scale)))

    def _ui_padding(self, value):
        try:
            return max(0, int(round(float(value) * float(self._custom("ui_scale", 1.0)) * self._density_factor())))
        except Exception:
            return int(value)

    def _font_size(self, base=10):
        try:
            ratio = float(self._custom("font_size", 10)) / 10.0
            scale = float(self._custom("ui_scale", 1.0))
            return max(6, int(round(float(base) * ratio * scale)))
        except Exception:
            return max(6, int(base))

    def _toolbar_text(self, item, *, loading=False):
        icons = {"back": "‹", "forward": "›", "reload": "×" if loading else "↻", "home": "⌂", "downloads": "⇩", "menu": "⋮"}
        words = {"back": "Back", "forward": "Forward", "reload": "Stop" if loading else "Reload", "home": "Home", "downloads": "Downloads", "menu": "Menu"}
        mode = str(self._custom("toolbar_label_style", "icons"))
        if mode == "text":
            return words.get(item, item.title())
        if mode == "both":
            return f"{icons.get(item, '')} {words.get(item, item.title())}".strip()
        return icons.get(item, words.get(item, item.title()))

    def _search_url(self, query):
        template = str(getattr(self, "preferences", DEFAULT_PREFERENCES).get("search_url_template") or "https://www.startpage.com/sp/search?query={query}")
        if "{query}" not in template:
            template = "https://www.startpage.com/sp/search?query={query}"
        return template.replace("{query}", quote_plus(str(query or "")))

    def _apply_toolbar_layout(self):
        widgets = getattr(self, "_toolbar_widgets", {})
        if not widgets:
            return
        for widget in widgets.values():
            try:
                widget.pack_forget()
            except Exception:
                pass
        visible = self._custom("toolbar_visible", {})
        order = self._custom("toolbar_order", TOOLBAR_ITEM_IDS)
        gap = self._ui_padding(7)
        outer = self._ui_padding(12)
        for item in order:
            widget = widgets.get(item)
            if widget is None or not bool(visible.get(item, True)):
                continue
            if item == "address":
                widget.pack(side="left", fill="x", expand=True, padx=(self._ui_padding(12), outer), pady=outer)
            else:
                widget.pack(side="left", padx=(0, gap), pady=self._ui_padding(10))
        try:
            self.site_info_button.pack_forget()
            if self._custom("show_site_info_button", True):
                self.site_info_button.pack(side="left", padx=(self._ui_padding(8), self._ui_padding(2)))
        except Exception:
            pass
        try:
            self.bookmark_button.pack_forget()
            if self._custom("show_bookmark_button", True):
                self.bookmark_button.pack(side="right", padx=(0, self._ui_padding(4)))
        except Exception:
            pass

    def _repack_browser_chrome(self):
        # Rebuild only Tk packing order. Chromium's target/process is untouched.
        ordered = [
            getattr(self, "app_bar", None), getattr(self, "tab_bar", None), getattr(self, "toolbar", None),
            getattr(self, "find_bar", None), getattr(self, "chrome_separator", None),
            getattr(self, "content_frame", None), getattr(self, "status_bar", None),
        ]
        for widget in ordered:
            if widget is not None:
                try:
                    widget.pack_forget()
                except Exception:
                    pass

        app_bar = getattr(self, "app_bar", None)
        tab_bar = getattr(self, "tab_bar", None)
        toolbar = getattr(self, "toolbar", None)
        find_bar = getattr(self, "find_bar", None)
        separator = getattr(self, "chrome_separator", None)
        content = getattr(self, "content_frame", None)
        status = getattr(self, "status_bar", None)
        if self._custom("show_app_bar", True) and app_bar is not None:
            app_bar.pack(fill="x")
        tab_first = self._custom("tab_position", "above_toolbar") == "above_toolbar"
        if tab_first:
            if self._custom("show_tab_bar", True) and tab_bar is not None:
                tab_bar.pack(fill="x")
            if self._custom("show_toolbar", True) and toolbar is not None:
                toolbar.pack(fill="x")
        else:
            if self._custom("show_toolbar", True) and toolbar is not None:
                toolbar.pack(fill="x")
            if self._custom("show_tab_bar", True) and tab_bar is not None:
                tab_bar.pack(fill="x")
        if getattr(self, "_find_bar_visible", False) and find_bar is not None:
            find_bar.pack(fill="x")
        if separator is not None and self._custom("show_chrome_separator", True):
            separator.pack(fill="x")
        if content is not None:
            content.pack(fill="both", expand=True)
        status_visible = bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True)) and not getattr(self, "preferences", DEFAULT_PREFERENCES).get("quiet_mode", False)
        if status_visible and status is not None:
            status.pack(fill="x")
        try:
            self.tab_items.pack_forget()
            self.tab_items.pack(side="left", fill="both", expand=True, padx=(self._ui_padding(16), self._ui_padding(10)), pady=(self._ui_padding(8), self._ui_padding(7)))
            self._place_new_tab_button_inline()
        except Exception:
            pass
        try:
            self.app_brand.pack_forget()
            if self._custom("show_brand_badge", True) or self._custom("show_title_text", True):
                self.app_brand.pack(side="left", padx=(self._ui_padding(18), self._ui_padding(16)), fill="y")
            self.brand_badge.pack_forget()
            if self._custom("show_brand_badge", True):
                self.brand_badge.pack(side="left", pady=self._ui_padding(5))
            self.title_label.pack_forget()
            if self._custom("show_title_text", True):
                self.title_label.pack(side="left", padx=(self._ui_padding(7), 0))
        except Exception:
            pass
        try:
            self.menu_strip.pack_forget()
            if self._custom("show_menu_bar", True):
                self.menu_strip.pack(side="left", fill="y", padx=(0, self._ui_padding(10)))
        except Exception:
            pass
        try:
            self.window_controls.pack_forget()
            if self._custom("show_window_controls", True):
                if self._custom("window_control_style", "traffic_lights") == "traffic_lights":
                    self.window_controls.pack(side="left", fill="y", padx=(self._ui_padding(14), self._ui_padding(6)), pady=self._ui_padding(7), before=self.app_brand)
                else:
                    self.window_controls.pack(side="right", fill="y", padx=(self._ui_padding(8), self._ui_padding(14)), pady=self._ui_padding(7))
        except Exception:
            pass
        try:
            self.scrollbar.pack_forget()
            if self._custom("show_scrollbar", True):
                self.scrollbar.pack(side="right", fill="y")
        except Exception:
            pass
        try:
            self.status_activity_dot.pack_forget()
            self.status_text_label.pack_forget()
            self.status_version_label.pack_forget()
            if self._custom("show_status_activity_dot", True):
                self.status_activity_dot.pack(side="left", padx=(self._ui_padding(16), self._ui_padding(8)))
            self.status_text_label.pack(side="left", fill="x", expand=True)
            if self._custom("show_status_version", True):
                self.status_version_label.pack(side="right", padx=(self._ui_padding(10), self._ui_padding(16)))
        except Exception:
            pass

    def _replace_palette_in_widget_tree(self, widget, old_ui, new_ui):
        reverse = {str(value).lower(): new_ui.get(key, value) for key, value in old_ui.items()}
        color_options = ("bg", "background", "fg", "foreground", "activebackground", "activeforeground",
                         "highlightbackground", "highlightcolor", "insertbackground", "selectbackground", "selectforeground")
        for option in color_options:
            try:
                current = str(widget.cget(option))
            except Exception:
                continue
            replacement = reverse.get(current.lower())
            if replacement and replacement != current:
                try:
                    widget.configure(**{option: replacement})
                except Exception:
                    pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = ()
        for child in children:
            self._replace_palette_in_widget_tree(child, old_ui, new_ui)

    def _apply_customization_runtime(self, *, repack=True, refresh_tabs=True):
        old_ui = dict(getattr(self, "ui", UI_COLOR_DEFAULTS))
        self.customization = _normalized_customization(self.preferences.get("customization"))
        self.preferences["customization"] = self.customization
        self.ui = dict(self.customization["colors"])
        try:
            self.root.configure(bg=self.ui["bg"])
            self._replace_palette_in_widget_tree(self.root, old_ui, self.ui)
        except Exception:
            pass
        try:
            self.app_bar.configure(height=self._ui_metric("app_bar_height", 44), bg=self.ui["bg"])
            self.tab_bar.configure(height=self._ui_metric("tab_bar_height", 52), bg=self.ui["chrome"])
            self.toolbar.configure(height=self._ui_metric("toolbar_height", 72), bg=self.ui["chrome"])
            self.status_bar.configure(height=self._ui_metric("status_bar_height", 30), bg=self.ui["chrome"], highlightbackground=self.ui["border"])
            self.chrome_separator.configure(bg=self.ui["border_soft"])
            self.brand_badge.configure(bg=self.ui["accent"])
            self.status_activity_dot.configure(fg=self.ui.get("success", "#45d483"), bg=self.ui["chrome"])
            self.address_shell.configure(bg=self.ui["chrome"])
            self.address_backdrop.configure(bg=self.ui["chrome"])
            self._set_address_shell_focus(self._address_focused)
            if hasattr(self.new_tab_button, "set_palette"):
                self.new_tab_button.set_palette(
                    surface_bg=self.ui["chrome_2"], hover_bg=self.ui["field_focus"],
                    fg=self.ui["muted"], hover_fg=self.ui["text"],
                    border=self.ui["border_soft"], hover_border=self.ui["border_focus"],
                    canvas_bg=self.ui["chrome"],
                    radius=self._ui_metric("control_corner_radius", 16),
                    disabled_fg=self.ui["muted_dim"],
                )
            self._refresh_window_controls()
            self._window_rounding_signature = None
            self._dwm_host_region_signature = None
            self.root.after_idle(self._apply_window_rounding)
        except Exception:
            pass
        try:
            import tkinter.font as tkfont
            families = {str(name).casefold(): str(name) for name in tkfont.families(self.root)}
            automatic_ui = families.get("segoe ui variable text", families.get("segoe ui", "Segoe UI"))
            automatic_display = families.get("segoe ui variable display", automatic_ui)
            automatic_mono = families.get("cascadia mono", families.get("consolas", "Consolas"))
            requested_ui = str(self._custom("font_family", "")).casefold()
            requested_display = str(self._custom("display_font_family", "")).casefold()
            requested_mono = str(self._custom("monospace_font_family", "")).casefold()
            self._ui_font_family = families.get(requested_ui, automatic_ui) if requested_ui else automatic_ui
            self._ui_display_font_family = families.get(requested_display, automatic_display) if requested_display else automatic_display
            self._ui_monospace_font_family = families.get(requested_mono, automatic_mono) if requested_mono else automatic_mono
            for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkCaptionFont", "TkSmallCaptionFont"):
                try:
                    tkfont.nametofont(named).configure(family=self._ui_font_family, size=max(7, int(self._custom("font_size", 10))))
                except Exception:
                    pass
            try:
                tkfont.nametofont("TkHeadingFont").configure(family=self._ui_display_font_family, weight="bold")
            except Exception:
                pass
            base = max(7, int(self._custom("font_size", 10)))
            menu = max(7, int(self._custom("menu_font_size", 9)))
            toolbar_size = max(7, int(self._custom("toolbar_font_size", 10)))
            self.address.configure(font=("Segoe UI", max(10, base + 1)))
            self._schedule_address_preview_render()
            self.title_label.configure(font=(self._ui_font_family, menu, "bold"))
            self.brand_badge.configure(font=(self._ui_font_family, menu, "bold"))
            self.status_text_label.configure(font=(self._ui_font_family, menu))
            self.status_version_label.configure(font=(self._ui_font_family, max(7, menu - 1)))
            for item, button in self._toolbar_widgets.items():
                if item != "address":
                    if hasattr(button, "set_palette"):
                        button.set_palette(
                            surface_bg=self.ui["field"], hover_bg=self.ui["field_focus"],
                            fg=self.ui["muted"], hover_fg="#ffffff",
                            border=self.ui["border_soft"], hover_border=self.ui["border_focus"],
                            canvas_bg=self.ui["chrome"],
                            radius=self._ui_metric("control_corner_radius", 16),
                            disabled_fg=self.ui["muted_dim"],
                        )
                    button.configure(font=(self._ui_font_family, toolbar_size))
            for button in getattr(self, "_browser_menu_buttons", []):
                if hasattr(button, "set_palette"):
                    button.set_palette(
                        surface_bg=self.ui["bg"], hover_bg=self.ui["field_focus"],
                        fg=self.ui["muted"], hover_fg=self.ui["text"],
                        border=self.ui["bg"], hover_border=self.ui["border_soft"],
                        canvas_bg=self.ui["bg"], radius=self._ui_metric("control_corner_radius", 16),
                        disabled_fg=self.ui["muted_dim"],
                    )
                button.configure(font=(self._ui_font_family, menu))
            for browser_menu in getattr(self, "_browser_menus", []):
                browser_menu.configure(
                    bg=self.ui["chrome_2"], fg=self.ui["text"],
                    activebackground=self.ui["field_focus"], activeforeground=self.ui["text"],
                    disabledforeground=self.ui["muted_dim"], selectcolor=self.ui["accent"],
                    borderwidth=0, activeborderwidth=0,
                    font=(self._ui_font_family, max(menu, self._font_size(10))),
                )
        except Exception:
            pass
        try:
            loading = bool((self._active_tab() or {}).get("loading"))
            self.back_button.configure(text=self._toolbar_text("back"))
            self.forward_button.configure(text=self._toolbar_text("forward"))
            self.reload_button.configure(text=self._toolbar_text("reload", loading=loading))
            self.home_button.configure(text=self._toolbar_text("home"))
            self.downloads_button.configure(text=self._toolbar_text("downloads"))
            self.main_menu_button.configure(text=self._toolbar_text("menu"))
        except Exception:
            pass
        try:
            title_version = f" v{BROWSER_VERSION}" if self._custom("show_version_in_title", True) else ""
            self.root.title(f"Tekzite Browser{' — Private' if self._private_mode else ''}{' — ' + self._profile_name if self._profile_name != 'Default' else ''}{title_version}")
            badge_version = f"  v{BROWSER_VERSION}" if self._custom("show_version_in_title", True) else ""
            self.title_label.configure(text=f"Tekzite{' • Private' if self._private_mode else ''}{badge_version}")
            self.root.minsize(self._custom("window_min_width", 900), self._custom("window_min_height", 600))
        except Exception:
            pass
        try:
            style = ttk.Style(self.root)
            style.configure("Tekzite.Vertical.TScrollbar", background=self.ui["chrome_2"], troughcolor=self.ui["bg"],
                            bordercolor=self.ui["bg"], arrowcolor=self.ui["muted"], lightcolor=self.ui["chrome_2"],
                            darkcolor=self.ui["chrome_2"], width=max(8, int(12 * float(self._custom("ui_scale", 1.0)))))
            style.configure("Tekzite.TNotebook", background=self.ui["bg"], borderwidth=0)
            style.configure("Tekzite.TNotebook.Tab", background=self.ui["chrome_2"], foreground=self.ui["text"], padding=(10, 6))
            style.map("Tekzite.TNotebook.Tab", background=[("selected", self.ui["accent"]), ("active", self.ui["chrome_hover"])], foreground=[("selected", "#ffffff")])
            style.configure("Treeview", background=self.ui["field"], fieldbackground=self.ui["field"], foreground=self.ui["text"],
                            rowheight=max(20, self._font_size(22)), bordercolor=self.ui["border"], font=(self._ui_font_family, self._font_size(9)))
            style.map("Treeview", background=[("selected", self.ui["accent"])], foreground=[("selected", "#ffffff")])
            style.configure("Treeview.Heading", background=self.ui["chrome_2"], foreground=self.ui["text"],
                            bordercolor=self.ui["border"], font=(self._ui_font_family, self._font_size(9)))
            style.configure("TCombobox", fieldbackground=self.ui["field"], background=self.ui["chrome_2"], foreground=self.ui["text"],
                            arrowcolor=self.ui["muted"], bordercolor=self.ui["border"], font=(self._ui_font_family, self._font_size(9)))
            style.map("TCombobox", fieldbackground=[("readonly", self.ui["field"])], foreground=[("readonly", self.ui["text"])])
        except Exception:
            pass
        self._apply_toolbar_layout()
        if repack:
            self._repack_browser_chrome()
        if refresh_tabs and getattr(self, "tab_items", None) is not None:
            self._refresh_tab_strip()
        try:
            self.root.update_idletasks()
            self._schedule_live_reflow()
        except Exception:
            pass

    def _reset_interface_customization(self, confirm=False):
        if confirm and not self._ask_yes_no("Reset Tekzite interface", "Reset all interface customization to Tekzite defaults?", parent=self.root):
            return "break"
        self.preferences["customization"] = _normalized_customization(DEFAULT_CUSTOMIZATION)
        self.customization = self.preferences["customization"]
        try:
            save_preferences(self.preferences)
        except Exception as exc:
            self.status_var.set(f"Could not save reset interface: {exc}")
            return "break"
        self._apply_customization_runtime()
        self.status_var.set("Tekzite interface reset to defaults")
        return "break"

    def _persist_preferences(self):
        save_preferences(self.preferences)

    def _apply_preferences_runtime(self):
        strict_loopback = bool(self.preferences.get("strict_python_loopback", True))
        os.environ["TEKZITE_STRICT_PYTHON_LOOPBACK"] = "1" if strict_loopback else "0"
        os.environ["TEKZITE_PRIVACY_LOCKDOWN"] = "1" if self.preferences.get("privacy_lockdown", True) else "0"
        os.environ["TEKZITE_TRACKER_BLOCKING"] = "1" if self.preferences.get("tracker_blocking_enabled", True) else "0"
        os.environ["TEKZITE_STRIP_REFERRER"] = "1" if self.preferences.get("strip_referrer", True) else "0"
        os.environ["TEKZITE_HTTPS_FIRST"] = "1" if self.preferences.get("https_first", True) else "0"
        loopback_policy.set_enabled(strict_loopback)
        if self.preferences.get("privacy_lockdown", False):
            try:
                (self._state_directory / "session.json").unlink(missing_ok=True)
                write_json(self._state_directory / "history.json", [])
                self.visits = []
                self._history_dirty = False
            except Exception:
                pass
        self._configure_feature_preferences()
        self.customization = _normalized_customization(self.preferences.get("customization"))
        self._apply_customization_runtime()
        self._apply_quiet_mode()
        if not self.preferences.get("omnibox_suggestions_enabled", True):
            self._hide_omnibox_suggestions()
        from engine import features
        if features.net._EDGE_SESSION:
            self._feature_async(features.configure, lambda _: None)

        if hasattr(self, "status_bar"):
            visible = bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True)) and not self.preferences.get("quiet_mode", False)
            if visible and not self.status_bar.winfo_ismapped():
                self.status_bar.pack(fill="x")
            elif not visible and self.status_bar.winfo_ismapped():
                self.status_bar.pack_forget()

    def _show_customize_browser(self):
        import tkinter.font as tkfont

        win = self._new_animated_toplevel(self.root)
        win.title(f"Customize Tekzite — v{BROWSER_VERSION}")
        win.geometry("900x720")
        win.minsize(780, 620)
        win.transient(self.root)
        win.configure(bg=self.ui["bg"])

        original_custom = json.loads(json.dumps(_normalized_customization(self.preferences.get("customization"))))
        draft = json.loads(json.dumps(original_custom))

        header = tk.Frame(win, bg=self.ui["bg"], padx=18, pady=(4, 10))
        header.pack(fill="x")
        tk.Label(header, text="Profile-specific appearance and behavior.",
                 bg=self.ui["bg"], fg=self.ui["muted"], font=(self._ui_font_family, self._font_size(9))).pack(anchor="w")

        notebook = ttk.Notebook(win, style="Tekzite.TNotebook")
        notebook.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        def page(title):
            frame = tk.Frame(notebook, bg=self.ui["bg"], padx=18, pady=16)
            notebook.add(frame, text=title)
            return frame

        appearance = page("Appearance")
        toolbar_page = page("Toolbar")
        tabs_page = page("Tabs & Layout")
        behavior_page = page("Behavior")
        advanced_page = page("Advanced")
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._animate_notebook_page(notebook), add="+")

        def label(parent, text, *, muted=False, bold=False, width=None):
            return tk.Label(parent, text=text, bg=self.ui["bg"], fg=self.ui["muted"] if muted else self.ui["text"],
                            font=(self._ui_font_family, self._font_size(9), "bold" if bold else "normal"), anchor="w", width=width)

        def check(parent, text, variable):
            widget = tk.Checkbutton(parent, text=text, variable=variable, bg=self.ui["bg"], fg=self.ui["text"],
                                    selectcolor=self.ui["field"], activebackground=self.ui["bg"], activeforeground=self.ui["text"],
                                    highlightthickness=0, bd=0, font=(self._ui_font_family, self._font_size(9)))
            return widget

        def entry(parent, variable, width=None):
            widget = tk.Entry(parent, textvariable=variable, bg=self.ui["field"], fg=self.ui["text"], insertbackground=self.ui["text"],
                              selectbackground=self.ui["accent"], selectforeground="#ffffff", relief="flat", bd=0,
                              highlightthickness=1, highlightbackground=self.ui["border"], font=(self._ui_font_family, self._font_size(9)), width=width)
            return widget

        # Appearance ---------------------------------------------------------
        preset_var = tk.StringVar(value=draft.get("preset", "Aurora Glass"))
        row = tk.Frame(appearance, bg=self.ui["bg"]); row.pack(fill="x", pady=(0, 12))
        label(row, "Preset", bold=True, width=16).pack(side="left")
        preset_box = ttk.Combobox(row, textvariable=preset_var, values=list(CUSTOMIZATION_PRESETS) + ["Custom"], state="readonly", width=22)
        preset_box.pack(side="left")

        color_vars = {key: tk.StringVar(value=draft["colors"][key]) for key in UI_COLOR_DEFAULTS}
        colors_frame = tk.Frame(appearance, bg=self.ui["bg"])
        colors_frame.pack(fill="x")
        pretty = {
            "bg": "Window background", "chrome": "Toolbar background", "chrome_2": "Button surface", "chrome_hover": "Hover surface",
            "field": "Address / field", "field_focus": "Focused field", "border": "Borders", "border_soft": "Soft borders",
            "border_focus": "Focus border", "text": "Primary text", "muted": "Secondary text", "muted_dim": "Dim text",
            "accent": "Accent", "accent_hover": "Accent hover", "danger": "Danger / close", "success": "Status success",
        }

        def choose_color(key):
            chosen = colorchooser.askcolor(color=color_vars[key].get(), parent=win, title=pretty.get(key, key))[1]
            if chosen:
                color_vars[key].set(chosen.lower())
                preset_var.set("Custom")

        for idx, key in enumerate(UI_COLOR_DEFAULTS):
            cell = tk.Frame(colors_frame, bg=self.ui["bg"])
            cell.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=(0, 14), pady=3)
            colors_frame.grid_columnconfigure(idx % 2, weight=1)
            label(cell, pretty.get(key, key), width=16).pack(side="left")
            entry(cell, color_vars[key], width=10).pack(side="left", padx=(0, 5), ipady=3)
            tk.Button(cell, text="●", command=lambda k=key: choose_color(k), bg=self.ui["chrome_2"], fg=color_vars[key].get(),
                      activebackground=self.ui["field_focus"], relief="flat", bd=0, padx=8).pack(side="left")

        font_row = tk.Frame(appearance, bg=self.ui["bg"]); font_row.pack(fill="x", pady=(16, 4))
        families = sorted(set(str(x) for x in tkfont.families(self.root)), key=str.casefold)
        font_var = tk.StringVar(value=draft.get("font_family", ""))
        display_font_var = tk.StringVar(value=draft.get("display_font_family", ""))
        mono_font_var = tk.StringVar(value=draft.get("monospace_font_family", ""))
        label(font_row, "UI font", bold=True, width=16).pack(side="left")
        ttk.Combobox(font_row, textvariable=font_var, values=[""] + families, width=24).pack(side="left", padx=(0, 12))
        label(font_row, "Display font", width=12).pack(side="left")
        ttk.Combobox(font_row, textvariable=display_font_var, values=[""] + families, width=24).pack(side="left")
        mono_row = tk.Frame(appearance, bg=self.ui["bg"]); mono_row.pack(fill="x", pady=(2, 4))
        label(mono_row, "Monospace font", width=16).pack(side="left")
        ttk.Combobox(mono_row, textvariable=mono_font_var, values=[""] + families, width=24).pack(side="left")

        size_row = tk.Frame(appearance, bg=self.ui["bg"]); size_row.pack(fill="x", pady=5)
        font_size_var = tk.StringVar(value=str(draft.get("font_size", 11)))
        menu_font_size_var = tk.StringVar(value=str(draft.get("menu_font_size", 10)))
        tab_font_size_var = tk.StringVar(value=str(draft.get("tab_font_size", 10)))
        toolbar_font_size_var = tk.StringVar(value=str(draft.get("toolbar_font_size", 11)))
        for text, var in (("UI size", font_size_var), ("Menu", menu_font_size_var), ("Tabs", tab_font_size_var), ("Toolbar", toolbar_font_size_var)):
            label(size_row, text).pack(side="left", padx=(0, 4))
            entry(size_row, var, width=4).pack(side="left", padx=(0, 12), ipady=3)

        density_var = tk.StringVar(value=draft.get("density", "spacious"))
        scale_var = tk.StringVar(value=str(draft.get("ui_scale", 1.0)))
        animations_var = tk.BooleanVar(value=bool(draft.get("animations", True)))
        window_control_style_var = tk.StringVar(value=draft.get("window_control_style", "traffic_lights"))
        tab_style_var = tk.StringVar(value=draft.get("tab_style", "soft"))
        row = tk.Frame(appearance, bg=self.ui["bg"]); row.pack(fill="x", pady=5)
        label(row, "Density", width=16).pack(side="left")
        ttk.Combobox(row, textvariable=density_var, values=["compact", "comfortable", "spacious"], state="readonly", width=16).pack(side="left", padx=(0, 14))
        label(row, "UI scale").pack(side="left")
        ttk.Combobox(row, textvariable=scale_var, values=["0.75", "0.85", "1.0", "1.1", "1.25", "1.4", "1.6"], width=8).pack(side="left", padx=(6, 14))
        check(row, "Animations", animations_var).pack(side="left")
        style_row = tk.Frame(appearance, bg=self.ui["bg"]); style_row.pack(fill="x", pady=(6, 3))
        label(style_row, "Window controls", width=16).pack(side="left")
        ttk.Combobox(style_row, textvariable=window_control_style_var, values=["traffic_lights", "tekzite"], state="readonly", width=16).pack(side="left", padx=(0, 14))
        label(style_row, "Tab style").pack(side="left")
        ttk.Combobox(style_row, textvariable=tab_style_var, values=["soft", "classic"], state="readonly", width=14).pack(side="left", padx=(6, 0))

        def select_preset(_event=None):
            name = preset_var.get()
            colors = CUSTOMIZATION_PRESETS.get(name)
            if colors:
                for key in UI_COLOR_DEFAULTS:
                    color_vars[key].set(colors[key])
        preset_box.bind("<<ComboboxSelected>>", select_preset)

        # Toolbar ------------------------------------------------------------
        show_toolbar_var = tk.BooleanVar(value=bool(draft.get("show_toolbar", True)))
        label_style_var = tk.StringVar(value=draft.get("toolbar_label_style", "icons"))
        site_info_var = tk.BooleanVar(value=bool(draft.get("show_site_info_button", True)))
        bookmark_button_var = tk.BooleanVar(value=bool(draft.get("show_bookmark_button", True)))
        check(toolbar_page, "Show toolbar", show_toolbar_var).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(toolbar_page, bg=self.ui["bg"]); row.pack(fill="x", pady=(0, 10))
        label(row, "Button labels", width=16).pack(side="left")
        ttk.Combobox(row, textvariable=label_style_var, values=["icons", "text", "both"], state="readonly", width=14).pack(side="left")
        check(row, "Site info inside address bar", site_info_var).pack(side="left", padx=(18, 0))
        check(row, "Bookmark star", bookmark_button_var).pack(side="left", padx=(18, 0))

        order = list(draft.get("toolbar_order", TOOLBAR_ITEM_IDS))
        visible_vars = {item: tk.BooleanVar(value=bool(draft.get("toolbar_visible", {}).get(item, True))) for item in TOOLBAR_ITEM_IDS}
        left = tk.Frame(toolbar_page, bg=self.ui["bg"]); left.pack(side="left", fill="both", expand=True, pady=8)
        label(left, "Order", bold=True).pack(anchor="w", pady=(0, 5))
        order_list = tk.Listbox(left, bg=self.ui["field"], fg=self.ui["text"], selectbackground=self.ui["accent"], selectforeground="#ffffff",
                                relief="flat", bd=0, highlightthickness=1, highlightbackground=self.ui["border"], height=10,
                                font=(self._ui_font_family, self._font_size(10)))
        order_list.pack(fill="both", expand=True)
        order_buttons = tk.Frame(left, bg=self.ui["bg"]); order_buttons.pack(fill="x", pady=6)

        def refresh_order():
            order_list.delete(0, "end")
            for item in order:
                order_list.insert("end", TOOLBAR_ITEM_NAMES[item])

        def move_order(delta):
            selected = order_list.curselection()
            if not selected:
                return
            idx = selected[0]
            other = idx + delta
            if not 0 <= other < len(order):
                return
            order[idx], order[other] = order[other], order[idx]
            refresh_order(); order_list.selection_set(other); order_list.activate(other)

        tk.Button(order_buttons, text="↑ Move up", command=lambda: move_order(-1), bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=10, pady=5).pack(side="left", padx=(0, 5))
        tk.Button(order_buttons, text="↓ Move down", command=lambda: move_order(1), bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=10, pady=5).pack(side="left")
        refresh_order()

        right = tk.Frame(toolbar_page, bg=self.ui["bg"], padx=24); right.pack(side="left", fill="both", expand=True, pady=8)
        label(right, "Visible items", bold=True).pack(anchor="w", pady=(0, 5))
        for item in TOOLBAR_ITEM_IDS:
            check(right, TOOLBAR_ITEM_NAMES[item], visible_vars[item]).pack(anchor="w", pady=2)
        label(right, "Ctrl+L always opens the address bar.", muted=True).pack(anchor="w", pady=(12, 0))

        # Tabs & layout ------------------------------------------------------
        bool_vars = {}
        bool_labels = (
            ("show_app_bar", "Show application/title bar"), ("show_brand_badge", "Show Tekzite badge"),
            ("show_title_text", "Show Tekzite title"), ("show_version_in_title", "Show version in title"),
            ("show_menu_bar", "Show File/Edit/View menus"), ("show_window_controls", "Show minimize/maximize/close controls"),
            ("show_tab_bar", "Show tab strip"), ("show_new_tab_button", "Show new-tab + button"),
            ("show_tab_favicons", "Show favicons"), ("show_tab_close_buttons", "Show tab close buttons"),
            ("show_tab_group_chips", "Show tab-group chips"), ("show_tab_active_indicator", "Show active-tab indicator"),
            ("show_scrollbar", "Show Tekzite scrollbar"), ("show_chrome_separator", "Show chrome/content separator"),
            ("show_status_activity_dot", "Show status activity dot"), ("show_status_version", "Show version in status bar"),
        )
        grid = tk.Frame(tabs_page, bg=self.ui["bg"]); grid.pack(fill="x")
        for index, (key, text) in enumerate(bool_labels):
            var = tk.BooleanVar(value=bool(draft.get(key, True))); bool_vars[key] = var
            check(grid, text, var).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 24), pady=3)
        tab_position_var = tk.StringVar(value=draft.get("tab_position", "above_toolbar"))
        new_tab_position_var = tk.StringVar(value=draft.get("new_tab_button_position", "right"))
        tab_chars_var = tk.StringVar(value=str(draft.get("tab_title_chars", 28)))
        tab_min_width_var = tk.StringVar(value=str(draft.get("tab_min_width", 175)))
        tab_max_width_var = tk.StringVar(value=str(draft.get("tab_max_width", 330)))
        row = tk.Frame(tabs_page, bg=self.ui["bg"]); row.pack(fill="x", pady=(16, 4))
        label(row, "Tab strip position", width=18).pack(side="left")
        ttk.Combobox(row, textvariable=tab_position_var, values=["above_toolbar", "below_toolbar"], state="readonly", width=16).pack(side="left", padx=(0, 18))
        label(row, "+ button position").pack(side="left")
        ttk.Combobox(row, textvariable=new_tab_position_var, values=["left", "right"], state="readonly", width=10).pack(side="left", padx=(6, 18))
        label(row, "Tab title chars").pack(side="left")
        entry(row, tab_chars_var, width=5).pack(side="left", padx=(6, 14), ipady=3)
        label(row, "Min width").pack(side="left")
        entry(row, tab_min_width_var, width=5).pack(side="left", padx=(6, 14), ipady=3)
        label(row, "Max width").pack(side="left")
        entry(row, tab_max_width_var, width=5).pack(side="left", padx=(6, 0), ipady=3)

        window_radius_var = tk.StringVar(value=str(draft.get("window_corner_radius", 24)))
        content_radius_var = tk.StringVar(value=str(draft.get("content_corner_radius", 18)))
        control_radius_var = tk.StringVar(value=str(draft.get("control_corner_radius", 16)))
        radius_row = tk.Frame(tabs_page, bg=self.ui["bg"]); radius_row.pack(fill="x", pady=(10, 2))
        label(radius_row, "Corner radius", bold=True, width=18).pack(side="left")
        for text, var in (("Window", window_radius_var), ("Web content", content_radius_var), ("Controls", control_radius_var)):
            label(radius_row, text).pack(side="left", padx=(0, 4))
            entry(radius_row, var, width=5).pack(side="left", padx=(0, 14), ipady=3)

        heights = {
            "app_bar_height": tk.StringVar(value=str(draft.get("app_bar_height", 44))),
            "tab_bar_height": tk.StringVar(value=str(draft.get("tab_bar_height", 52))),
            "toolbar_height": tk.StringVar(value=str(draft.get("toolbar_height", 72))),
            "status_bar_height": tk.StringVar(value=str(draft.get("status_bar_height", 30))),
            "find_bar_height": tk.StringVar(value=str(draft.get("find_bar_height", 46))),
        }
        label(tabs_page, "Chrome heights (px before UI scaling)", bold=True).pack(anchor="w", pady=(18, 6))
        row = tk.Frame(tabs_page, bg=self.ui["bg"]); row.pack(fill="x")
        for key, text in (("app_bar_height", "App"), ("tab_bar_height", "Tabs"), ("toolbar_height", "Toolbar"), ("status_bar_height", "Status"), ("find_bar_height", "Find")):
            label(row, text).pack(side="left", padx=(0, 4)); entry(row, heights[key], width=5).pack(side="left", padx=(0, 14), ipady=3)

        # Behavior -----------------------------------------------------------
        homepage_var = tk.StringVar(value=str(self.preferences.get("homepage", START_URL)))
        search_var = tk.StringVar(value=str(self.preferences.get("search_url_template", "https://www.startpage.com/sp/search?query={query}")))
        startup_var = tk.StringVar(value=str(self.preferences.get("startup", "homepage")))
        newtab_var = tk.StringVar(value=str(self.preferences.get("new_tab", "blank")))
        zoom_var = tk.StringVar(value=f"{self._page_zoom_percent()}%")
        statusbar_var = tk.BooleanVar(value=bool(self.preferences.get("show_status_bar", True)))
        for text, var in (("Homepage", homepage_var), ("Search URL template", search_var)):
            label(behavior_page, text, bold=True).pack(anchor="w", pady=(5, 2))
            entry(behavior_page, var).pack(fill="x", ipady=5, pady=(0, 7))
        label(behavior_page, "Use {query} where the URL-encoded search terms should go.", muted=True).pack(anchor="w", pady=(0, 10))
        row = tk.Frame(behavior_page, bg=self.ui["bg"]); row.pack(fill="x", pady=5)
        label(row, "Startup", width=14).pack(side="left")
        ttk.Combobox(row, textvariable=startup_var, values=["homepage", "blank"], state="readonly", width=14).pack(side="left", padx=(0, 18))
        label(row, "New tab", width=10).pack(side="left")
        ttk.Combobox(row, textvariable=newtab_var, values=["blank", "homepage"], state="readonly", width=14).pack(side="left", padx=(0, 18))
        label(row, "Page zoom").pack(side="left")
        ttk.Combobox(row, textvariable=zoom_var, values=["75%", "80%", "90%", "100%", "110%", "125%", "150%", "175%", "200%"], width=8).pack(side="left", padx=(6, 0))
        check(behavior_page, "Show status bar", statusbar_var).pack(anchor="w", pady=(12, 3))

        # Advanced -----------------------------------------------------------
        window_width_var = tk.StringVar(value=str(draft.get("window_width", 1280)))
        window_height_var = tk.StringVar(value=str(draft.get("window_height", 840)))
        min_width_var = tk.StringVar(value=str(draft.get("window_min_width", 900)))
        min_height_var = tk.StringVar(value=str(draft.get("window_min_height", 600)))
        start_max_var = tk.BooleanVar(value=bool(draft.get("start_maximized", False)))
        label(advanced_page, "Initial window", bold=True).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(advanced_page, bg=self.ui["bg"]); row.pack(fill="x", pady=4)
        for text, var in (("Width", window_width_var), ("Height", window_height_var), ("Minimum width", min_width_var), ("Minimum height", min_height_var)):
            label(row, text).pack(side="left", padx=(0, 4)); entry(row, var, width=6).pack(side="left", padx=(0, 12), ipady=3)
        check(advanced_page, "Start maximized", start_max_var).pack(anchor="w", pady=8)
        label(advanced_page, "Recovery", bold=True).pack(anchor="w", pady=(18, 5))
        label(advanced_page, "If a custom layout hides too much UI, press Ctrl+Shift+Alt+R to reset only the interface. Browser data is untouched.", muted=True).pack(anchor="w")

        def int_value(var, default):
            try:
                return int(str(var.get()).strip())
            except Exception:
                return default

        def float_value(var, default):
            try:
                return float(str(var.get()).strip())
            except Exception:
                return default

        def collect_custom():
            custom = json.loads(json.dumps(draft))
            custom["preset"] = preset_var.get() or "Custom"
            custom["colors"] = {key: _valid_hex_color(color_vars[key].get(), UI_COLOR_DEFAULTS[key]) for key in UI_COLOR_DEFAULTS}
            custom["font_family"] = font_var.get().strip()
            custom["display_font_family"] = display_font_var.get().strip()
            custom["monospace_font_family"] = mono_font_var.get().strip()
            custom["font_size"] = int_value(font_size_var, 11)
            custom["menu_font_size"] = int_value(menu_font_size_var, 10)
            custom["tab_font_size"] = int_value(tab_font_size_var, 10)
            custom["toolbar_font_size"] = int_value(toolbar_font_size_var, 11)
            custom["density"] = density_var.get()
            custom["ui_scale"] = float_value(scale_var, 1.0)
            custom["animations"] = bool(animations_var.get())
            custom["window_control_style"] = window_control_style_var.get()
            custom["tab_style"] = tab_style_var.get()
            custom["show_toolbar"] = bool(show_toolbar_var.get())
            custom["toolbar_label_style"] = label_style_var.get()
            custom["show_site_info_button"] = bool(site_info_var.get())
            custom["show_bookmark_button"] = bool(bookmark_button_var.get())
            custom["toolbar_order"] = list(order)
            custom["toolbar_visible"] = {item: bool(visible_vars[item].get()) for item in TOOLBAR_ITEM_IDS}
            for key, var in bool_vars.items():
                custom[key] = bool(var.get())
            custom["tab_position"] = tab_position_var.get()
            custom["new_tab_button_position"] = new_tab_position_var.get()
            custom["tab_title_chars"] = int_value(tab_chars_var, 28)
            custom["tab_min_width"] = int_value(tab_min_width_var, 175)
            custom["tab_max_width"] = int_value(tab_max_width_var, 330)
            custom["window_corner_radius"] = int_value(window_radius_var, 24)
            custom["content_corner_radius"] = int_value(content_radius_var, 18)
            custom["control_corner_radius"] = int_value(control_radius_var, 16)
            for key, var in heights.items():
                custom[key] = int_value(var, DEFAULT_CUSTOMIZATION[key])
            custom["window_width"] = int_value(window_width_var, 1280)
            custom["window_height"] = int_value(window_height_var, 840)
            custom["window_min_width"] = int_value(min_width_var, 900)
            custom["window_min_height"] = int_value(min_height_var, 600)
            custom["start_maximized"] = bool(start_max_var.get())
            return _normalized_customization(custom)

        def load_custom_into_controls(custom):
            nonlocal draft, order
            draft = json.loads(json.dumps(_normalized_customization(custom)))
            preset_var.set(draft.get("preset", "Custom"))
            for key in UI_COLOR_DEFAULTS:
                color_vars[key].set(draft["colors"][key])
            font_var.set(draft.get("font_family", "")); display_font_var.set(draft.get("display_font_family", "")); mono_font_var.set(draft.get("monospace_font_family", ""))
            font_size_var.set(str(draft["font_size"])); menu_font_size_var.set(str(draft["menu_font_size"]))
            tab_font_size_var.set(str(draft["tab_font_size"])); toolbar_font_size_var.set(str(draft["toolbar_font_size"]))
            density_var.set(draft["density"]); scale_var.set(str(draft["ui_scale"])); animations_var.set(bool(draft["animations"]))
            window_control_style_var.set(draft.get("window_control_style", "traffic_lights")); tab_style_var.set(draft.get("tab_style", "soft"))
            show_toolbar_var.set(bool(draft["show_toolbar"])); label_style_var.set(draft["toolbar_label_style"])
            site_info_var.set(bool(draft["show_site_info_button"])); bookmark_button_var.set(bool(draft["show_bookmark_button"]))
            order = list(draft["toolbar_order"]); refresh_order()
            for item in TOOLBAR_ITEM_IDS:
                visible_vars[item].set(bool(draft["toolbar_visible"].get(item, True)))
            for key, var in bool_vars.items(): var.set(bool(draft[key]))
            tab_position_var.set(draft["tab_position"]); new_tab_position_var.set(draft["new_tab_button_position"]); tab_chars_var.set(str(draft["tab_title_chars"]))
            tab_min_width_var.set(str(draft["tab_min_width"])); tab_max_width_var.set(str(draft["tab_max_width"]))
            window_radius_var.set(str(draft["window_corner_radius"])); content_radius_var.set(str(draft["content_corner_radius"])); control_radius_var.set(str(draft["control_corner_radius"]))
            for key, var in heights.items(): var.set(str(draft[key]))
            window_width_var.set(str(draft["window_width"])); window_height_var.set(str(draft["window_height"]))
            min_width_var.set(str(draft["window_min_width"])); min_height_var.set(str(draft["window_min_height"])); start_max_var.set(bool(draft["start_maximized"]))

        def preview():
            self.preferences["customization"] = collect_custom()
            self.customization = self.preferences["customization"]
            self._apply_customization_runtime()
            self.status_var.set("Customization preview — Save to keep it")

        def export_preset():
            custom = collect_custom()
            path = filedialog.asksaveasfilename(parent=win, title="Export Tekzite customization", defaultextension=".json",
                                                filetypes=[("Tekzite customization", "*.json"), ("JSON", "*.json")],
                                                initialfile="tekzite-customization.json")
            if not path:
                return
            payload = {"format": "tekzite-customization", "version": 1, "browser_version": BROWSER_VERSION, "customization": custom}
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

        def import_preset():
            path = filedialog.askopenfilename(parent=win, title="Import Tekzite customization", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
            if not path:
                return
            try:
                preset_path = Path(path)
                if preset_path.stat().st_size > 1024 * 1024:
                    raise ValueError("customization preset is larger than 1 MiB")
                payload = json.loads(preset_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("customization preset must be a JSON object")
                preset_format = payload.get("format")
                if preset_format not in (None, "tekzite-customization"):
                    raise ValueError("unsupported customization preset format")
                custom = payload.get("customization", payload)
                if not isinstance(custom, dict):
                    raise ValueError("customization payload must be an object")
                load_custom_into_controls(custom)
                preview()
            except Exception as exc:
                self._show_message("error", "Customize Tekzite", f"Could not import customization:\n{exc}", parent=win)

        def reset_controls():
            load_custom_into_controls(DEFAULT_CUSTOMIZATION)
            preview()

        def save_close():
            custom = collect_custom()
            search_template = search_var.get().strip()
            if "{query}" not in search_template:
                self._show_message("error", "Customize Tekzite", "Search URL template must contain {query}.", parent=win)
                return
            self.preferences["customization"] = custom
            self.customization = custom
            self.preferences["homepage"] = (homepage_var.get().strip()[:32768] or START_URL)
            self.preferences["search_url_template"] = search_template
            self.preferences["startup"] = startup_var.get()
            self.preferences["new_tab"] = newtab_var.get()
            self.preferences["page_zoom_percent"] = _normalized_zoom_percent(zoom_var.get(), self._page_zoom_percent())
            self.preferences["show_status_bar"] = bool(statusbar_var.get())
            try:
                save_preferences(self.preferences)
            except Exception as exc:
                self._show_message("error", "Customize Tekzite", f"Could not save customization:\n{exc}", parent=win)
                return
            self._apply_customization_runtime()
            self._apply_chromium_zoom_to_all_tabs()
            self._schedule_chromium_zoom_apply(all_tabs=True)
            self.status_var.set("Customization saved for this profile")
            win.destroy()

        def cancel():
            self.preferences["customization"] = original_custom
            self.customization = original_custom
            self._apply_customization_runtime()
            win.destroy()

        footer = tk.Frame(win, bg=self.ui["bg"], padx=16, pady=12)
        footer.pack(fill="x")
        tk.Button(footer, text="Import…", command=import_preset, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=12, pady=7).pack(side="left")
        tk.Button(footer, text="Export…", command=export_preset, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=12, pady=7).pack(side="left", padx=6)
        tk.Button(footer, text="Reset", command=reset_controls, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=12, pady=7).pack(side="left", padx=(12, 0))
        tk.Button(footer, text="Cancel", command=cancel, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=14, pady=7).pack(side="right")
        tk.Button(footer, text="Save", command=save_close, bg=self.ui["accent"], fg="#ffffff", relief="flat", padx=18, pady=7).pack(side="right", padx=6)
        tk.Button(footer, text="Preview", command=preview, bg=self.ui["chrome_2"], fg=self.ui["text"], relief="flat", padx=14, pady=7).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", cancel)
        win.bind("<Escape>", lambda event: cancel())
        return "break"

    def _show_privacy_shield(self):
        win = self._new_animated_toplevel(self.root)
        win.title(f"Tekzite Privacy Shield — v{BROWSER_VERSION}")
        win.configure(bg=self.ui["bg"])
        win.transient(self.root)
        win.geometry("720x650")
        outer = tk.Frame(win, bg=self.ui["bg"], padx=22, pady=18)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="Live privacy status. Destinations are not stored here.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(9))).pack(anchor="w", pady=(0, 14))

        body = tk.Text(outer, bg=self.ui["field"], fg=self.ui["text"], insertbackground=self.ui["text"],
                       relief="flat", wrap="word", font=(self._ui_monospace_font_family, self._font_size(9)), padx=14, pady=12)
        body.pack(fill="both", expand=True)

        def yes(value):
            return "ACTIVE" if value else "OFF"

        def refresh():
            try:
                net = network_engine_debug(start=False)
            except Exception as exc:
                net = {"alive": False, "proxy": None, "error": str(exc)}
            try:
                stats = privacy_stats()
            except Exception:
                stats = {}
            prefs = self.preferences
            rows = [
                "TEKZITE PRIVACY CORE",
                "=" * 62,
                f"Privacy lockdown .......... {yes(prefs.get('privacy_lockdown', False))}",
                f"Tracker blocking .......... {yes(prefs.get('tracker_blocking_enabled', True))}",
                f"Tracking-param stripping .. {yes(prefs.get('strip_tracking_parameters', True))}",
                f"Cross-site referrer strip . {yes(prefs.get('strip_referrer', True))}",
                f"HTTPS-first ............... {yes(prefs.get('https_first', True))}",
                f"Third-party cookies ....... BLOCKED",
                f"GPC + DNT ................. SENT",
                f"WebRTC direct UDP ......... BLOCKED",
                f"QUIC ...................... DISABLED",
                f"Chromium built-in DoH ..... DISABLED",
                f"DNS prefetch/prediction ... DISABLED",
                f"Password/autofill cloud ... DISABLED",
                f"Permissions default ....... DENY (camera/mic/location/notifications/sensors)",
                f"Python localhost egress ... {yes(prefs.get('strict_python_loopback', True))}",
                f"Browsing-data clear exit .. {yes(prefs.get('clear_browsing_data_on_exit', True) or prefs.get('privacy_lockdown', False))}",
                f"Chromium profile storage .. {'TEMPORARY PROCESS PROFILE' if prefs.get('privacy_lockdown', False) else 'PERSISTENT PROFILE'}",
                f"History/session on disk ... {'NO' if prefs.get('privacy_lockdown', False) else 'USER SETTING'}",
                f"User extensions ........... {'DISABLED IN LOCKDOWN' if prefs.get('privacy_lockdown', False) else 'ALLOWED BY USER'}",
                "",
                "NETWORK BOUNDARY",
                "=" * 62,
                f"Local filtering proxy ..... {'RUNNING' if net.get('alive') else 'NOT STARTED'}",
                f"Proxy endpoint ............ {net.get('proxy') or 'starts with first webpage'}",
                "HTTPS inspection .......... NONE (TLS remains end-to-end)",
                "DNS route ................ Your Windows/router resolver; Tekzite does not force public DoH",
                "",
                "THIS SESSION",
                "=" * 62,
                f"Telemetry hosts blocked ... {int(stats.get('telemetry_blocked', 0))}",
                f"Tracker hosts blocked ..... {int(stats.get('trackers_blocked', 0))}",
                f"Ad hosts blocked .......... {int(stats.get('ads_blocked', 0))}",
                f"HTTP requests upgraded .... {int(stats.get('https_upgrades', 0))}",
                f"Tracking params removed ... {int(getattr(self, '_privacy_tracking_params_stripped', 0))}",
                "",
                "LIMIT",
                "=" * 62,
                "A website you visit still sees the public IP address of your network unless you use an upstream VPN/proxy/Tor layer.",
                "Tekzite minimizes browser leakage; it does not claim network anonymity by itself.",
            ]
            body.configure(state="normal")
            body.delete("1.0", "end")
            body.insert("1.0", "\n".join(rows))
            body.configure(state="disabled")

        footer = tk.Frame(outer, bg=self.ui["bg"]); footer.pack(fill="x", pady=(10, 0))
        tk.Button(footer, text="Local Ports", command=self._show_local_ports, bg=self.ui["chrome_2"], fg=self.ui["text"],
                  relief="flat", padx=14, pady=7).pack(side="left")
        tk.Button(footer, text="Refresh", command=refresh, bg=self.ui["accent"], fg="#ffffff",
                  relief="flat", padx=16, pady=7).pack(side="right")
        refresh()
        return "break"

    def _make_tekzite_default_browser(self, parent=None, refresh_callback=None):
        if os.name != "nt":
            self._show_message("info", "Default Browser", "Default-browser registration is available on Windows only.", parent=parent or self.root)
            return "break"
        try:
            _register_tekzite_default_browser()
            uri = _open_tekzite_default_apps_settings()
            self.status_var.set("Tekzite registered with Windows Default Apps — confirm Set default in Windows Settings")
            if callable(refresh_callback):
                try:
                    (parent or self.root).after(750, refresh_callback)
                except Exception:
                    pass
            return uri
        except Exception as exc:
            self._show_message(
                "error", "Default Browser",
                f"Tekzite could not register with Windows Default Apps:\n{exc}",
                parent=parent or self.root,
            )
            return "break"

    def show_preferences(self):
        # Remember who owned keyboard input before Settings opened. Frameless
        # Linux dialogs are modeless, so opening/closing Settings must never
        # strand focus away from both the omnibox and the Chromium page.
        try:
            _settings_previous_focus = self.root.focus_get()
        except Exception:
            _settings_previous_focus = None
        _settings_restore_address = bool(
            _settings_previous_focus is getattr(self, "address", None)
            or getattr(self, "_address_focus_active", False)
        )
        _settings_restore_page = bool(
            getattr(self, "_chromium_page_keyboard_active", False)
            or (
                getattr(self, "_embedded_mode", False)
                and not _settings_restore_address
            )
        )

        # Settings owns its final geometry because it intentionally occupies most
        # of the browser height. Delay automatic motion until that geometry is
        # established, otherwise the generic dialog animation can capture the
        # small requested widget size before the tall layout is applied.
        # Settings uses the same Tekzite-owned frameless dialog shell as every
        # other app dialog. Linux focus is repaired explicitly after mapping
        # instead of falling back to a second native window-manager title bar.
        win = self._new_animated_toplevel(
            self.root, auto_animate=False, branded=True
        )
        win.title(f"Tekzite Browser Settings — v{BROWSER_VERSION}")
        dialog_width = 620
        win.configure(bg=self.ui["bg"])
        win.transient(self.root)
        # v6.8: build Preferences while hidden, then size/center it from the
        # completed widget tree before exposing it. This avoids the v6.7
        # failure mode where a sizing exception could leave a 1-pixel dialog.
        win.withdraw()

        # Do not grab/focus the withdrawn shell. v6.8 shows, raises and
        # focuses the completed dialog only after its final geometry is known.

        # v10.5.38: Settings uses a fixed shell with a scrollable body. The
        # options can grow without forcing the whole dialog off-screen, while
        # Save/Cancel remain visible at the bottom at all times.
        shell = tk.Frame(win, bg=self.ui["bg"], padx=22, pady=18)
        shell.pack(fill="both", expand=True)
        tk.Label(shell, text="Customize Tekzite without editing configuration files.", fg=self.ui["muted"],
                 bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(9))).pack(anchor="w", pady=(0, 12))

        scroll_host = tk.Frame(shell, bg=self.ui["bg"])
        scroll_host.pack(fill="both", expand=True)
        settings_canvas = tk.Canvas(
            scroll_host, bg=self.ui["bg"], highlightthickness=0, bd=0,
            width=max(520, dialog_width - 70), height=980,
        )
        settings_scrollbar = tk.Scrollbar(
            scroll_host, orient="vertical", command=settings_canvas.yview,
            bg=self.ui["chrome_2"], activebackground=self.ui["accent"],
            troughcolor=self.ui["bg"], relief="flat", bd=0, width=12,
        )
        settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        settings_scrollbar.pack(side="right", fill="y", padx=(10, 0))
        settings_canvas.pack(side="left", fill="both", expand=True)

        outer = tk.Frame(settings_canvas, bg=self.ui["bg"])
        settings_window = settings_canvas.create_window((0, 0), window=outer, anchor="nw")

        def sync_settings_scrollregion(_event=None):
            try:
                settings_canvas.configure(scrollregion=settings_canvas.bbox("all"))
            except Exception:
                pass

        def fit_settings_body(event=None):
            try:
                width = int(event.width) if event is not None else int(settings_canvas.winfo_width())
                settings_canvas.itemconfigure(settings_window, width=max(1, width))
                settings_canvas.after_idle(sync_settings_scrollregion)
            except Exception:
                pass

        def scroll_settings(event):
            try:
                bbox = settings_canvas.bbox("all")
                if not bbox or (bbox[3] - bbox[1]) <= settings_canvas.winfo_height():
                    return None
                delta = int(getattr(event, "delta", 0) or 0)
                if delta:
                    units = -int(delta / 120)
                    if units == 0:
                        units = -1 if delta > 0 else 1
                    settings_canvas.yview_scroll(units * 3, "units")
                elif int(getattr(event, "num", 0) or 0) == 4:
                    settings_canvas.yview_scroll(-3, "units")
                elif int(getattr(event, "num", 0) or 0) == 5:
                    settings_canvas.yview_scroll(3, "units")
                return "break"
            except Exception:
                return None

        outer.bind("<Configure>", sync_settings_scrollregion, add="+")
        settings_canvas.bind("<Configure>", fit_settings_body, add="+")
        win.bind("<MouseWheel>", scroll_settings, add="+")
        win.bind("<Button-4>", scroll_settings, add="+")
        win.bind("<Button-5>", scroll_settings, add="+")

        homepage = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("homepage", START_URL))
        startup = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("startup", "homepage"))
        new_tab = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("new_tab", "blank"))
        renderer = tk.StringVar(value="chromium")
        chromium_presentation = tk.StringVar(value=getattr(self, "preferences", DEFAULT_PREFERENCES).get("chromium_presentation", "native"))
        auto_fallback = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("auto_chromium_fallback", True)))
        reuse_tabs = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("reuse_open_tabs", True)))
        omnibox_suggestions_enabled = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("omnibox_suggestions_enabled", True)))
        status_bar = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("show_status_bar", True)))
        network_diagnostics = tk.StringVar(value=str(getattr(self, "preferences", DEFAULT_PREFERENCES).get("network_diagnostics", "off")))
        strict_python_loopback = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("strict_python_loopback", True)))
        privacy_lockdown = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("privacy_lockdown", True)))
        tracker_blocking = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("tracker_blocking_enabled", True)))
        strip_tracking = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("strip_tracking_parameters", True)))
        strip_referrer = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("strip_referrer", True)))
        https_first = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("https_first", True)))
        clear_on_exit = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("clear_browsing_data_on_exit", True)))
        adblock_enabled = tk.BooleanVar(value=bool(getattr(self, "preferences", DEFAULT_PREFERENCES).get("adblock_enabled", True)))
        page_zoom = tk.StringVar(value=f"{self._page_zoom_percent()}%")
        website_color_scheme = tk.StringVar(value=self._website_color_scheme())
        sleeping_tabs_enabled = tk.BooleanVar(value=bool(self.preferences.get("sleeping_tabs_enabled", True)))
        sleeping_tabs_minutes = tk.StringVar(value=str(self.preferences.get("sleeping_tabs_minutes", 30)))
        download_prompt = tk.BooleanVar(value=bool(self.preferences.get("download_prompt", False)))
        update_repository = tk.StringVar(value=str(self.preferences.get("update_repository", "")))

        def section(title):
            tk.Label(outer, text=title, fg=self.ui["accent_hover"], bg=self.ui["bg"],
                     font=(self._ui_font_family, self._font_size(10), "bold")).pack(anchor="w", pady=(12, 6))
        def combo(var, values):
            box = ttk.Combobox(outer, textvariable=var, values=values, state="readonly")
            box.pack(fill="x", pady=(0, 6))
            return box

        section("Homepage")
        entry = tk.Entry(outer, highlightthickness=0, bd=0, textvariable=homepage, bg=self.ui["field"], fg=self.ui["text"],
                         insertbackground=self.ui["text"], relief="flat", font=(self._ui_font_family, self._font_size(10)))
        entry.pack(fill="x", ipady=7)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Show local address-bar suggestions and autocomplete",
                       variable=omnibox_suggestions_enabled, bg=self.ui["bg"], fg=self.ui["text"],
                       selectcolor=self.ui["field"], activebackground=self.ui["bg"],
                       activeforeground=self.ui["text"]).pack(anchor="w", pady=(9, 2))
        tk.Label(outer, text="Local suggestions only. Typing stays on this device.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8)),
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))

        quiet_mode = tk.BooleanVar(value=self.preferences.get("quiet_mode", False))
        restore_tabs = tk.BooleanVar(value=self.preferences.get("restore_tabs", True))
        section("Startup and tabs")
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Restore open tabs on restart (overrides startup choice)",
                       variable=restore_tabs, bg=self.ui["bg"], fg=self.ui["text"],
                       selectcolor=self.ui["field"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Quiet mode: hide debug/status controls and reduce animations",
                       variable=quiet_mode, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"]).pack(anchor="w", pady=3)
        combo(startup, ["homepage", "blank"])
        combo(new_tab, ["blank", "homepage"])
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Switch to an already-open tab instead of loading the same URL again",
                       variable=reuse_tabs, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Put inactive background tabs to sleep",
                       variable=sleeping_tabs_enabled, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        sleep_row = tk.Frame(outer, bg=self.ui["bg"]); sleep_row.pack(fill="x", pady=(0, 4))
        tk.Label(sleep_row, text="Sleep after", bg=self.ui["bg"], fg=self.ui["muted"]).pack(side="left")
        ttk.Combobox(sleep_row, textvariable=sleeping_tabs_minutes, values=("5","10","20","30","60","120"), state="readonly", width=8).pack(side="left", padx=8)
        tk.Label(sleep_row, text="minutes (pinned tabs never sleep)", bg=self.ui["bg"], fg=self.ui["muted"]).pack(side="left")

        section("Rendering engine")
        combo(renderer, ["chromium"])
        tk.Label(outer, text="Auto selects the best available renderer.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8))).pack(anchor="w")
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Automatically fall back to Chromium when native rendering fails",
                       variable=auto_fallback, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Chromium presentation", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, self._font_size(8))).pack(anchor="w", pady=(7, 1))
        combo(chromium_presentation, ["native", "software"] if os.name == "nt" else ["software"])
        tk.Label(outer, text="Native for normal use. Software is for diagnostics.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8))).pack(anchor="w")

        section("Privacy")
        tk.Label(outer, text="Privacy Core: telemetry off • GPC + DNT • third-party cookies blocked",
                 fg=self.ui["text"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(9))).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Privacy Lockdown: do not save history or open tabs",
                       variable=privacy_lockdown, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Block tracker and analytics hosts",
                       variable=tracker_blocking, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Remove tracking parameters from links",
                       variable=strip_tracking, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Remove Referer from requests",
                       variable=strip_referrer, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="HTTPS-first: upgrade HTTP when possible",
                       variable=https_first, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Restrict local Python connections",
                       variable=strict_python_loopback, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Allows only Tekzite proxy and Chromium control ports. Restart required.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8)), wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Label(outer, text="Camera, mic, location, notifications, sensors and autofill are off by default.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8)), wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Block ads",
                       variable=adblock_enabled, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Blocks known ad hosts. Restart required after changing this.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8)), wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Clear cookies, storage, cache and history on exit",
                       variable=clear_on_exit, bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="Network diagnostics", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, self._font_size(8))).pack(anchor="w", pady=(6, 1))
        combo(network_diagnostics, ["off", "errors", "full"])
        tk.Label(outer, text="Off is recommended. Full may log hosts and HTTP paths.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8))).pack(anchor="w")

        section("Default browser")
        tk.Label(outer, text="Register Tekzite for web links and HTML files.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8)),
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 5))
        default_browser_status_var = tk.StringVar(value="Checking Windows default browser…" if os.name == "nt" else "Default-browser detection is available on Windows only.")
        default_browser_status_label = tk.Label(
            outer, textvariable=default_browser_status_var, fg=self.ui["muted"], bg=self.ui["bg"],
            font=(self._ui_font_family, self._font_size(9), "bold"), wraplength=560, justify="left"
        )
        default_browser_status_label.pack(anchor="w", pady=(0, 7))
        default_browser_button = tk.Button(
            outer, text="Make Tekzite default browser…", highlightthickness=0,
            bg=self.ui["accent"], fg="#ffffff", activebackground=self.ui["accent_hover"],
            activeforeground="#ffffff", relief="flat", bd=0, padx=16, pady=7, cursor="hand2"
        )
        default_browser_button.pack(anchor="w", pady=(0, 4))

        def refresh_default_browser_status():
            try:
                if not win.winfo_exists():
                    return
                status = _tekzite_default_browser_status()
                if not status.get("supported"):
                    default_browser_status_var.set("Default-browser detection is available on Windows only.")
                    default_browser_button.configure(text="Make Tekzite default browser…", state="disabled", cursor="arrow")
                    return
                if status.get("is_default"):
                    default_browser_status_var.set("✓ Tekzite is your default browser for HTTP and HTTPS.")
                    default_browser_status_label.configure(fg=self.ui["accent_hover"])
                    default_browser_button.configure(text="Tekzite is the default browser", state="disabled", cursor="arrow")
                else:
                    http_ok = bool(status.get("http_default"))
                    https_ok = bool(status.get("https_default"))
                    if http_ok or https_ok:
                        missing = "HTTPS" if http_ok else "HTTP"
                        default_browser_status_var.set(f"Tekzite is only partially set as default. {missing} still uses another browser.")
                    else:
                        default_browser_status_var.set("Tekzite is not currently the default browser.")
                    default_browser_status_label.configure(fg=self.ui["muted"])
                    default_browser_button.configure(text="Make Tekzite default browser…", state="normal", cursor="hand2")
            except Exception:
                default_browser_status_var.set("Could not read the current Windows default-browser association.")
                default_browser_status_label.configure(fg=self.ui["muted"])
                default_browser_button.configure(text="Open Windows Default Apps…", state="normal", cursor="hand2")

        default_browser_button.configure(
            command=lambda: self._make_tekzite_default_browser(parent=win, refresh_callback=refresh_default_browser_status)
        )
        tk.Label(outer, text="Windows confirmation is required.",
                 fg=self.ui["muted_dim"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8)),
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))

        # Refresh immediately, whenever Settings regains focus after Windows
        # Default Apps, and briefly in the background in case the focus event is
        # swallowed by the frameless/native DWM window arrangement.
        refresh_default_browser_status()
        win.bind("<FocusIn>", lambda _event: refresh_default_browser_status(), add="+")
        def poll_default_browser_status():
            try:
                if not win.winfo_exists():
                    return
                refresh_default_browser_status()
                win.after(1200, poll_default_browser_status)
            except Exception:
                return
        win.after(1200, poll_default_browser_status)

        section("Downloads & updates")
        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Ask where to save each download (restart required)", variable=download_prompt,
                       bg=self.ui["bg"], fg=self.ui["text"], selectcolor=self.ui["field"],
                       activebackground=self.ui["bg"], activeforeground=self.ui["text"]).pack(anchor="w", pady=3)
        tk.Label(outer, text="GitHub repository for update checks (owner/repository)", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, self._font_size(8))).pack(anchor="w", pady=(4,1))
        tk.Entry(outer, highlightthickness=0, bd=0, textvariable=update_repository, bg=self.ui["field"], fg=self.ui["text"],
                 insertbackground=self.ui["text"], relief="flat").pack(fill="x", ipady=4, pady=(0,4))

        section("Interface")
        tk.Label(outer, text="Default page zoom", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, self._font_size(8))).pack(anchor="w", pady=(0, 1))
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
        tk.Label(outer, text="Preview is immediate. Save makes it permanent.",
                 fg=self.ui["muted"], bg=self.ui["bg"], font=(self._ui_font_family, self._font_size(8))).pack(anchor="w", pady=(0, 5))

        tk.Label(outer, text="Website color scheme", fg=self.ui["muted"], bg=self.ui["bg"],
                 font=(self._ui_font_family, self._font_size(8))).pack(anchor="w", pady=(6, 1))
        color_scheme_box = combo(website_color_scheme, ["system", "dark", "light"])
        original_color_scheme = self._website_color_scheme()

        def preview_website_color_scheme(_event=None):
            value = _normalized_website_color_scheme(
                website_color_scheme.get(), original_color_scheme
            )
            self.preferences["website_color_scheme"] = value
            try:
                self._executor.submit(self._apply_website_color_scheme_to_all_tabs)
            except Exception:
                pass
            self.status_var.set(f"Website color scheme preview: {value}")

        color_scheme_box.bind("<<ComboboxSelected>>", preview_website_color_scheme)
        tk.Label(
            outer,
            text="For sites that support light/dark themes.",
            fg=self.ui["muted"], bg=self.ui["bg"],
            font=(self._ui_font_family, self._font_size(8)),
            wraplength=560, justify="left",
        ).pack(anchor="w", pady=(0, 5))

        tk.Checkbutton(outer, highlightthickness=0, bd=0, relief="flat", text="Show status bar", variable=status_bar, bg=self.ui["bg"], fg=self.ui["text"],
                       selectcolor=self.ui["field"], activebackground=self.ui["bg"],
                       activeforeground=self.ui["text"]).pack(anchor="w", pady=3)

        def _force_browser_keyboard_target(target):
            """Return keyboard focus after an explicit Settings close action."""
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            try:
                # Prefer the cooperative Tk focus request on every platform.
                # Because this runs before the dialog is destroyed, Linux WMs
                # can transfer focus normally without a delayed activation.
                target.focus_set()
            except Exception:
                pass
            if sys.platform.startswith("linux"):
                try:
                    # Only fall back to a forced request while handling this
                    # direct user action, never from a timer/background callback.
                    if self.root.focus_get() is not target:
                        target.focus_force()
                except Exception:
                    pass
            else:
                try:
                    self.root.focus_force()
                    target.focus_force()
                except Exception:
                    pass

        def restore_browser_input_after_settings():
            """Return keyboard ownership to Tekzite after Settings closes."""
            try:
                if _settings_restore_address:
                    self._address_focus_active = True
                    self._chromium_page_keyboard_active = False
                    _force_browser_keyboard_target(self.address)
                    return
                if _settings_restore_page and getattr(self, "_embedded_mode", False):
                    self._address_focus_active = False
                    self._chromium_page_keyboard_active = True
                    target = (
                        self.edge_host
                        if getattr(self, "_chromium_dwm_mode", False)
                        else self.chromium_surface
                    )
                    _force_browser_keyboard_target(target)
                    return
                _force_browser_keyboard_target(self.root)
            except Exception:
                pass

        def schedule_browser_input_restore():
            # Linux focus must remain user-driven: the synchronous handoff above
            # is the only one. Delayed retries can steal focus from any desktop,
            # terminal or app the user clicks immediately after closing Settings.
            if sys.platform.startswith("linux"):
                return
            try:
                self.root.after(150, restore_browser_input_after_settings)
                self.root.after(320, restore_browser_input_after_settings)
            except Exception:
                restore_browser_input_after_settings()

        buttons = tk.Frame(shell, bg=self.ui["bg"])
        # Reserve the footer before the large scrollable body. Linux Tk honors
        # the canvas requested height more aggressively than Windows; packing
        # the footer last could push Save/Cancel below the visible window.
        buttons.pack(fill="x", side="bottom", pady=(14, 0), before=scroll_host)
        def save_and_close():
            # Keep persistence separate from live runtime application. On Linux
            # the Chromium software compositor can be busy when Settings closes;
            # a live-apply failure must never make a successful disk save look
            # like the Save button did nothing.
            try:
                selected_zoom = _normalized_zoom_percent(page_zoom.get(), original_zoom)
                try:
                    sleeping_minutes = max(5, min(240, int(sleeping_tabs_minutes.get() or 30)))
                except Exception:
                    sleeping_minutes = 30
                presentation_value = str(chromium_presentation.get() or "").strip()
                if os.name != "nt":
                    # Linux preview always uses the CDP software compositor.
                    presentation_value = "software"
                elif presentation_value not in {"native", "software"}:
                    presentation_value = "native"

                self.preferences.update({
                    "homepage": homepage.get().strip() or START_URL,
                    "startup": startup.get(),
                    "restore_tabs": bool(restore_tabs.get()),
                    "quiet_mode": bool(quiet_mode.get()),
                    "new_tab": new_tab.get(),
                    "renderer": "chromium",
                    "chromium_presentation": presentation_value,
                    "auto_chromium_fallback": bool(auto_fallback.get()),
                    "reuse_open_tabs": bool(reuse_tabs.get()),
                    "omnibox_suggestions_enabled": bool(omnibox_suggestions_enabled.get()),
                    "show_status_bar": bool(status_bar.get()),
                    "network_diagnostics": network_diagnostics.get(),
                    "strict_python_loopback": bool(strict_python_loopback.get()),
                    "privacy_lockdown": bool(privacy_lockdown.get()),
                    "tracker_blocking_enabled": bool(tracker_blocking.get()),
                    "strip_tracking_parameters": bool(strip_tracking.get()),
                    "strip_referrer": bool(strip_referrer.get()),
                    "https_first": bool(https_first.get()),
                    "clear_browsing_data_on_exit": bool(clear_on_exit.get()),
                    "adblock_enabled": bool(adblock_enabled.get()),
                    "page_zoom_percent": selected_zoom,
                    "website_color_scheme": _normalized_website_color_scheme(website_color_scheme.get()),
                    "sleeping_tabs_enabled": bool(sleeping_tabs_enabled.get()),
                    "sleeping_tabs_minutes": sleeping_minutes,
                    "download_prompt": bool(download_prompt.get()),
                    "update_repository": update_repository.get().strip(),
                })
                save_preferences(self.preferences)
            except Exception as exc:
                self._show_message("error", "Tekzite Settings", f"Could not save preferences:\n{exc}", parent=win)
                return

            # Launch-time settings are exported immediately so subsequent helper
            # starts use the saved values even if a best-effort live refresh
            # encounters a renderer-specific problem.
            os.environ["TEKZITE_NETWORK_LOG_LEVEL"] = str(self.preferences.get("network_diagnostics", "off"))
            os.environ["TEKZITE_ADBLOCK_ENABLED"] = "1" if self.preferences.get("adblock_enabled", True) else "0"
            os.environ["TEKZITE_PRIVACY_LOCKDOWN"] = "1" if self.preferences.get("privacy_lockdown", True) else "0"
            os.environ["TEKZITE_TRACKER_BLOCKING"] = "1" if self.preferences.get("tracker_blocking_enabled", True) else "0"
            os.environ["TEKZITE_STRIP_REFERRER"] = "1" if self.preferences.get("strip_referrer", True) else "0"
            os.environ["TEKZITE_HTTPS_FIRST"] = "1" if self.preferences.get("https_first", True) else "0"
            os.environ["TEKZITE_DOWNLOAD_PROMPT"] = "1" if self.preferences.get("download_prompt", False) else "0"

            # Once the atomic save verifies, close Settings right away. Runtime
            # application happens on the Tk idle queue so a Linux CDP hiccup
            # cannot strand the modal dialog after a successful save.
            self.status_var.set("Preferences saved - restart Tekzite to apply network/privacy/download launch changes")
            try:
                win.grab_release()
            except Exception:
                pass
            # Hand focus back while the Settings X window still exists. If the
            # focused override-redirect window is destroyed first, XWayland can
            # leave keyboard focus on None and later Tk focus_set() calls become
            # purely internal until another WM activation occurs.
            restore_browser_input_after_settings()
            win.destroy()
            schedule_browser_input_restore()

            def apply_saved_preferences_runtime():
                live_errors = []
                try:
                    self._apply_preferences_runtime()
                except Exception as exc:
                    live_errors.append(f"preferences: {exc}")
                try:
                    self._apply_chromium_zoom_to_all_tabs()
                    self._schedule_chromium_zoom_apply(all_tabs=True)
                except Exception as exc:
                    live_errors.append(f"zoom: {exc}")
                try:
                    self._apply_website_color_scheme_to_all_tabs()
                except Exception as exc:
                    live_errors.append(f"website color scheme: {exc}")
                try:
                    self._schedule_sleeping_tabs(1000)
                except Exception as exc:
                    live_errors.append(f"sleeping tabs: {exc}")
                if live_errors:
                    self.status_var.set(
                        "Preferences saved - some live changes will apply after restart"
                    )

            try:
                self.root.after_idle(apply_saved_preferences_runtime)
            except Exception:
                # Preferences are already durably saved. A restart applies every
                # launch-time setting even if the UI is shutting down right now.
                pass
        def cancel_preferences():
            # Live zoom selection is only a preview until Save. Restore the
            # authoritative value when the dialog is cancelled.
            if self._page_zoom_percent() != original_zoom:
                self.preferences["page_zoom_percent"] = original_zoom
                self._apply_chromium_zoom_to_all_tabs()
                self._schedule_chromium_zoom_apply(all_tabs=True)
            if self._website_color_scheme() != original_color_scheme:
                self.preferences["website_color_scheme"] = original_color_scheme
                try:
                    self._executor.submit(self._apply_website_color_scheme_to_all_tabs)
                except Exception:
                    pass
            try:
                win.grab_release()
            except Exception:
                pass
            restore_browser_input_after_settings()
            win.destroy()
            schedule_browser_input_restore()

        tk.Button(buttons, text="Cancel", command=cancel_preferences, bg=self.ui["chrome_2"], fg=self.ui["text"],
                  relief="flat", bd=0, highlightthickness=0, padx=16, pady=7).pack(side="right")
        tk.Button(buttons, text="Save", command=save_and_close, bg=self.ui["accent"], fg="#ffffff",
                  relief="flat", bd=0, highlightthickness=0, padx=20, pady=7).pack(side="right", padx=(0, 8))
        def fit_and_center_preferences():
            # v10.5.38: Settings has one authoritative geometry calculation.
            # Use Tk screen coordinates for both sizing and placement, then
            # re-assert the exact same geometry after the frameless window maps.
            # This avoids size drift from DPI conversion, header insertion and
            # Windows' first-map negotiation racing each other.
            try:
                # Settings is frameless on every platform and therefore always
                # receives Tekzite's in-window title/header controls.
                self._apply_about_style_to_dialog(win)
                try:
                    close_button = getattr(win, "_tekzite_dialog_close_button", None)
                    if close_button is not None:
                        close_button.configure(command=cancel_preferences)
                except Exception:
                    pass
                win.update_idletasks()

                screen_w = max(1, int(win.winfo_screenwidth()))
                screen_h = max(1, int(win.winfo_screenheight()))
                requested_w = max(dialog_width, int(shell.winfo_reqwidth()) + 2)
                # Keep a predictable large footprint on every open. 88% leaves
                # breathing room around the frameless shell while 1120 remains
                # the cap on tall displays.
                requested_h = min(1120, max(720, int(round(screen_h * 0.88))))
                dialog_w = min(requested_w, max(560, screen_w - 64))
                dialog_h = min(requested_h, max(620, screen_h - 64))

                # v10.5.39: Settings and every other Tekzite dialog now share
                # the same true screen-center placement instead of mixing
                # browser-relative and Windows-default positions.
                centered = self._screen_center_geometry(win, dialog_w, dialog_h, 16)
                match = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", centered)
                if not match:
                    raise ValueError("could not resolve screen-centered Settings geometry")
                dialog_w, dialog_h, x, y = map(int, match.groups())
            except Exception:
                dialog_w, dialog_h = dialog_width, 820
                x, y = 40, 40

            final_geometry = f"{dialog_w}x{dialog_h}+{x}+{y}"

            def enforce_final_geometry():
                try:
                    if win.winfo_exists():
                        win.geometry(final_geometry)
                except Exception:
                    pass

            try:
                win.resizable(False, False)
                win.geometry(final_geometry)
                win.update_idletasks()
                win.deiconify()
                # Windows can renegotiate an overrideredirect Toplevel on its
                # first map. Reapply immediately before animation and once after
                # the animation has settled so every opening lands identically.
                enforce_final_geometry()
                win.lift()
                if os.name == "nt":
                    win.attributes("-topmost", True)
                self._animate_toplevel_in(win, 155, slide=14)
                win.after(190, enforce_final_geometry)
                win.after(360, enforce_final_geometry)
                if os.name == "nt":
                    win.after(390, lambda: win.winfo_exists() and win.attributes("-topmost", False))
                else:
                    # The Settings command itself is the user gesture. Ask Tk
                    # cooperatively for entry focus now; never queue a later
                    # forced activation that can race another Linux application.
                    try:
                        entry.focus_set()
                    except Exception:
                        pass
            except Exception:
                try:
                    win.deiconify()
                    enforce_final_geometry()
                    win.lift()
                except Exception:
                    pass
            # Settings is intentionally modeless. A Tk grab here can leave the
            # frameless Linux root unable to receive keyboard input after the
            # dialog closes, and it also prevents typing in a webpage while
            # Settings is open.
            if os.name == "nt":
                try:
                    win.focus_force()
                except Exception:
                    pass

        win.after_idle(fit_and_center_preferences)
        win.protocol("WM_DELETE_WINDOW", cancel_preferences)

    def _raise_toplevel_above_dwm(self, win, hold_ms=420):
        """Force an app dialog above the separate native DWM presentation HWND.

        Tk ``lift``/``-topmost`` is usually enough, but the Chromium page is
        mirrored through a raw owned Win32 popup.  Resolve the real Tk wrapper
        HWND and use SetWindowPos so the dialog wins the native z-order race too.
        The TOPMOST state is temporary; after the first visible frame it returns
        to normal app-owned ordering.
        """
        try:
            win.update_idletasks()
            win.deiconify()
            win.lift()
        except Exception:
            pass
        if os.name != "nt":
            # Linux has no Tekzite DWM presenter to outrank. Do not use
            # focus_force() or temporary topmost here: across Linux window
            # managers those activation requests can behave like a keyboard grab.
            return True
        try:
            win.focus_force()
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            GA_ROOT = 2
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            raw = int(win.winfo_id())
            hwnd = int(user32.GetAncestor(wintypes.HWND(raw), GA_ROOT) or raw)
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, flags)
            win.attributes("-topmost", True)

            def release_native_topmost(w=win, native_hwnd=hwnd):
                try:
                    if not w.winfo_exists():
                        return
                    user32.SetWindowPos(wintypes.HWND(native_hwnd), wintypes.HWND(HWND_NOTOPMOST), 0, 0, 0, 0, flags)
                    w.attributes("-topmost", False)
                    w.lift()
                except Exception:
                    pass
            win.after(max(160, int(hold_ms)), release_native_topmost)
            return True
        except Exception:
            try:
                win.attributes("-topmost", True)
                win.after(max(160, int(hold_ms)), lambda w=win: w.winfo_exists() and w.attributes("-topmost", False))
            except Exception:
                pass
            return False

    def _show_about(self):
        """Open a real, reusable About window that always appears above DWM.

        Earlier builds routed Help -> About Tekzite through the generic modal
        message helper.  Because the webpage is presented by a separate native
        DWM popup, that small modal could end up visually behind the page even
        though it had the Tk grab, making About look as if it did nothing.
        Keep About as a normal Tekzite-owned animated toplevel and explicitly
        raise it above the presentation surface.
        """
        existing = getattr(self, "_about_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify()
                self._raise_toplevel_above_dwm(existing, hold_ms=420)
                return existing
        except Exception:
            self._about_window = None

        win = self._new_animated_toplevel(self.root, duration=165, slide=14, branded=False)
        self._about_window = win
        # Build and size About while withdrawn. This guarantees that neither Tk
        # nor the DWM popup can expose an unpositioned/1x1 first frame.
        try:
            win.withdraw()
        except Exception:
            pass
        win.title("About Tekzite")
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(bg=self.ui["bg"])

        def clear_about_ref(event=None):
            try:
                if event is None or event.widget is win:
                    if getattr(self, "_about_window", None) is win:
                        self._about_window = None
            except Exception:
                pass

        win.bind("<Destroy>", clear_about_ref, add="+")
        win.bind("<Escape>", lambda _e: win.destroy())

        outer = tk.Frame(win, bg=self.ui["bg"], padx=28, pady=24)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=self.ui["bg"])
        header.pack(fill="x")
        logo = tk.Canvas(header, width=54, height=54, bg=self.ui["bg"], highlightthickness=0, bd=0)
        logo.pack(side="left", padx=(0, 16))
        logo.create_rectangle(4, 4, 50, 50, fill=self.ui["accent"], outline=self.ui["accent_hover"], width=1)
        logo.create_text(27, 27, text="T", fill="#ffffff",
                         font=(self._ui_display_font_family, self._font_size(20), "bold"))

        title_col = tk.Frame(header, bg=self.ui["bg"])
        title_col.pack(side="left", fill="x", expand=True)
        about_title = tk.Label(title_col, text="Tekzite Browser", bg=self.ui["bg"], fg=self.ui["text"],
                               font=(self._ui_display_font_family, self._font_size(18), "bold"), anchor="w")
        about_title.pack(fill="x")
        about_version = tk.Label(title_col, text=f"Version {BROWSER_VERSION}", bg=self.ui["bg"], fg=self.ui["accent_hover"],
                                 font=(self._ui_font_family, self._font_size(10)), anchor="w")
        about_version.pack(fill="x", pady=(2, 0))
        top_close = tk.Button(
            header, text="×", command=win.destroy,
            bg=self.ui["bg"], fg=self.ui["muted"],
            activebackground=self.ui["chrome_hover"], activeforeground=self.ui["text"],
            relief="flat", bd=0, highlightthickness=0, cursor="hand2",
            font=(self._ui_display_font_family, self._font_size(15)), padx=10, pady=4,
        )
        top_close.pack(side="right", padx=(14, 0))
        self._bind_frameless_dialog_drag(
            win, outer, header, logo, title_col, about_title, about_version
        )

        tk.Frame(outer, bg=self.ui["border_soft"], height=1).pack(fill="x", pady=(20, 18))

        mode = "Private Window" if self._private_mode else (
            "Privacy Lockdown" if self.preferences.get("privacy_lockdown", True) else "Standard profile"
        )
        details = (
            "Chromium-rendered Tekzite browser.\n\n"
            f"Mode: {mode}\n"
            f"Profile: {getattr(self, '_profile_name', 'Default')}\n"
            "Renderer: Chromium\n"
            "Platform: Windows 10/11"
        )
        tk.Label(outer, text=details, bg=self.ui["bg"], fg=self.ui["muted"],
                 font=(self._ui_font_family, self._font_size(10)), justify="left",
                 anchor="w", wraplength=500).pack(fill="x")

        footer = tk.Frame(outer, bg=self.ui["bg"])
        footer.pack(fill="x", pady=(24, 0))

        def copy_about_info():
            info = (
                f"Tekzite Browser v{BROWSER_VERSION}\n"
                f"Mode: {mode}\n"
                f"Profile: {getattr(self, '_profile_name', 'Default')}\n"
                "Renderer: Chromium + Windows DWM"
            )
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(info)
                self.root.update_idletasks()
                self.status_var.set("About information copied")
            except Exception:
                pass

        tk.Button(footer, text="Copy info", command=copy_about_info,
                  bg=self.ui["chrome_2"], fg=self.ui["text"],
                  activebackground=self.ui["chrome_hover"], activeforeground=self.ui["text"],
                  relief="flat", bd=0, padx=16, pady=8, cursor="hand2").pack(side="left")
        tk.Button(footer, text="Check for updates", command=self._check_for_updates,
                  bg=self.ui["chrome_2"], fg=self.ui["text"],
                  activebackground=self.ui["chrome_hover"], activeforeground=self.ui["text"],
                  relief="flat", bd=0, padx=16, pady=8, cursor="hand2").pack(side="left", padx=(8, 0))
        close_btn = tk.Button(footer, text="Close", command=win.destroy,
                              bg=self.ui["accent"], fg="#ffffff",
                              activebackground=self.ui["accent_hover"], activeforeground="#ffffff",
                              relief="flat", bd=0, padx=22, pady=8, cursor="hand2")
        close_btn.pack(side="right")

        win.update_idletasks()
        width = max(520, int(outer.winfo_reqwidth()) + 12)
        height = max(330, int(outer.winfo_reqheight()) + 8)
        try:
            px, py = int(self.root.winfo_rootx()), int(self.root.winfo_rooty())
            pw, ph = int(self.root.winfo_width()), int(self.root.winfo_height())
            x = px + max(0, (pw - width) // 2)
            y = py + max(0, (ph - height) // 2)
            win.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            win.geometry(f"{width}x{height}")

        # DWM presentation is a separate native owned popup. Use Win32 z-order
        # directly as well as Tk so About cannot be hidden behind the webpage.
        self._raise_toplevel_above_dwm(win, hold_ms=520)
        try:
            close_btn.focus_set()
        except Exception:
            pass
        return win

    def navigate(self):
        # v4.83: pressing Enter/Go commits the omnibox. Do not leave its
        # cross-window focus guard latched while the Chromium page loads.
        url = self.url_var.get()
        self._remember_omnibox_input(url)
        self._release_address_focus_for_navigation()
        self.navigate_to(
            url,
            add_history=True,
        )

    def navigate_to(self, url, add_history=True, reuse_existing=True):
        """Navigate using Chromium only. Tekzite no longer has a web renderer."""
        # Do not retire a just-closed renderer while the next page is starting.
        self._defer_closed_target_retirement(1800)
        url = self.normalize_url(url)
        if self.preferences.get("strip_tracking_parameters", True):
            url, removed = strip_tracking_parameters(url)
            if removed:
                self._privacy_tracking_params_stripped += int(removed)
                self.status_var.set(f"Privacy Shield removed {removed} tracking parameter{'s' if removed != 1 else ''}")
        if self.preferences.get("https_first", True):
            url = upgrade_to_https(url)
        url = self.apply_site_compatibility(url)

        active = self._active_tab()
        previous_url = str(active.get("url") or "") if active is not None else ""
        if self._maybe_start_google_auth_handoff(url, previous_url, active):
            return
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
        window = self._new_animated_toplevel(self.root)
        window.title(f"Tekzite {title}")
        window.geometry(geometry)

        frame = tk.Frame(window)
        frame.pack(fill="both", expand=True)

        text = tk.Text(
            frame,
            wrap=wrap,
            font=(self._ui_monospace_font_family, self._font_size(9)),
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
        add("TEKZITE", "\n".join([
            f"version: {BROWSER_VERSION}",
            "web_engine: Chromium only",
            "presentation: DWM/native Chromium",
            "dwm_keyboard_sink_kind: tk-native-lazy",
            f"dwm_keyboard_sink_hwnd: {getattr(self, '_dwm_keyboard_sink_hwnd', None)}",
            f"dwm_keyboard_sink_focused: {getattr(self, '_dwm_keyboard_sink_focused', False)}",
            f"dwm_keyboard_sink_create_count: {getattr(self, '_dwm_keyboard_sink_create_count', 0)}",
            f"dwm_keyboard_sink_focus_count: {getattr(self, '_dwm_keyboard_sink_focus_count', 0)}",
            f"dwm_keyboard_sink_messages: {getattr(self, '_dwm_keyboard_sink_messages', 0)}",
            f"dwm_keyboard_sink_chars: {getattr(self, '_dwm_keyboard_sink_chars', 0)}",
            f"dwm_keyboard_sink_last: {getattr(self, '_dwm_keyboard_sink_last', None)}",
            f"dwm_keyboard_poll_active: {getattr(self, '_dwm_keyboard_poll_active', False)}",
            f"dwm_keyboard_poll_foreground: {getattr(self, '_dwm_keyboard_poll_foreground', False)}",
            f"dwm_keyboard_poll_events: {getattr(self, '_dwm_keyboard_poll_events', 0)}",
            f"dwm_keyboard_poll_chars: {getattr(self, '_dwm_keyboard_poll_chars', 0)}",
            f"dwm_keyboard_poll_last: {getattr(self, '_dwm_keyboard_poll_last', None)}",
            f"dwm_keyboard_poll_error: {getattr(self, '_dwm_keyboard_poll_error', None)}",
        ]))
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
            self._show_message("error", 
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
        window = self._new_animated_toplevel(self.root)
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
            fg=self.ui["muted"], font=(self._ui_font_family, self._font_size(9)), padx=12
        ).pack(side="left")

        find_var = tk.StringVar()
        find_entry = tk.Entry(
            toolbar, textvariable=find_var, bg=self.ui["field"],
            fg=self.ui["text"], insertbackground=self.ui["text"],
            relief="flat", bd=0, font=(self._ui_font_family, self._font_size(9))
        )
        find_entry.pack(side="left", fill="x", expand=True, padx=(8, 6), pady=8)

        body = tk.Frame(window, bg=self.ui["bg"])
        body.pack(fill="both", expand=True)
        yscroll = tk.Scrollbar(body, orient="vertical")
        yscroll.pack(side="right", fill="y")
        xscroll = tk.Scrollbar(body, orient="horizontal")
        xscroll.pack(side="bottom", fill="x")
        text = tk.Text(
            body, wrap="none", font=(self._ui_monospace_font_family, self._font_size(10)),
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
            font=(self._ui_font_family, self._font_size(8)), padx=10, pady=4
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
        # WM_CLOSE, a restart request and a keyboard shortcut can converge on
        # shutdown in the same UI turn. Teardown is intentionally idempotent.
        if getattr(self, "_closing", False):
            return True
        if not getattr(self, "_private_mode", False):
            try:
                self._save_session()
                write_json(self._state_directory / "history.json", [] if self.preferences.get("clear_browsing_data_on_exit", True) else self.visits)
            except OSError as exc:
                if not self._ask_yes_no("Save browser state", f"Could not save browser state:\n{exc}\n\nClose anyway?", parent=self.root):
                    self._restart_after_close = False
                    return False
        self._closing = True
        try:
            if self._checkpoint_job is not None:
                self.root.after_cancel(self._checkpoint_job)
        except Exception:
            pass
        try:
            if self._page_state_after_id is not None:
                self.root.after_cancel(self._page_state_after_id)
        except Exception:
            pass
        try:
            self._hide_omnibox_suggestions()
        except Exception:
            pass
        # Hundreds of small after() callbacks drive animation, frame polling,
        # input coalescing and recovery. Cancel them before destroying native
        # windows so none can wake mid-teardown and touch a dead HWND/Tk widget.
        self._cancel_all_tk_after_jobs()
        self._navigation_generation += 1
        try:
            close_embedded_chromium(
                clear_profile=bool(
                    getattr(self, "_private_mode", False)
                    or self.preferences.get("privacy_lockdown", True)
                    or self.preferences.get("clear_browsing_data_on_exit", True)
                ),
                # v10.5.69: let Chromium durably commit cookie/storage changes
                # such as a fresh YouTube sign-out before Tekzite exits.
                graceful=True,
                timeout=6.0,
            )
        except Exception:
            pass
        try:
            try:
                self._chromium_input_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            try:
                self._chromium_hover_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            try:
                self._chromium_cursor_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            try:
                self._chromium_scroll_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            try:
                self._tab_switch_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._executor.shutdown(wait=False, cancel_futures=True)
        finally:
            try:
                self._stop_dwm_keyboard_poll()
            except Exception:
                pass
            try:
                sink = getattr(self, "_dwm_keyboard_sink_widget", None)
                if sink is not None:
                    sink.destroy()
                self._dwm_keyboard_sink_widget = None
                self._dwm_keyboard_sink_hwnd = None
                self._dwm_keyboard_sink_focused = False
            except Exception:
                pass
            try:
                if self._dwm_host is not None and os.name == "nt":
                    import ctypes
                    from ctypes import wintypes
                    ctypes.WinDLL("user32", use_last_error=True).DestroyWindow(wintypes.HWND(int(self._dwm_host)))
            except Exception:
                pass
            for temp_profile in (getattr(self, "_private_profile_dir", None), getattr(self, "_privacy_profile_dir", None)):
                if temp_profile:
                    try:
                        removed = remove_profile_tree(temp_profile)
                        if not removed:
                            self._write_stability_log(
                                "Private profile cleanup warning",
                                f"Temporary profile remained after retry cleanup: {temp_profile}",
                            )
                    except Exception as exc:
                        self._write_stability_log(
                            "Private profile cleanup error",
                            f"{type(exc).__name__}: {exc}",
                        )
            restart_after_close = bool(getattr(self, "_restart_after_close", False))
            restart_private = bool(getattr(self, "_private_mode", False))
            try:
                self.root.destroy()
            except Exception as exc:
                self._write_stability_log("Tk destroy error", f"{type(exc).__name__}: {exc}")
            if restart_after_close:
                try:
                    self._spawn_browser_process(private=restart_private)
                except Exception:
                    pass
        return True

    def run(self):
        try:
            self.root.after_idle(self._animate_main_window_in)
        except Exception:
            pass
        self.root.mainloop()


if __name__ == "__main__":
    BrowserApp().run()

