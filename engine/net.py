from functools import lru_cache
from urllib.request import Request, urlopen, ProxyHandler, build_opener
from urllib.parse import unquote_to_bytes
from http.cookiejar import CookieJar
import base64
import io
import os
import shutil
import subprocess
import tempfile
import json
import socket
import time
import sys
import atexit
import threading
from pathlib import Path
from urllib.request import urlopen as _stdlib_urlopen
from urllib.parse import urlsplit


_ORIGINAL_URLOPEN = urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)

DOCUMENT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
    "Sec-GPC": "1",
}

SUBRESOURCE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Sec-GPC": "1",
}

DOCUMENT_TIMEOUT = 15
SUBRESOURCE_TIMEOUT = 6

# One cookie jar for the browser session. urllib follows HTTP redirects for us,
# but does not persist cookies between separate urlopen() calls by itself.
_COOKIE_JAR = CookieJar()

# v4.34: one network process for both Tekzite's native renderer and Chromium.
_NETWORK_ENGINE = None
_NETWORK_OPENER = None
_NETWORK_ENGINE_LOG_HANDLE = None


def _network_engine_root():
    return Path(__file__).resolve().parent.parent



TEKZITE_ZOOM_EXTENSION_ID = "afhkpeiilpolfogelgpkdijgnmofdiho"

def _zoom_extension_dir():
    return (_network_engine_root() / "chromium_zoom_extension").resolve()

def _network_engine_state_dir():
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = Path(root) / "Tekzite Browser" / "Network Engine"
    else:
        root = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        path = Path(root) / "tekzite-browser" / "network-engine"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wait_tcp_port(host, port, process, timeout=8.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Tekzite Network Engine exited with code {process.returncode}")
        try:
            with socket.create_connection((host, int(port)), timeout=0.25):
                return
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    raise RuntimeError("Tekzite Network Engine did not become ready") from last


def _stop_network_engine():
    global _NETWORK_ENGINE, _NETWORK_OPENER, _NETWORK_ENGINE_LOG_HANDLE
    state = _NETWORK_ENGINE
    _NETWORK_ENGINE = None
    _NETWORK_OPENER = None
    if state:
        proc = state.get("process")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    if _NETWORK_ENGINE_LOG_HANDLE is not None:
        try:
            _NETWORK_ENGINE_LOG_HANDLE.close()
        except Exception:
            pass
        _NETWORK_ENGINE_LOG_HANDLE = None


atexit.register(_stop_network_engine)


def ensure_network_engine():
    """Start/reuse Tekzite's loopback network process and return its state."""
    global _NETWORK_ENGINE, _NETWORK_OPENER, _NETWORK_ENGINE_LOG_HANDLE
    if _NETWORK_ENGINE:
        proc = _NETWORK_ENGINE.get("process")
        if proc is not None and proc.poll() is None:
            return _NETWORK_ENGINE
        _NETWORK_ENGINE = None
        _NETWORK_OPENER = None

    host = "127.0.0.1"
    port = _free_loopback_port()
    root = _network_engine_root()
    exe = root / "tekzite-network.exe"
    script = root / "tekzite_network.py"
    if exe.is_file():
        command = [str(exe), "--host", host, "--port", str(port)]
        mode = "exe"
    elif script.is_file():
        command = [sys.executable, str(script), "--host", host, "--port", str(port)]
        mode = "python"
    else:
        raise RuntimeError("Tekzite Network Engine is missing")

    state_dir = _network_engine_state_dir()
    log_path = state_dir / "network.jsonl"
    log_level = str(os.environ.get("TEKZITE_NETWORK_LOG_LEVEL", "off")).strip().lower()
    if log_level not in {"off", "errors", "full"}:
        log_level = "off"
    # Privacy-first: do not retain connection history unless explicitly enabled.
    if log_level == "off":
        try:
            log_path.unlink(missing_ok=True)
        except Exception:
            pass
        log_handle = open(os.devnull, "w", encoding="utf-8")
    else:
        log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
    command += ["--log-level", log_level]
    adblock_enabled = str(os.environ.get("TEKZITE_ADBLOCK_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if not adblock_enabled:
        command.append("--disable-adblock")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    try:
        _wait_tcp_port(host, port, proc)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        log_handle.close()
        raise

    proxy_url = f"http://{host}:{port}"
    # Environment variables also cover code paths using urllib's default opener.
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url
    no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    local_tokens = [x.strip() for x in no_proxy.split(",") if x.strip()]
    for token in ("127.0.0.1", "localhost", "::1"):
        if token not in local_tokens:
            local_tokens.append(token)
    os.environ["NO_PROXY"] = ",".join(local_tokens)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    _NETWORK_OPENER = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    _NETWORK_ENGINE_LOG_HANDLE = log_handle
    _NETWORK_ENGINE = {
        "process": proc,
        "host": host,
        "port": port,
        "proxy_url": proxy_url,
        "mode": mode,
        "command": command,
        "log_path": str(log_path),
    }
    return _NETWORK_ENGINE


def network_engine_debug():
    state = ensure_network_engine()
    proc = state.get("process")
    return {
        "mode": state.get("mode"),
        "pid": getattr(proc, "pid", None),
        "alive": bool(proc is not None and proc.poll() is None),
        "proxy": state.get("proxy_url"),
        "log_path": state.get("log_path"),
    }


def _network_urlopen(request, timeout):
    """Open an external URL through Tekzite Network, keeping loopback direct."""
    # Preserve the long-standing test/integration seam: callers that monkeypatch
    # engine.net.urlopen still intercept requests. Normal runtime keeps the
    # original function here and therefore uses the Tekzite Network opener.
    if urlopen is not _ORIGINAL_URLOPEN:
        return urlopen(request, timeout=timeout)
    try:
        full_url = request.full_url
    except Exception:
        full_url = str(request)
    try:
        host = (urlsplit(full_url).hostname or "").lower()
    except Exception:
        host = ""
    if host in {"127.0.0.1", "localhost", "::1"}:
        return _stdlib_urlopen(request, timeout=timeout)
    ensure_network_engine()
    return _NETWORK_OPENER.open(request, timeout=timeout)


def _add_session_cookies(request):
    try:
        _COOKIE_JAR.add_cookie_header(request)
    except Exception:
        pass



def _is_google_search_url(url: str) -> bool:
    try:
        parts = urlsplit(str(url))
    except Exception:
        return False
    host = (parts.hostname or "").lower()
    return host in {"google.com", "www.google.com"} and parts.path == "/search"


def _looks_like_google_js_gate(html: str) -> bool:
    """Detect Google's JS-only search bootstrap page.

    Since 2025/2026 Google can return HTTP 200 with a sizeable HTML shell, but
    no actual result DOM. The shell contains an enable-JavaScript retry route
    and/or the familiar "not redirected within a few seconds" message.
    """
    lowered = (html or "").lower()
    if "/httpservice/retry/enablejs" in lowered:
        return True
    if "not redirected within a few seconds" in lowered:
        return True
    if "niet binnen enkele seconden wordt omgeleid" in lowered:
        return True
    return False


def _chromium_candidates():
    """Yield real Chromium-family executables, avoiding Windows app aliases.

    On Windows, PATH entries can resolve to WindowsApps/App Execution Aliases.
    Launching those may forward our URL into the user's already-running Edge
    session, which creates visible tabs and leaves no DevTools endpoint for
    Tekzite. Prefer the actual installed executable and skip alias shims.
    """
    seen = set()

    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("LOCALAPPDATA"),
        ]
        root_dir = _network_engine_root()
        bundled = [
            os.path.join(root_dir, "chromium.exe"),
            os.path.join(root_dir, "chromium", "chrome.exe"),
            os.path.join(root_dir, "ungoogled-chromium", "chrome.exe"),
        ]
        for path in bundled:
            path = os.path.abspath(path)
            key = os.path.normcase(path)
            if os.path.isfile(path) and key not in seen:
                seen.add(key)
                yield path

        # Keep Tekzite on its dedicated Chromium backend rather than silently
        # switching browser engines. Microsoft websites themselves are allowed
        # through Tekzite Network; this only controls which Chromium executable
        # Tekzite launches.
        relatives = [
            os.path.join("Chromium", "Application", "chrome.exe"),
            os.path.join("Google", "Chrome", "Application", "chrome.exe"),
        ]
        for root in roots:
            if not root:
                continue
            for rel in relatives:
                path = os.path.abspath(os.path.join(root, rel))
                key = os.path.normcase(path)
                if os.path.isfile(path) and key not in seen:
                    seen.add(key)
                    yield path

        # PATH is only a fallback on Windows. Explicitly ignore WindowsApps
        # aliases because they can hand the command to the user's normal Edge.
        for name in ("chromium.exe", "chrome.exe"):
            path = shutil.which(name)
            if not path:
                continue
            normalized = os.path.normcase(os.path.abspath(path))
            if "\\windowsapps\\" in normalized:
                continue
            if normalized not in seen and os.path.isfile(path):
                seen.add(normalized)
                yield path
        return

    # Linux/macOS development machines use ordinary PATH discovery.
    for name in (
        "chromium", "chromium-browser", "ungoogled-chromium",
        "google-chrome", "google-chrome-stable",
    ):
        path = shutil.which(name)
        if path:
            key = os.path.realpath(path)
            if key not in seen:
                seen.add(key)
                yield path


_EDGE_SESSION = None
_CHROMIUM_LAUNCH_DEBUG = {
    "attempts": 0, "executable": None, "port": None, "profile": None,
    "recovered": False, "last_error": None, "errors": [],
}



def _persistent_edge_profile_dir():
    """Return Tekzite's dedicated persistent Chromium compatibility profile.

    The profile has a Tekzite/Chromium identity only.  On first v4.43 launch
    we migrate the older Edge-named bridge directory in place so cookies,
    storage and sign-ins survive the branding cleanup.
    """
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        base = os.path.join(root, "Tekzite Browser")
        path = os.path.join(base, "Chromium Bridge Profile")
        legacy = os.path.join(base, "Edge Bridge Profile v4.14")
    else:
        root = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state"
        )
        base = os.path.join(root, "tekzite-browser")
        path = os.path.join(base, "chromium-bridge-profile")
        legacy = os.path.join(base, "edge-bridge-profile-v414")

    try:
        os.makedirs(base, exist_ok=True)
        if not os.path.exists(path) and os.path.isdir(legacy):
            os.replace(legacy, path)
    except OSError:
        # Migration is cosmetic; never make browser startup depend on it.
        pass
    os.makedirs(path, exist_ok=True)
    return path




def _edge_profile_owner_file(profile_dir):
    return os.path.join(profile_dir, "tekzite-helper.pid")


def _terminate_stale_profile_owner(profile_dir):
    """Clean up a helper left behind by an earlier Tekzite run.

    Edge refuses to open the same user-data-dir twice. When an old hidden
    helper survives a crash, a new launch can silently hand navigation to that
    stale process instead of exposing Tekzite's DevTools port. Kill only the
    PID recorded by Tekzite inside its dedicated bridge profile.
    """
    owner = _edge_profile_owner_file(profile_dir)
    try:
        raw = Path(owner).read_text(encoding="ascii").strip()
        pid = int(raw)
    except Exception:
        try:
            os.remove(owner)
        except OSError:
            pass
        return

    if pid <= 0 or pid == os.getpid():
        try:
            os.remove(owner)
        except OSError:
            pass
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    else:
        try:
            os.kill(pid, 15)
        except Exception:
            pass

    try:
        os.remove(owner)
    except OSError:
        pass




def _profile_chromium_pids(profile_dir):
    """Return Windows Chromium PIDs using Tekzite's exact bridge profile.

    A Chromium launcher can exit with code 0 after forwarding its command line to
    an already-running browser process. If that older process owns Tekzite's
    private user-data-dir but Tekzite's PID marker points elsewhere, the new
    remote-debugging port never appears. Query the Windows process command lines
    so we can identify only processes tied to this dedicated bridge profile.
    """
    if os.name != "nt":
        return []
    profile = os.path.normcase(os.path.abspath(str(profile_dir)))
    escaped = profile.replace("'", "''")
    script = (
        f"$profile='{escaped}'; "
        f"$selfPid={int(os.getpid())}; "
        "Get-CimInstance Win32_Process | Where-Object { "
        "$_.ProcessId -ne $selfPid -and $_.CommandLine -and "
        "($_.CommandLine.ToLower().Contains('--user-data-dir=' + $profile.ToLower()) -or "
        "$_.CommandLine.ToLower().Contains('--user-data-dir=\\\"' + $profile.ToLower() + '\\\"')) "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        pids = []
        for line in (result.stdout or "").splitlines():
            try:
                pid = int(line.strip())
            except Exception:
                continue
            if pid > 0 and pid != os.getpid() and pid not in pids:
                pids.append(pid)
        return pids
    except Exception:
        return []


def _terminate_profile_chromium_processes(profile_dir):
    """Kill only Chromium processes using Tekzite's dedicated bridge profile."""
    pids = _profile_chromium_pids(profile_dir)
    terminated = []
    if os.name != "nt":
        return pids, terminated
    for pid in pids:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                terminated.append(int(pid))
        except Exception:
            pass
    if pids:
        # Let Chromium release its profile singleton and file handles.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not _profile_chromium_pids(profile_dir):
                break
            time.sleep(0.05)
    return pids, terminated


def _clear_chromium_profile_locks(profile_dir):
    """Remove only stale Chromium singleton lock artifacts from Tekzite's private profile.

    This directory belongs exclusively to Tekzite's compatibility helper. We call
    this only after terminating the recorded helper process, so deleting these
    lock crumbs cannot touch the user's normal browser profile.
    """
    removed = []
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
        path = Path(profile_dir) / name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed.append(name)
            elif path.is_dir():
                import shutil as _shutil
                _shutil.rmtree(path, ignore_errors=True)
                removed.append(name)
        except Exception:
            pass
    return removed

def _write_profile_owner(profile_dir, pid):
    try:
        Path(_edge_profile_owner_file(profile_dir)).write_text(
            str(int(pid)), encoding="ascii"
        )
    except Exception:
        pass


def _clear_profile_owner(profile_dir, pid=None):
    owner = _edge_profile_owner_file(profile_dir)
    if pid is not None:
        try:
            if int(Path(owner).read_text(encoding="ascii").strip()) != int(pid):
                return
        except Exception:
            return
    try:
        os.remove(owner)
    except OSError:
        pass


def _free_loopback_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _devtools_json(port, path="/json/list", timeout=1.0):
    with _stdlib_urlopen(
        f"http://127.0.0.1:{int(port)}{path}", timeout=timeout
    ) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _hide_process_windows(root_pid):
    """Hide any Chromium windows owned by *root_pid* or its descendants.

    This runs while DevTools is starting, before Tekzite reparents the page
    surface, preventing a helper window from flashing or appearing on taskbar.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        # Lightweight process-tree walk via Toolhelp. Keep this local so the
        # startup path does not depend on helpers defined later in the module.
        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        descendants = {int(root_pid)}
        if snap != INVALID_HANDLE_VALUE:
            try:
                rows = []
                entry = PROCESSENTRY32W()
                entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
                while ok:
                    rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
                    ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
                changed = True
                while changed:
                    changed = False
                    for pid, ppid in rows:
                        if ppid in descendants and pid not in descendants:
                            descendants.add(pid)
                            changed = True
            finally:
                kernel32.CloseHandle(snap)

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        @WNDENUMPROC
        def enum_proc(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in descendants:
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, len(cls))
                if cls.value.startswith("Chrome_WidgetWin"):
                    user32.ShowWindow(hwnd, 0)  # SW_HIDE
            return True
        user32.EnumWindows(enum_proc, 0)
    except Exception:
        pass


def _terminate_helper_process_tree(process):
    """Terminate only the dedicated helper process tree Tekzite launched."""
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(int(process.pid)), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return
        except Exception:
            pass
    try:
        process.terminate()
    except Exception:
        pass


class _AdoptedProcessHandle:
    """Minimal Popen-like handle for a Chromium process adopted after launch handoff."""

    def __init__(self, pid):
        self.pid = int(pid)
        self.returncode = None

    def poll(self):
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
                if not handle:
                    self.returncode = 0
                    return self.returncode
                try:
                    code = wintypes.DWORD()
                    if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                        return None
                    if int(code.value) == STILL_ACTIVE:
                        return None
                    self.returncode = int(code.value)
                    return self.returncode
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                return None
        try:
            os.kill(self.pid, 0)
            return None
        except OSError:
            self.returncode = 0
            return self.returncode


def _listener_pid_for_port(port):
    """Return the PID listening on the local DevTools TCP port, if discoverable."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        needle = f":{int(port)}"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP":
                continue
            local, state, pid = parts[1], parts[3].upper(), parts[4]
            if state != "LISTENING" or not local.endswith(needle):
                continue
            try:
                return int(pid)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _wait_for_devtools(port, process, timeout=10.0):
    """Wait for DevTools and tolerate Chromium's normal launcher handoff.

    Some Chromium builds start a short-lived launcher process that exits with
    code 0 after transferring the profile/command line to the actual browser
    process.  A clean launcher exit is therefore not a failure by itself.
    """
    deadline = time.monotonic() + timeout
    last_error = None
    clean_exit_seen = False
    exit_code = None
    while time.monotonic() < deadline:
        rc = process.poll()
        if rc is not None:
            exit_code = int(rc)
            if exit_code != 0:
                raise RuntimeError(
                    f"Chromium bridge exited early with code {exit_code}"
                )
            clean_exit_seen = True
        elif not clean_exit_seen:
            _hide_process_windows(process.pid)
        try:
            _devtools_json(port, "/json/version", timeout=0.5)
            if not clean_exit_seen:
                _hide_process_windows(process.pid)
            adopted_pid = _listener_pid_for_port(port) if clean_exit_seen else None
            return {
                "handoff": bool(clean_exit_seen),
                "exit_code": exit_code,
                "adopted_pid": adopted_pid,
            }
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    if clean_exit_seen:
        raise RuntimeError(
            "Chromium launcher exited cleanly with code 0, but no DevTools "
            "endpoint appeared after handoff"
        ) from last_error
    raise RuntimeError("Timed out waiting for Chromium DevTools") from last_error


class _StdlibWebSocket:
    """Tiny RFC 6455 client sufficient for local Chromium DevTools.

    Chromium exposes a loopback ``ws://`` endpoint for CDP. Keeping this here
    avoids making Tekzite's Google compatibility bridge depend on the external
    ``websocket-client`` package.
    """

    def __init__(self, ws_url, timeout=5):
        import base64
        import hashlib
        import socket
        import struct
        from urllib.parse import urlparse

        parsed = urlparse(str(ws_url))
        if parsed.scheme not in ("ws", "wss"):
            raise RuntimeError(f"Unsupported DevTools WebSocket URL: {ws_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        sock = socket.create_connection((host, port), timeout=timeout)
        if parsed.scheme == "wss":
            import ssl
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(request)

        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("DevTools WebSocket handshake closed early")
            response.extend(chunk)
            if len(response) > 65536:
                raise RuntimeError("DevTools WebSocket handshake was too large")
        head, remainder = bytes(response).split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1", "replace").split("\r\n")
        if not lines or " 101 " not in (" " + lines[0] + " "):
            raise RuntimeError(f"DevTools WebSocket handshake failed: {lines[0] if lines else 'empty response'}")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept", "") != expected:
            raise RuntimeError("DevTools WebSocket handshake returned an invalid accept key")

        self._socket = sock
        self._buffer = bytearray(remainder)
        self._struct = struct
        self._closed = False
        # v5.00: one serialization/id domain per physical DevTools socket.
        # This is the final guard against duplicate CDP ids when multiple
        # browser subsystems share a persistent websocket.
        self._cdp_lock = threading.RLock()
        self._cdp_next_id = 1

    def settimeout(self, timeout):
        self._socket.settimeout(timeout)

    def _read_exact(self, size):
        while len(self._buffer) < size:
            chunk = self._socket.recv(max(4096, size - len(self._buffer)))
            if not chunk:
                raise ConnectionError("DevTools WebSocket closed")
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _send_frame(self, opcode, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        payload = bytes(payload)
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x80 | (opcode & 0x0F)])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(self._struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(self._struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + masked)

    def send(self, payload):
        self._send_frame(0x1, payload)

    def recv(self):
        fragments = bytearray()
        text_message = False
        while True:
            first, second = self._read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = self._struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = self._struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(length) if length else b""
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

            if opcode == 0x8:
                self.close()
                raise ConnectionError("DevTools WebSocket closed")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                fragments = bytearray(payload)
                text_message = True
            elif opcode == 0x2:
                fragments = bytearray(payload)
                text_message = False
            elif opcode == 0x0:
                fragments.extend(payload)
            else:
                continue

            if fin:
                data = bytes(fragments)
                return data.decode("utf-8", "replace") if text_message else data

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self._socket.close()
        except Exception:
            pass


def _open_devtools_websocket(ws_url, timeout=5):
    return _StdlibWebSocket(ws_url, timeout=timeout)


def _cdp_call(ws, method, params=None, message_id=1, timeout=8.0):
    """Send one serialized CDP request with a socket-unique request id.

    v5.00 makes the websocket itself authoritative for request ids. Callers may
    still provide a preferred starting id for compatibility/debugging, but the
    actual id sent on the wire is atomically reserved from the socket's monotone
    counter. This prevents Runtime.evaluate/Page.captureScreenshot/zoom/input
    callers from ever producing Chromium's ``Duplicate id in protocol request``
    error on a shared persistent channel.
    """
    lock = getattr(ws, "_cdp_lock", None)
    if lock is None:
        # Compatibility for mocked/test websocket objects.
        lock = threading.RLock()
        try:
            setattr(ws, "_cdp_lock", lock)
        except Exception:
            pass
    with lock:
        preferred = max(1, int(message_id or 1))
        next_id = max(preferred, int(getattr(ws, "_cdp_next_id", 1) or 1))
        try:
            setattr(ws, "_cdp_next_id", next_id + 1)
            setattr(ws, "_cdp_last_id", next_id)
            setattr(ws, "_cdp_last_method", str(method))
        except Exception:
            pass

        ws.settimeout(timeout)
        ws.send(json.dumps({
            "id": next_id,
            "method": method,
            "params": params or {},
        }))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = ws.recv()
            payload = json.loads(raw)
            if payload.get("id") != next_id:
                continue
            if "error" in payload:
                raise RuntimeError(f"CDP {method} failed: {payload['error']}")
            return payload.get("result", {})
        raise RuntimeError(f"Timed out waiting for CDP {method}")



def _close_page_cdp_channel(channel):
    """Close one cached page-level CDP WebSocket."""
    if not channel:
        return
    ws = channel.get("ws") if isinstance(channel, dict) else None
    if ws is not None:
        try:
            ws.close()
        except Exception:
            pass
    if isinstance(channel, dict):
        channel["ws"] = None
        channel["closed"] = True


def _close_persistent_page_cdp_channels(session, target_id=None):
    """Close cached page CDP channels, optionally only for *target_id*."""
    if not session:
        return
    channels = session.get("page_cdp_channels") or {}
    if target_id is not None:
        prefix = f"{target_id}:"
        for key in [key for key in list(channels) if key == str(target_id) or key.startswith(prefix)]:
            channel = channels.pop(key, None)
            _close_page_cdp_channel(channel)
        return
    for channel in list(channels.values()):
        _close_page_cdp_channel(channel)
    channels.clear()


def _get_persistent_page_cdp_channel(session, target_id=None, timeout=5.0, purpose="default"):
    """Return one long-lived page CDP WebSocket per Chromium target.

    v4.55 keeps long-lived per-purpose sockets for each target. Capture uses a
    dedicated lane while input/control uses the default lane, preventing a slow
    screenshot from delaying clicks or keystrokes without returning to the old
    per-frame connection churn.
    """
    if not session or not session.get("port"):
        raise RuntimeError("Chromium helper is not running")

    wanted = target_id or session.get("active_target_id") or session.get("target_id")
    purpose = str(purpose or "default")
    channels = session.setdefault("page_cdp_channels", {})
    if wanted:
        cache_key = f"{wanted}:{purpose}"
        cached = channels.get(cache_key)
        if cached and cached.get("ws") is not None and not cached.get("closed"):
            return cached

    # Only hit /json when establishing/re-establishing a target channel.
    page = _pick_devtools_page(session["port"], session, target_id=wanted)
    resolved_target = str(page.get("id") or wanted or "")
    cache_key = f"{resolved_target}:{purpose}"
    cached = channels.get(cache_key)
    if cached and cached.get("ws") is not None and not cached.get("closed"):
        return cached

    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=timeout)
    channel = {
        "target_id": resolved_target,
        "purpose": purpose,
        "ws_url": page.get("webSocketDebuggerUrl"),
        "ws": ws,
        "lock": threading.RLock(),
        "next_message_id": 1000,
        "enabled_domains": set(),
        "closed": False,
        "created_at": time.monotonic(),
        "calls": 0,
        "reconnects": 0,
    }
    channels[cache_key] = channel
    if resolved_target:
        session["target_id"] = resolved_target
    try:
        _cdp_call(ws, "Network.enable", {}, message_id=901, timeout=timeout)
        _cdp_call(
            ws, "Network.setExtraHTTPHeaders",
            {"headers": {"DNT": "1", "Sec-GPC": "1"}},
            message_id=902, timeout=timeout,
        )
        channel["enabled_domains"].add("Network")
        channel["privacy_headers"] = True
        channel["next_message_id"] = max(channel["next_message_id"], 1000)
    except Exception:
        channel["privacy_headers"] = False
    return channel


def _persistent_page_cdp_call(session, method, params=None, *, target_id=None,
                              timeout=5.0, purpose="default"):

    """Call a page CDP method over Tekzite's persistent per-tab channel.

    One reconnect is attempted if Chromium closes the socket. This keeps the
    steady-state path at one long-lived loopback connection per active tab.
    """
    last_error = None
    for attempt in range(2):
        channel = _get_persistent_page_cdp_channel(
            session, target_id=target_id, timeout=timeout, purpose=purpose
        )
        lock = channel["lock"]
        try:
            with lock:
                message_id = int(channel.get("next_message_id", 1000))
                channel["next_message_id"] = message_id + 1
                result = _cdp_call(
                    channel["ws"], method, params or {},
                    message_id=message_id, timeout=timeout,
                )
                channel["calls"] = int(channel.get("calls", 0)) + 1
                return result
        except Exception as exc:
            last_error = exc
            tid = channel.get("target_id")
            pkey = f"{tid}:{channel.get('purpose', 'default')}"
            _close_page_cdp_channel(channel)
            (session.get("page_cdp_channels") or {}).pop(pkey, None)
            if attempt == 0:
                continue
            raise
    raise RuntimeError(f"Persistent CDP call failed: {method}") from last_error


def persistent_cdp_debug():
    """Return connection-reuse counters for Tekzite debug output/tests."""
    session = _EDGE_SESSION or {}
    channels = session.get("page_cdp_channels") or {}
    return {
        "channels": len(channels),
        "targets": {
            key: {
                "calls": int(value.get("calls", 0)),
                "closed": bool(value.get("closed")),
                "created_at": value.get("created_at"),
            }
            for key, value in channels.items()
        },
    }


def _apply_privacy_profile_preferences(profile_dir):
    """Apply privacy-first Chromium profile prefs without weakening TLS/security."""
    try:
        default_dir = Path(profile_dir) / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)
        pref_path = default_dir / "Preferences"
        try:
            prefs = json.loads(pref_path.read_text(encoding="utf-8")) if pref_path.exists() else {}
        except Exception:
            prefs = {}
        if not isinstance(prefs, dict):
            prefs = {}
        profile = prefs.setdefault("profile", {})
        profile["password_manager_enabled"] = False
        profile["cookie_controls_mode"] = 2  # Chromium: block third-party cookies where supported.
        content = profile.setdefault("default_content_setting_values", {})
        content.update({
            "notifications": 2,
            "geolocation": 2,
            "media_stream_mic": 2,
            "media_stream_camera": 2,
            "sensors": 2,
        })
        prefs.setdefault("credentials_enable_service", False)
        prefs.setdefault("autofill", {}).update({"profile_enabled": False, "credit_card_enabled": False})
        prefs.setdefault("dns_prefetching", {})["enabled"] = False
        prefs.setdefault("net", {})["network_prediction_options"] = 2
        prefs.setdefault("search", {})["suggest_enabled"] = False
        prefs.setdefault("spellcheck", {})["use_spelling_service"] = False
        prefs.setdefault("signin", {})["allowed"] = False
        prefs["enable_do_not_track"] = True
        sandbox = prefs.setdefault("privacy_sandbox", {})
        sandbox.update({
            "apis_enabled": False,
            "m1": {"topics_enabled": False, "fledge_enabled": False, "ad_measurement_enabled": False},
        })
        tmp = pref_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs, separators=(",", ":")), encoding="utf-8")
        tmp.replace(pref_path)
    except Exception:
        # Privacy prefs are defense-in-depth; browser startup must still work.
        pass


def _start_persistent_chromium_session(timeout=12, launch_geometry=None, launch_url=None):
    """Launch a real Chromium-family session with persistent state.

    v5.05 makes helper startup self-healing. A crashed Chromium can leave its
    private profile locked even after Tekzite's PID marker is gone. For each
    backend we therefore get two clean launch attempts, using a fresh DevTools
    port on retry and removing only stale singleton lock files from Tekzite's
    dedicated compatibility profile.
    """
    global _EDGE_SESSION, _CHROMIUM_LAUNCH_DEBUG

    if _EDGE_SESSION:
        process = _EDGE_SESSION.get("process")
        if process is not None and process.poll() is None:
            try:
                _devtools_json(_EDGE_SESSION["port"], "/json/version", timeout=0.5)
                return _EDGE_SESSION
            except Exception:
                pass
        _EDGE_SESSION = None

    _CHROMIUM_LAUNCH_DEBUG = {
        "attempts": 0, "executable": None, "port": None, "profile": None,
        "launch_geometry_requested": tuple(launch_geometry) if launch_geometry else None,
        "launch_url_requested": str(launch_url) if launch_url else None,
        "recovered": False, "last_error": None, "errors": [],
        "handoff_detected": False, "original_pid": None,
        "adopted_pid": None, "launcher_exit_code": None,
        "profile_processes_found": [], "profile_processes_terminated": [],
    }
    last_error = None
    candidates = list(_chromium_candidates())
    for executable in candidates:
        profile = _persistent_edge_profile_dir()
        # Two attempts per executable. The second one is a deliberately clean
        # retry after terminating any partial process and clearing stale locks.
        for attempt in (1, 2):
            port = _free_loopback_port()
            _CHROMIUM_LAUNCH_DEBUG.update({
                "attempts": int(_CHROMIUM_LAUNCH_DEBUG.get("attempts", 0)) + 1,
                "executable": executable, "port": port, "profile": profile,
            })
            process = None
            try:
                _terminate_stale_profile_owner(profile)
                found, terminated = _terminate_profile_chromium_processes(profile)
                if found:
                    _CHROMIUM_LAUNCH_DEBUG["profile_processes_found"] = list(found)
                if terminated:
                    _CHROMIUM_LAUNCH_DEBUG["profile_processes_terminated"] = list(terminated)
                # Once no live process owns Tekzite's private profile, singleton
                # crumbs are stale by definition and can be removed safely.
                if not _profile_chromium_pids(profile):
                    _clear_chromium_profile_locks(profile)
                if attempt == 2:
                    # Give Windows a beat to release file/process handles from
                    # the failed first helper before relaunching the same profile.
                    time.sleep(0.15)
                _apply_privacy_profile_preferences(profile)
                launch_x, launch_y, launch_w, launch_h = (-32000, -32000, 800, 600)
                if launch_geometry:
                    try:
                        launch_x, launch_y, launch_w, launch_h = map(int, launch_geometry)
                        launch_w, launch_h = max(320, launch_w), max(240, launch_h)
                    except Exception:
                        launch_x, launch_y, launch_w, launch_h = (-32000, -32000, 800, 600)
                command = [
                    executable,
                    f"--remote-debugging-port={port}",
                    "--remote-debugging-address=127.0.0.1",
                    "--remote-allow-origins=*",
                    f"--user-data-dir={profile}",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-save-password-bubble", "--disable-translate",
                    "--disable-search-engine-choice-screen", "--disable-notifications",
                    "--disable-geolocation", "--disable-sync", "--disable-component-update",
                    "--disable-background-networking", "--disable-breakpad",
                    "--disable-crash-reporter", "--disable-domain-reliability",
                    "--disable-client-side-phishing-detection", "--disable-default-apps",
                    "--disable-logging", "--metrics-recording-only", "--no-pings",
                    "--disable-features=EdgeFirstRunExperience,msEdgeSidebarV2,AsyncDns,DnsOverHttps,UseDnsHttpsSvcb,NetworkErrorLogging,Reporting,OptimizationHints,AutofillServerCommunication,InterestFeedContentSuggestions,PrivacySandboxSettings4,MediaRouter,CalculateNativeWinOcclusion",
                    "--disable-session-crashed-bubble", "--disable-background-mode",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                    f"--disable-extensions-except={_zoom_extension_dir()}",
                    f"--load-extension={_zoom_extension_dir()}",
                    f"--proxy-server={ensure_network_engine()['proxy_url']}",
                    "--proxy-bypass-list=<-loopback>", "--disable-quic",
                    "--dns-prefetch-disable",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    f"--window-position={launch_x},{launch_y}",
                    f"--window-size={launch_w},{launch_h}",
                    f"--app={str(launch_url or 'about:blank')}",
                ]
                # v7.3 typography guard: Chromium's best Windows text path is
                # the default one. Never let legacy/debug switches disable LCD
                # text, subpixel positioning, or DirectWrite UI rendering.
                # These switches materially affect glyph sharpness, kerning and
                # hinting. We deliberately do not inject CSS font smoothing.
                _bad_typography_switches = {
                    "--disable-lcd-text",
                    "--disable-font-subpixel-positioning",
                    "--disable-directwrite-for-ui",
                }
                command = [arg for arg in command if str(arg).casefold() not in _bad_typography_switches]

                # v5.23: derive launch-feature diagnostics from the exact argv
                # that will be passed to Chromium. This prevents debug state from
                # drifting away from the real process command line.
                effective_flags = [str(arg) for arg in command[1:] if str(arg).startswith("--")]
                disabled_features = ""
                for arg in effective_flags:
                    if arg.startswith("--disable-features="):
                        disabled_features = arg.split("=", 1)[1]
                        break
                _CHROMIUM_LAUNCH_DEBUG.update({
                    "native_occlusion_disabled": "CalculateNativeWinOcclusion" in disabled_features,
                    "renderer_backgrounding_disabled": "--disable-renderer-backgrounding" in effective_flags,
                    "background_timer_throttling_disabled": "--disable-background-timer-throttling" in effective_flags,
                    "occluded_window_backgrounding_disabled": "--disable-backgrounding-occluded-windows" in effective_flags,
                    "launch_effective_flags": list(effective_flags),
                    "typography_lcd_text_enabled": "--disable-lcd-text" not in effective_flags,
                    "typography_subpixel_positioning_enabled": "--disable-font-subpixel-positioning" not in effective_flags,
                    "typography_directwrite_ui_enabled": "--disable-directwrite-for-ui" not in effective_flags,
                    "typography_css_override_used": False,
                })
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                process = subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=creationflags, startupinfo=None,
                )
                original_pid = int(process.pid)
                wait_info = _wait_for_devtools(port, process, timeout=timeout) or {}
                handoff = bool(wait_info.get("handoff"))
                adopted_pid = wait_info.get("adopted_pid")
                if handoff:
                    if not adopted_pid:
                        raise RuntimeError(
                            "Chromium DevTools appeared after launcher handoff, "
                            "but the listening browser PID could not be identified"
                        )
                    process = _AdoptedProcessHandle(adopted_pid)
                _write_profile_owner(profile, process.pid)
                _EDGE_SESSION = {
                    "process": process, "port": port, "profile": profile,
                    "page_cdp_channels": {}, "executable": executable,
                    "launch_attempt": attempt,
                    "launch_handoff": handoff,
                    "launch_original_pid": original_pid,
                    "launch_adopted_pid": int(adopted_pid) if adopted_pid else None,
                    "launch_geometry": (launch_x, launch_y, launch_w, launch_h),
                    "launch_url": str(launch_url or "about:blank"),
                }
                _CHROMIUM_LAUNCH_DEBUG.update({
                    "handoff_detected": handoff,
                    "original_pid": original_pid,
                    "adopted_pid": int(adopted_pid) if adopted_pid else None,
                    "launcher_exit_code": wait_info.get("exit_code"),
                })
                _CHROMIUM_LAUNCH_DEBUG["recovered"] = bool(attempt > 1)
                _CHROMIUM_LAUNCH_DEBUG["last_error"] = None
                if os.name == "nt":
                    try:
                        helper_hwnd = _find_chromium_window(_EDGE_SESSION, timeout=1.5)
                        _EDGE_SESSION["outer_hwnd"] = _hwnd_int(helper_hwnd)
                        _EDGE_SESSION["main_hwnd"] = _hwnd_int(helper_hwnd)
                        _apply_tekzite_chromium_branding(_EDGE_SESSION)
                    except Exception:
                        pass
                return _EDGE_SESSION
            except Exception as exc:
                last_error = exc
                msg = f"{type(exc).__name__}: {exc}"
                _CHROMIUM_LAUNCH_DEBUG["last_error"] = msg
                _CHROMIUM_LAUNCH_DEBUG.setdefault("errors", []).append(
                    {"attempt": attempt, "executable": executable, "port": port, "error": msg}
                )
                try:
                    _terminate_helper_process_tree(process)
                except Exception:
                    pass
                try:
                    _clear_profile_owner(profile, getattr(process, "pid", None))
                except Exception:
                    pass
                if attempt == 1:
                    # A failed Chromium may not have written Tekzite's owner PID
                    # yet, so clear its private singleton locks before retry 2.
                    _clear_chromium_profile_locks(profile)

    if last_error is not None:
        raise RuntimeError(
            f"No persistent Chromium session could be started; last launch error: "
            f"{type(last_error).__name__}: {last_error}"
        ) from last_error
    raise RuntimeError(
        "No Chromium backend found. Install Chromium/Ungoogled Chromium "
        "or place chromium.exe beside Tekzite. Microsoft Edge is intentionally "
        "not used as Tekzite's browser backend."
    )


def _pick_devtools_page(port, session=None, target_id=None):
    """Return a debuggable page target.

    v4.40 keeps one Chromium page target per Tekzite tab.  ``target_id``
    selects that exact target; when omitted, the session's current target is
    used for backwards compatibility with the pre-tab single-page bridge.
    """
    pages = _devtools_json(port, "/json/list", timeout=1.0)
    wanted = target_id or (session or {}).get("target_id")
    if wanted:
        for page in pages:
            if page.get("id") == wanted and page.get("webSocketDebuggerUrl"):
                return page
    candidates = [
        page for page in pages
        if page.get("type") == "page" and page.get("webSocketDebuggerUrl")
    ]
    if not candidates:
        raise RuntimeError("Chromium bridge exposed no debuggable page")
    # App-mode startup should expose exactly one page. Prefer about:blank if
    # Edge also created an internal/background page for its own UI.
    page = next((p for p in candidates if p.get("url") == "about:blank"), candidates[0])
    if session is not None:
        session["target_id"] = page.get("id")
    return page



def _browser_cdp_call(session, method, params=None, *, message_id=1, timeout=5.0):
    """Call the browser-level DevTools target endpoint."""
    version = _devtools_json(session["port"], "/json/version", timeout=1.0)
    ws_url = version.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("Chromium browser DevTools websocket unavailable")
    ws = _open_devtools_websocket(ws_url, timeout=timeout)
    try:
        return _cdp_call(ws, method, params or {}, message_id=message_id, timeout=timeout)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def create_embedded_chromium_target(url: str = "about:blank", *, require_bootstrap: bool = False):
    """Create/claim a Chromium page target for a Tekzite tab.

    v5.17 is app-window-first.  Chromium is launched with ``--app=about:blank``;
    the first Tekzite tab claims that already-existing app target instead of
    immediately creating a second target/window hierarchy.  This keeps the
    DirectComposition presenter attached to Chromium's original app window.
    Later Tekzite tabs can still use Target.createTarget inside the persistent
    browser session.
    """
    session = _start_persistent_chromium_session(timeout=12)
    target_id = None
    if require_bootstrap:
        session["native_app_target_strict"] = True

    # Reuse an already-claimed bootstrap target when the caller is the first
    # native Tekzite tab returning through the same startup path.
    claimed_id = session.get("native_app_target_id") if session.get("app_bootstrap_target_claimed") else None
    if claimed_id:
        try:
            pages = _devtools_json(session["port"], "/json/list", timeout=1.0)
            if any(p.get("id") == claimed_id for p in pages):
                target_id = claimed_id
                session["native_app_target_reused"] = True
        except Exception:
            target_id = None

    # Claim the launch app target exactly once.  Reusing the bootstrap target is
    # important: creating a second target at startup can cause Chromium to
    # manufacture another Chrome_WidgetWin_0 presenter, which defeats app-mode
    # and was implicated in the detached-overlay surface churn.
    if not target_id and not session.get("app_bootstrap_target_claimed"):
        try:
            pages = _devtools_json(session["port"], "/json/list", timeout=1.0)
            expected_launch_url = str(session.get("launch_url") or "about:blank")
            expected_lower = expected_launch_url.lower()
            bootstrap = next(
                (p for p in pages
                 if p.get("type") == "page"
                 and p.get("webSocketDebuggerUrl")
                 and str(p.get("url") or "").lower() == expected_lower),
                None,
            )
            if bootstrap is None:
                bootstrap = next(
                    (p for p in pages
                     if p.get("type") == "page"
                     and p.get("webSocketDebuggerUrl")
                     and str(p.get("url") or "").lower() in {"about:blank", "chrome://newtab/"}),
                    None,
                )
            if bootstrap and bootstrap.get("id"):
                target_id = bootstrap.get("id")
                session["app_bootstrap_target_claimed"] = True
                session["native_app_target_reused"] = True
                session["native_app_target_id"] = target_id
                session["native_direct_app_url"] = expected_launch_url if expected_lower not in {"about:blank", "chrome://newtab/"} else None
                session["native_direct_app_target_match"] = (str(bootstrap.get("url") or "").lower() == expected_lower)
                _browser_cdp_call(
                    session, "Target.activateTarget", {"targetId": target_id}, message_id=102
                )
                # Navigate through the page websocket so the original app target
                # remains the visible native surface.
                page_ws = _open_devtools_websocket(bootstrap["webSocketDebuggerUrl"], timeout=5)
                try:
                    _cdp_call(page_ws, "Page.enable", message_id=1)
                    if str(url or "about:blank") != str(bootstrap.get("url") or ""):
                        _cdp_call(
                            page_ws, "Page.navigate", {"url": str(url or "about:blank")},
                            message_id=2, timeout=5.0,
                        )
                finally:
                    try:
                        page_ws.close()
                    except Exception:
                        pass
        except Exception as exc:
            session["native_app_target_reuse_error"] = str(exc)
            target_id = None

    if not target_id and require_bootstrap:
        session["native_app_target_reused"] = False
        error = session.get("native_app_target_reuse_error") or (
            "Chromium bootstrap app target was not found; refusing to create a second "
            "native target for the first Tekzite tab"
        )
        session["native_app_target_reuse_error"] = error
        raise RuntimeError(error)

    if not target_id:
        result = _browser_cdp_call(
            session,
            "Target.createTarget",
            {"url": str(url or "about:blank"), "newWindow": False, "background": False},
            message_id=101,
        )
        target_id = result.get("targetId")
        if not target_id:
            raise RuntimeError("Chromium did not create a page target")
        _browser_cdp_call(
            session, "Target.activateTarget", {"targetId": target_id}, message_id=102
        )
        session["native_app_target_reused"] = False
    session["target_id"] = target_id
    # Every page target receives the browser-wide zoom bootstrap immediately,
    # including 100%. Applying 100% matters too: it clears any stale per-page
    # state and makes the invariant explicit that *all* web pages are governed
    # by the same saved preference, regardless of host or subdomain.
    try:
        inherited_zoom = int(session.get("default_page_zoom_percent", 100))
        set_embedded_chromium_zoom(inherited_zoom, target_id=target_id, timeout=3)
    except Exception:
        pass
    return target_id


def activate_embedded_chromium_target(target_id: str):
    """Activate an already loaded Chromium tab without navigating it again.

    v7.5 uses the persistent browser CDP channel as the fast path. A synchronous
    /json/list round-trip on every tab click made switching visibly laggy and is
    unnecessary: Target.activateTarget itself is authoritative. Only fall back to
    the target listing if Chromium rejects the activation.
    """
    if not target_id:
        return False
    session = _start_persistent_chromium_session(timeout=12)
    try:
        _browser_cdp_call(
            session, "Target.activateTarget", {"targetId": target_id}, message_id=103,
            timeout=1.5,
        )
    except Exception:
        try:
            pages = _devtools_json(session["port"], "/json/list", timeout=0.75)
        except Exception:
            return False
        if not any(p.get("id") == target_id for p in pages):
            return False
        try:
            _browser_cdp_call(
                session, "Target.activateTarget", {"targetId": target_id}, message_id=103,
                timeout=1.5,
            )
        except Exception:
            return False
    session["target_id"] = target_id
    session["tab_switch_fast_path_count"] = int(session.get("tab_switch_fast_path_count", 0)) + 1
    return True


def close_embedded_chromium_target(target_id: str):
    """Close one Chromium page target while keeping the helper process alive."""
    if not target_id:
        return False
    session = _start_persistent_chromium_session(timeout=12)
    _close_persistent_page_cdp_channels(session, target_id=target_id)
    try:
        result = _browser_cdp_call(
            session, "Target.closeTarget", {"targetId": target_id}, message_id=104
        )
    except Exception:
        return False
    if session.get("target_id") == target_id:
        session.pop("target_id", None)
    return bool(result.get("success", True))

def fetch_rendered_dom(url: str, timeout: int = 30):
    """Render *url* in Tekzite's persistent, real Chromium compatibility session.

    This deliberately does not use ``--headless`` or a throw-away profile.
    The helper stays hidden and never becomes a second browser surface. Chromium
    executes only the site's JavaScript. The resulting outerHTML is
    then handed back to Tekzite's own parser/style/layout/paint pipeline.
    """
    session = _start_persistent_chromium_session(timeout=min(timeout, 12))
    page = _pick_devtools_page(session["port"], session)
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    try:
        _cdp_call(ws, "Page.enable", message_id=1)
        _cdp_call(ws, "Runtime.enable", message_id=2)
        _cdp_call(ws, "Page.navigate", {"url": str(url)}, message_id=3)

        # Give a real network-loaded page time to settle. We intentionally use
        # normal wall-clock time instead of virtual-time/headless shortcuts,
        # because this bridge is meant to look and behave like a normal browser
        # session to JavaScript-heavy sites.
        deadline = time.monotonic() + max(4.0, min(float(timeout), 20.0))
        stable_html = ""
        stable_count = 0
        message_id = 10
        while time.monotonic() < deadline:
            result = _cdp_call(
                ws,
                "Runtime.evaluate",
                {
                    "expression": "document.documentElement ? document.documentElement.outerHTML : ''",
                    "returnByValue": True,
                },
                message_id=message_id,
                timeout=4.0,
            )
            message_id += 1
            html = (
                result.get("result", {}).get("value", "")
                if isinstance(result, dict) else ""
            )
            if html and "<html" in html.lower():
                if html == stable_html:
                    stable_count += 1
                else:
                    stable_html = html
                    stable_count = 0

                lowered = html.lower()
                # Result pages normally contain the search container and links.
                # A generic two-sample stability fallback covers other JS sites.
                if (
                    'id="search"' in lowered
                    or 'id="rso"' in lowered
                    or stable_count >= 2
                ):
                    return html
            time.sleep(0.50)

        if stable_html:
            return stable_html
        raise RuntimeError("Chromium bridge produced no HTML")
    finally:
        try:
            ws.close()
        except Exception:
            pass




def _analyze_embedded_frame_png(data_b64: str):
    """Return lightweight visual-health metrics for a CDP PNG screenshot.

    A PNG existing is not proof that Chromium actually painted useful content:
    the compositor can return a perfectly valid all-black/all-white frame during
    consent, renderer and surface transitions.  Downsample aggressively so this
    check stays cheap enough for first-frame and post-click validation.
    """
    metrics = {
        "valid": False, "width": 0, "height": 0,
        "black_ratio": 1.0, "white_ratio": 0.0,
        "channel_span": 0, "visual": False,
    }
    if not isinstance(data_b64, str) or len(data_b64) < 128:
        return metrics
    try:
        from PIL import Image
        raw = base64.b64decode(data_b64, validate=False)
        with Image.open(io.BytesIO(raw)) as im:
            metrics["width"], metrics["height"] = im.size
            rgb = im.convert("RGB")
            rgb.thumbnail((72, 72))
            pixels = list(rgb.getdata())
        if not pixels:
            return metrics
        total = float(len(pixels))
        black = sum(1 for r,g,b in pixels if r <= 14 and g <= 14 and b <= 14)
        white = sum(1 for r,g,b in pixels if r >= 241 and g >= 241 and b >= 241)
        mins = [min(px[i] for px in pixels) for i in range(3)]
        maxs = [max(px[i] for px in pixels) for i in range(3)]
        span = max(maxs[i] - mins[i] for i in range(3))
        black_ratio = black / total
        white_ratio = white / total
        # Reject only near-uniform compositor blanks. Dark-mode pages remain
        # valid because real UI/content creates substantial pixel variation.
        visual = not ((black_ratio >= 0.985 or white_ratio >= 0.995) and span <= 28)
        metrics.update({
            "valid": True, "black_ratio": black_ratio,
            "white_ratio": white_ratio, "channel_span": int(span),
            "visual": bool(visual),
        })
        return metrics
    except Exception as exc:
        metrics["error"] = type(exc).__name__
        return metrics


def _wait_for_embedded_first_frame(session, timeout: float = 12.0, soft_timeout: bool = False):
    """Wait until Chromium's document is genuinely ready to be embedded.

    Chromium may throttle or entirely withhold compositor surfaces while its
    native window is parked far off-screen.  Requiring ``Page.captureScreenshot``
    before re-parenting therefore creates a false timeout on perfectly healthy
    pages (notably YouTube).  Treat DOM readiness plus real body content and
    animation-frame progress as the authoritative handshake.  A CDP screenshot
    remains a best-effort confirmation/debug signal, never a hard gate.
    """
    page = _pick_devtools_page(session["port"], session)
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    deadline = time.monotonic() + max(1.0, float(timeout))
    msg = 20
    ready_since = None
    last_ready = ""
    last_text_len = 0
    last_nodes = 0
    try:
        _cdp_call(ws, "Page.enable", message_id=msg); msg += 1
        _cdp_call(ws, "Runtime.enable", message_id=msg); msg += 1
        while time.monotonic() < deadline:
            state = _cdp_call(
                ws,
                "Runtime.evaluate",
                {
                    "expression": "({ready:document.readyState,text:(document.body&&document.body.innerText||'').trim().length,nodes:document.body?document.body.childElementCount:0,w:document.documentElement?document.documentElement.scrollWidth:0,h:document.documentElement?document.documentElement.scrollHeight:0})",
                    "returnByValue": True,
                },
                message_id=msg,
                timeout=3.0,
            )
            msg += 1
            value = state.get("result", {}).get("value", {}) if isinstance(state, dict) else {}
            ready = str(value.get("ready") or "")
            text_len = int(value.get("text") or 0)
            nodes = int(value.get("nodes") or 0)
            width = int(value.get("w") or 0)
            height = int(value.get("h") or 0)
            last_ready, last_text_len, last_nodes = ready, text_len, nodes

            has_document = (
                ready in {"interactive", "complete"}
                and (text_len >= 8 or nodes >= 2)
                and width > 0 and height > 0
            )
            if has_document:
                if ready_since is None:
                    ready_since = time.monotonic()

                raf_ok = False
                try:
                    _cdp_call(
                        ws,
                        "Runtime.evaluate",
                        {
                            "expression": "new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))",
                            "awaitPromise": True,
                            "returnByValue": True,
                        },
                        message_id=msg,
                        timeout=2.0,
                    )
                    msg += 1
                    raf_ok = True
                except Exception:
                    # Off-screen Chromium can throttle rAF too.  A stable ready
                    # DOM is still preferable to failing the whole navigation.
                    pass

                screenshot_chars = 0
                screenshot_data = ""
                frame_metrics = {}
                try:
                    shot = _cdp_call(
                        ws,
                        "Page.captureScreenshot",
                        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": False,
            # Chromium can trade encoder CPU time for faster delivery without
            # lowering PNG image quality. The software surface remains lossless.
            "optimizeForSpeed": True,
        },
                        message_id=msg,
                        timeout=1.5,
                    )
                    msg += 1
                    data = shot.get("data", "") if isinstance(shot, dict) else ""
                    if isinstance(data, str):
                        screenshot_data = data
                        screenshot_chars = len(data)
                        frame_metrics = _analyze_embedded_frame_png(data)
                except Exception:
                    # Not fatal: off-screen windows often have no submitted
                    # compositor surface until they are attached/visible.
                    pass

                # A stable DOM is *not* proof that Chromium has submitted a
                # drawable frame. Modern app shells such as YouTube can reach
                # readyState=complete with a handful of nodes while the native
                # compositor is still completely white. v4.91 accepted that
                # state after 350 ms, which produced the intermittent
                # "Preparing frame" -> white page failure.
                #
                # Prefer an actual screenshot. If the off-screen Chromium
                # compositor cannot capture yet, only accept the DOM/rAF path
                # when the document also contains real visible text. A node-only
                # shell with text_len == 0 must keep waiting until it paints.
                stable_ready = (time.monotonic() - ready_since) >= 0.35
                screenshot_exists = screenshot_chars >= 128
                screenshot_ready = screenshot_exists and bool(frame_metrics.get("visual"))
                semantic_frame_ready = text_len >= 8 and (raf_ok or stable_ready)
                session["first_frame_visual_black_ratio"] = frame_metrics.get("black_ratio")
                session["first_frame_visual_white_ratio"] = frame_metrics.get("white_ratio")
                session["first_frame_visual_span"] = frame_metrics.get("channel_span")
                session["first_frame_blank_png_rejected"] = bool(screenshot_exists and not screenshot_ready)
                if screenshot_ready or semantic_frame_ready:
                    session["first_frame_ready"] = True
                    session["first_frame_ready_state"] = ready
                    session["first_frame_text_len"] = text_len
                    session["first_frame_nodes"] = nodes
                    session["first_frame_png_chars"] = screenshot_chars
                    session["first_frame_probe"] = (
                        "visual-screenshot" if screenshot_ready
                        else "text+raf" if raf_ok
                        else "stable-text-dom"
                    )
                    session["first_frame_empty_shell_rejected"] = False
                    return True
                if text_len == 0 and (not screenshot_exists or not screenshot_ready):
                    session["first_frame_empty_shell_rejected"] = True
            else:
                ready_since = None
            time.sleep(0.10)
    finally:
        try:
            ws.close()
        except Exception:
            pass
    session["first_frame_ready"] = False
    session["first_frame_ready_state"] = last_ready
    session["first_frame_text_len"] = last_text_len
    session["first_frame_nodes"] = last_nodes
    session["first_frame_preattach_timeout"] = True
    if soft_timeout:
        return False
    raise RuntimeError("Chromium document did not become ready before timeout")





def _current_render_host_size(session):
    """Return the live RenderWidgetHost size in device pixels, if available."""
    if os.name != "nt" or not session:
        return None
    render = _hwnd_int(session.get("render_hwnd") or 0)
    if not render:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(render)):
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(_as_hwnd(render), ctypes.byref(rect)):
            return None
        return (
            max(0, int(rect.right) - int(rect.left)),
            max(0, int(rect.bottom) - int(rect.top)),
        )
    except Exception:
        return None


def _kick_cold_start_native_resize(session):
    """Force one harmless WM_SIZE cycle after a cold native attach.

    Chromium can keep the launch viewport (for example 800x479) for its first
    embedded RenderWidgetHost even though Tekzite's host is already 1280x676.
    A normal reload fixes that because Chromium receives another complete layout
    cycle.  Reproduce only that resize signal without reloading the page by
    nudging the locked owner by one pixel and restoring the exact size.
    """
    if os.name != "nt" or not session or session.get("presentation_mode") == "software":
        return False
    owner = _hwnd_int(session.get("embedded_hwnd") or 0)
    if not owner:
        return False
    try:
        import ctypes
        import time as _time
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(owner)):
            return False
        width, height = session.get("embedded_size") or session.get("embedded_parent_client_size") or (1, 1)
        width, height = max(1, int(width)), max(1, int(height))
        crop_left, crop_top, crop_right, crop_bottom = session.get("chrome_crop") or _embedded_chrome_crop(session)
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        SWP_FRAMECHANGED = 0x0020
        flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED

        session["cold_start_resize_before"] = _current_render_host_size(session)
        session["cold_start_resize_kick_attempted"] = True
        # One-pixel width nudge is enough to generate a genuine native resize
        # without visibly moving the page or changing the requested viewport.
        user32.SetWindowPos(
            _as_hwnd(owner), _as_hwnd(0), -int(crop_left), -int(crop_top),
            max(1, width + int(crop_left) + int(crop_right) - 1),
            max(1, height + int(crop_top) + int(crop_bottom)), flags,
        )
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            _time.sleep(0.02)
        user32.SetWindowPos(
            _as_hwnd(owner), _as_hwnd(0), -int(crop_left), -int(crop_top),
            max(1, width + int(crop_left) + int(crop_right)),
            max(1, height + int(crop_top) + int(crop_bottom)), flags,
        )
        _refresh_render_host_within_owner(session, width, height)
        _show_embedded_render_host(session, width, height)
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            _time.sleep(0.02)
        session["cold_start_resize_after"] = _current_render_host_size(session)
        return True
    except Exception as exc:
        session["cold_start_resize_kick_attempted"] = True
        session["cold_start_resize_kick_error"] = str(exc)
        return False


def _wait_for_attached_first_frame(session, timeout: float = 6.0):
    """Verify a usable frame after the native HWND has been attached.

    Modern SPA pages can keep ``document.readyState`` at ``loading`` for a long
    time even after Chromium already has a healthy visible compositor surface.
    The off-screen pre-attach probe must therefore be advisory, not fatal. Once
    the owner is embedded and visible, accept either a visually non-blank CDP
    screenshot or meaningful page content regardless of readyState.
    """
    frame_generation = int(session.get("navigation_generation") or 0)
    session["attached_frame_generation"] = frame_generation
    page = _pick_devtools_page(session["port"], session, target_id=session.get("target_id"))
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    deadline = time.monotonic() + max(1.0, float(timeout))
    msg = 80
    last_ready = ""
    last_text = 0
    last_nodes = 0
    try:
        _cdp_call(ws, "Page.enable", message_id=msg); msg += 1
        _cdp_call(ws, "Runtime.enable", message_id=msg); msg += 1
        while time.monotonic() < deadline:
            state = _cdp_call(
                ws,
                "Runtime.evaluate",
                {
                    "expression": "({ready:document.readyState,text:(document.body&&document.body.innerText||'').trim().length,nodes:document.body?document.body.childElementCount:0,w:document.documentElement?document.documentElement.scrollWidth:0,h:document.documentElement?document.documentElement.scrollHeight:0})",
                    "returnByValue": True,
                },
                message_id=msg, timeout=2.0,
            )
            msg += 1
            value = state.get("result", {}).get("value", {}) if isinstance(state, dict) else {}
            ready = str(value.get("ready") or "")
            text_len = int(value.get("text") or 0)
            nodes = int(value.get("nodes") or 0)
            width = int(value.get("w") or 0)
            height = int(value.get("h") or 0)
            last_ready, last_text, last_nodes = ready, text_len, nodes

            screenshot_chars = 0
            metrics = {}
            try:
                shot = _cdp_call(
                    ws, "Page.captureScreenshot",
                    {"format":"png", "fromSurface":True, "captureBeyondViewport":False, "optimizeForSpeed":True},
                    message_id=msg, timeout=1.5,
                )
                msg += 1
                data = shot.get("data", "") if isinstance(shot, dict) else ""
                if isinstance(data, str):
                    screenshot_chars = len(data)
                    metrics = _analyze_embedded_frame_png(data)
            except Exception:
                pass

            screenshot_ready = screenshot_chars >= 128 and bool(metrics.get("visual"))
            semantic_ready = text_len >= 8 and nodes >= 2 and width > 0 and height > 0

            # v5.01: on the very first navigation, semantic DOM readiness alone
            # is not enough. Chromium can expose a fully populated Startpage DOM
            # while its native RWH is still stuck at the launch viewport. A reload
            # then fixes it, which is a strong sign that the missing piece is the
            # first native resize/layout cycle rather than network or JS loading.
            cold_start = frame_generation <= 1
            expected_size = session.get("embedded_size") or session.get("embedded_parent_client_size") or (0, 0)
            expected_w, expected_h = int(expected_size[0] or 0), int(expected_size[1] or 0)
            live_size = _current_render_host_size(session)
            geometry_ready = False
            if live_size and expected_w > 0 and expected_h > 0:
                rw, rh = live_size
                geometry_ready = (rw >= int(expected_w * 0.94) and rh >= int(expected_h * 0.94))
            session["cold_start_geometry_wait"] = bool(cold_start and not screenshot_ready and not geometry_ready)
            session["cold_start_render_size"] = live_size
            session["cold_start_expected_size"] = (expected_w, expected_h)
            if cold_start and not screenshot_ready:
                semantic_ready = semantic_ready and geometry_ready
                if not geometry_ready and not session.get("cold_start_resize_kick_attempted"):
                    _kick_cold_start_native_resize(session)

            session["attached_frame_ready_state"] = ready
            session["attached_frame_text_len"] = text_len
            session["attached_frame_nodes"] = nodes
            session["attached_frame_png_chars"] = screenshot_chars
            session["attached_frame_visual"] = bool(metrics.get("visual"))
            if screenshot_ready or semantic_ready:
                # Only commit evidence that belongs to the navigation we started
                # probing. A SPA/client redirect can begin a new navigation while
                # this loop is still alive; without a generation guard the old
                # frame could incorrectly mark the new document as ready.
                if int(session.get("navigation_generation") or 0) != frame_generation:
                    session["attached_frame_stale_generation"] = True
                    return False
                session["first_frame_ready"] = True
                session["first_frame_committed"] = True
                session["first_frame_generation"] = frame_generation
                session["first_frame_ready_state"] = ready
                session["first_frame_text_len"] = text_len
                session["first_frame_nodes"] = nodes
                session["first_frame_png_chars"] = screenshot_chars
                session["first_frame_probe"] = "attached-visual-screenshot" if screenshot_ready else "attached-semantic-dom"
                session["attached_frame_timeout"] = False
                session["attached_frame_stale_generation"] = False
                return True

            # The visible native surface may need one Windows repaint cycle
            # after SetParent before DComp submits pixels.
            try:
                _show_embedded_render_host(
                    session,
                    int((session.get("embedded_size") or (1,1))[0]),
                    int((session.get("embedded_size") or (1,1))[1]),
                )
                import ctypes
                ctypes.windll.dwmapi.DwmFlush()
            except Exception:
                pass
            time.sleep(0.12)
    finally:
        try:
            ws.close()
        except Exception:
            pass
    session["attached_frame_timeout"] = True
    session["attached_frame_ready_state"] = last_ready
    session["attached_frame_text_len"] = last_text
    session["attached_frame_nodes"] = last_nodes
    # Do not fail navigation here. Chromium's native surface is already attached
    # and may continue loading asynchronously; a hard timeout would tear down a
    # healthy SPA just because readyState remained 'loading'.
    return False

def navigate_embedded_chromium(url: str, timeout: int = 20, wait_for_first_frame: bool = False, target_id: str = None, create_new_target: bool = False):
    """Navigate the persistent Chromium helper and return its session.

    With ``wait_for_first_frame`` the helper remains off-screen until CDP has
    observed a real rendered frame.  That mode is used by Tekzite's embedded
    surface to avoid exposing a dead gray host while Chromium is still
    initializing its compositor.
    """
    session = _start_persistent_chromium_session(timeout=min(timeout, 12))
    if create_new_target:
        target_id = create_embedded_chromium_target("about:blank")
    page = _pick_devtools_page(session["port"], session, target_id=target_id)
    if target_id:
        activate_embedded_chromium_target(target_id)
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    direct_app_target = bool(
        session.get("native_direct_app_launch")
        and session.get("native_direct_app_target_match")
        and page.get("id") == session.get("native_app_target_id")
        and str(page.get("url") or "").lower() not in {"about:blank", "chrome://newtab/"}
    )
    try:
        _cdp_call(ws, "Page.enable", message_id=1)
        if direct_app_target:
            session["native_direct_app_navigation_skipped"] = True
        else:
            _cdp_call(ws, "Page.navigate", {"url": str(url)}, message_id=2)
            session["native_direct_app_navigation_skipped"] = False
    finally:
        try:
            ws.close()
        except Exception:
            pass
    session["target_id"] = page.get("id")
    session["last_url"] = str(url)
    # v4.98: frame-readiness diagnostics belong to one navigation only.
    # Increment the generation and erase attached-frame evidence from the
    # previous document so debug/recovery code cannot combine old visual proof
    # with a newly reset first_frame_ready flag.
    session["navigation_generation"] = int(session.get("navigation_generation") or 0) + 1
    session["first_frame_ready"] = False
    session["first_frame_committed"] = False
    session["first_frame_generation"] = None
    session["attached_frame_generation"] = None
    session["attached_frame_ready_state"] = None
    session["attached_frame_text_len"] = 0
    session["attached_frame_nodes"] = 0
    session["attached_frame_png_chars"] = 0
    session["attached_frame_visual"] = False
    session["attached_frame_timeout"] = None
    session["attached_frame_stale_generation"] = False
    if wait_for_first_frame:
        _wait_for_embedded_first_frame(
            session, timeout=max(4.0, min(float(timeout), 15.0)), soft_timeout=True
        )
    return session


def _windows_descendant_pids(root_pid):
    """Return *root_pid* and descendants using the Win32 Toolhelp API."""
    if os.name != "nt":
        return {int(root_pid)}
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return {int(root_pid)}
    try:
        rows = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)

    descendants = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, ppid in rows:
            if ppid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    return descendants


def _find_chromium_window(session, timeout=8.0):
    """Find the *main* Chromium top-level HWND for this Tekzite session.

    Chromium creates several top-level Chrome_WidgetWin* utility windows.
    Selecting the first one is unstable and can return a tiny/hidden helper
    instead of the real page window. Prefer a parentless Chrome_WidgetWin_1
    with a substantial client rectangle, then fall back by area.
    """
    if os.name != "nt":
        raise RuntimeError("Native Chromium embedding is currently Windows-only")
    import ctypes
    from ctypes import wintypes

    process = session.get("process")
    if process is None:
        raise RuntimeError("Chromium session has no process")

    user32 = ctypes.windll.user32
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        pids = _windows_descendant_pids(process.pid)
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @WNDENUMPROC
        def enum_proc(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids or not user32.IsWindow(hwnd):
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, len(cls))
            if not cls.value.startswith("Chrome_WidgetWin"):
                return True
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                left = int(rect.left)
                top = int(rect.top)
                width = max(0, int(rect.right) - left)
                height = max(0, int(rect.bottom) - top)
                area = width * height
            else:
                left = top = 0
                width = height = area = 0
            parent = user32.GetParent(hwnd)
            # v4.23: identify the window Tekzite itself launched, rather than
            # letting an unrelated large Chrome_WidgetWin_0 win by raw area.
            # The helper is intentionally created as an 800x600 app window at
            # (-32000,-32000). That launch fingerprint is far stronger than
            # size alone and remained stable in the user's v4.22 diagnostics.
            launch_position_match = left <= -30000 and top <= -30000
            launch_size_match = 600 <= width <= 1200 and 400 <= height <= 900
            score = area
            if not parent:
                score += 1_000_000
            if cls.value == "Chrome_WidgetWin_1":
                score += 10_000_000
            if width >= 500 and height >= 300:
                score += 3_000_000
            if launch_position_match:
                score += 20_000_000
            if launch_position_match and launch_size_match:
                score += 20_000_000
            found.append((score, area, width, height, left, top, _hwnd_int(hwnd), cls.value))
            return True

        user32.EnumWindows(enum_proc, 0)
        if found:
            found.sort(reverse=True)
            selected = found[0]
            session["main_window_candidates"] = [
                {"score": x[0], "area": x[1], "width": x[2], "height": x[3], "left": x[4], "top": x[5], "hwnd": x[6], "class": x[7]}
                for x in found
            ]
            session["main_hwnd"] = selected[6]
            session["main_class"] = selected[7]
            session["main_launch_fingerprint"] = bool(selected[4] <= -30000 and selected[5] <= -30000)
            return selected[6]
        time.sleep(0.10)
    raise RuntimeError("Could not find Chromium window for embedding")


def _hide_chromium_session_window(session):
    """Hide the non-headless compatibility engine's native Windows surface.

    The Chromium process remains fully windowed for site compatibility, but its
    HWND is never presented to the user. Tekzite owns the only visible browser
    surface and consumes Chromium merely as a DOM-producing JavaScript backend.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        hwnd = _find_chromium_window(session, timeout=2.0)
        ctypes.windll.user32.ShowWindow(_hwnd_int(hwnd), 0)  # SW_HIDE
        session["hidden_hwnd"] = _hwnd_int(hwnd)
        return True
    except Exception:
        # Off-screen launch still prevents focus theft if hiding races startup.
        return False


def _typed_user32():
    """Return user32 with pointer-sized HWND signatures configured.

    ctypes assumes plain C ``int`` arguments when a Win32 function has no
    ``argtypes``.  HWND values are pointer-sized on 64-bit Windows, so that
    default can raise ``OverflowError: int too long to convert`` before the
    API is even called.  Keep all native-window calls behind explicit Win32
    signatures.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.RedrawWindow.argtypes = [
        wintypes.HWND, ctypes.c_void_p, wintypes.HRGN, wintypes.UINT,
    ]
    user32.RedrawWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    return user32


def _hwnd_int(value):
    """Return a native HWND-like value as a Python int, safely on Python 3.14+.

    ``ctypes`` pointer scalars such as ``c_void_p``/``wintypes.HWND`` no
    longer reliably support ``int(pointer)``.  On Python 3.14 that operation
    can try to parse the pointer's raw bytes as decimal text and raise
    ``ValueError: invalid literal for int() with base 10: b'...'``.
    Always unwrap ``.value`` first and only then convert the numeric payload.
    """
    if value is None:
        return 0
    raw = getattr(value, "value", value)
    if raw is None:
        return 0
    if isinstance(raw, (bytes, bytearray)):
        return int.from_bytes(raw, byteorder="little", signed=False)
    return int(raw)


def _as_hwnd(value):
    """Convert a Python/Tk native window id to an HWND without narrowing."""
    from ctypes import wintypes
    return wintypes.HWND(_hwnd_int(value))


def _chromium_window_tree(session, timeout=0.0):
    """Return Chromium HWND metadata for the helper process tree.

    Chromium exposes a small native window hierarchy on Windows.  The outer
    ``Chrome_WidgetWin_1`` shell is not necessarily the surface that owns the
    rendered web contents.  Recording the hierarchy lets the embedder pick the
    actual render/content HWND instead of treating the browser frame as the
    page surface.
    """
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    process = session.get("process")
    if process is None:
        return []
    user32 = _typed_user32()
    deadline = time.monotonic() + max(0.0, float(timeout))

    while True:
        pids = _windows_descendant_pids(process.pid)
        rows = []
        top_handles = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def describe(hwnd, depth, top_hwnd):
            if not user32.IsWindow(_as_hwnd(hwnd)):
                return
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(_as_hwnd(hwnd), ctypes.byref(pid))
            if int(pid.value) not in pids:
                return
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(_as_hwnd(hwnd), cls, len(cls))
            rect = wintypes.RECT()
            if user32.GetWindowRect(_as_hwnd(hwnd), ctypes.byref(rect)):
                rect_tuple = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
            else:
                rect_tuple = None
            parent = user32.GetParent(_as_hwnd(hwnd))
            rows.append({
                "hwnd": _hwnd_int(hwnd),
                "parent": _hwnd_int(parent),
                "top_hwnd": _hwnd_int(top_hwnd),
                "pid": int(pid.value),
                "class": cls.value,
                "visible": bool(user32.IsWindowVisible(_as_hwnd(hwnd))),
                "rect": rect_tuple,
                "depth": int(depth),
            })

        @WNDENUMPROC
        def enum_top(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids:
                top_handles.append(_hwnd_int(hwnd))
            return True

        ctypes.windll.user32.EnumWindows(enum_top, 0)

        for top in top_handles:
            describe(top, 0, top)
            @WNDENUMPROC
            def enum_child(hwnd, lparam, _top=top):
                # EnumChildWindows recursively enumerates descendants.
                depth = 1
                parent = user32.GetParent(_as_hwnd(hwnd))
                seen = set()
                while parent and _hwnd_int(parent) != _hwnd_int(_top) and _hwnd_int(parent) not in seen:
                    seen.add(_hwnd_int(parent))
                    depth += 1
                    parent = user32.GetParent(parent)
                describe(_hwnd_int(hwnd), depth, _top)
                return True
            user32.EnumChildWindows(_as_hwnd(top), enum_child, 0)

        if rows or time.monotonic() >= deadline:
            return rows
        time.sleep(0.05)


def _is_descendant_of(hwnd, ancestor, user32=None):
    """Return True if hwnd belongs to ancestor's native child tree."""
    if not hwnd or not ancestor:
        return False
    user32 = user32 or _typed_user32()
    current = _as_hwnd(hwnd)
    seen = set()
    while current:
        value = _hwnd_int(current)
        if value == _hwnd_int(ancestor):
            return True
        if value in seen:
            break
        seen.add(value)
        current = user32.GetParent(current)
    return False


def _select_chromium_content_window(session, timeout=4.0):
    """Select a Chromium *owner widget* that contains the live page surface.

    v4.46 correctly discovered render hosts outside the launch shell, but
    re-parenting ``Chrome_RenderWidgetHostHWND`` itself can sever it from the
    Chromium widget/compositor hierarchy that presents its pixels.  Some Edge
    builds expose a healthy 792x516 render host below a zero-sized
    ``Chrome_WidgetWin_0``.  The child has convincing geometry but paints blank
    after being transplanted on its own.

    Use the render host as the locator, then embed the nearest Chromium widget
    that owns it.  The owner may initially be hidden/zero-sized; Tekzite will
    resize it after SetParent.  Preserve the render-host rectangle so the
    embedder can crop the owner's Chromium chrome and expose only page pixels.
    """
    deadline = time.monotonic() + max(0.1, float(timeout))
    last_tree = []
    user32 = _typed_user32() if os.name == "nt" else None
    main_hwnd = session.get("main_hwnd") or _find_chromium_window(session, timeout=timeout)
    session["outer_hwnd"] = _hwnd_int(main_hwnd)

    expected_w, expected_h = 800, 600
    try:
        for row in _chromium_window_tree(session):
            if _hwnd_int(row.get("hwnd") or 0) == _hwnd_int(main_hwnd) and row.get("rect"):
                x1, y1, x2, y2 = row["rect"]
                expected_w = max(1, int(x2) - int(x1))
                expected_h = max(1, int(y2) - int(y1))
                break
    except Exception:
        pass

    while time.monotonic() < deadline:
        tree = _chromium_window_tree(session)
        last_tree = tree
        by_hwnd = {_hwnd_int(r.get("hwnd") or 0): r for r in tree}
        render_candidates = []
        widget_candidates = []

        for row in tree:
            hwnd = _hwnd_int(row.get("hwnd") or 0)
            cls = row.get("class") or ""
            rect = row.get("rect")
            if not rect:
                width = height = area = 0
            else:
                width = max(0, int(rect[2]) - int(rect[0]))
                height = max(0, int(rect[3]) - int(rect[1]))
                area = width * height

            in_main_tree = (
                _hwnd_int(row.get("top_hwnd") or 0) == _hwnd_int(main_hwnd)
                or _is_descendant_of(hwnd, main_hwnd, user32)
            )

            if cls == "Chrome_RenderWidgetHostHWND" or "RenderWidgetHost" in cls:
                # Reject genuinely dead utility hosts. A page host needs a
                # meaningful viewport even if its owning widget is hidden.
                if width < 200 or height < 150:
                    continue

                owner = None
                current_parent = _hwnd_int(row.get("parent") or 0)
                seen = set()
                while current_parent and current_parent not in seen:
                    seen.add(current_parent)
                    candidate = by_hwnd.get(current_parent)
                    if candidate and str(candidate.get("class") or "").startswith("Chrome_WidgetWin"):
                        owner = candidate
                        break
                    if candidate:
                        current_parent = _hwnd_int(candidate.get("parent") or 0)
                    elif user32 is not None:
                        current_parent = _hwnd_int(user32.GetParent(_as_hwnd(current_parent)))
                    else:
                        break
                if owner is None:
                    continue

                dw = abs(width - expected_w)
                dh = abs(height - expected_h)
                geometry_bonus = max(0, 600 - (dw + dh))
                score = 5000 + geometry_bonus + min(area // 10000, 400)
                if in_main_tree:
                    score += 150
                if row.get("visible"):
                    score += 25
                render_candidates.append((score, area, -row.get("depth", 0), row, owner))
                continue

            # Compatibility fallback when Chromium exposes no RWH.
            if width < 200 or height < 150:
                continue
            if in_main_tree and cls.startswith("Chrome_WidgetWin") and row.get("depth", 0) > 0:
                score = 1000 + min(area // 10000, 300)
                if row.get("visible"):
                    score += 25
                widget_candidates.append((score, area, -row.get("depth", 0), row))

        if render_candidates:
            render_candidates.sort(reverse=True, key=lambda item: item[:3])
            _, _, _, render_row, owner_row = render_candidates[0]
            session["window_tree"] = tree
            session["render_hwnd"] = _hwnd_int(render_row["hwnd"])
            session["render_class"] = render_row.get("class") or ""
            session["render_rect"] = render_row.get("rect")
            session["content_hwnd"] = _hwnd_int(owner_row["hwnd"])
            session["content_class"] = owner_row.get("class") or ""
            session["content_top_hwnd"] = _hwnd_int(owner_row.get("top_hwnd") or owner_row.get("hwnd") or 0)
            session["content_selection"] = "render-host owner-widget"
            session["content_expected_size"] = (expected_w, expected_h)
            return _hwnd_int(owner_row["hwnd"])

        if widget_candidates:
            widget_candidates.sort(reverse=True, key=lambda item: item[:3])
            selected = widget_candidates[0][3]
            session["window_tree"] = tree
            session["content_hwnd"] = _hwnd_int(selected["hwnd"])
            session["content_class"] = selected.get("class") or ""
            session["content_top_hwnd"] = _hwnd_int(selected.get("top_hwnd") or 0)
            session["content_selection"] = "main-tree descendant"
            return _hwnd_int(selected["hwnd"])
        time.sleep(0.10)

    session["window_tree"] = last_tree
    session["content_hwnd"] = _hwnd_int(main_hwnd)
    session["content_class"] = session.get("main_class") or "Chrome_WidgetWin_1"
    session["content_top_hwnd"] = _hwnd_int(main_hwnd)
    session["content_selection"] = "main-window fallback"
    return _hwnd_int(main_hwnd)



def _apply_tekzite_chromium_branding(session):
    """Remove visible host-browser branding from Tekzite's helper window.

    The rendering engine remains Chromium-family, but its native top-level
    helper must never advertise itself as a separate Edge application.  Give
    the helper a Tekzite title and tool-window identity so it does not create
    a normal taskbar/app-window presence while it is being re-parented.
    """
    if os.name != "nt" or not session:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _typed_user32()
        user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        user32.SetWindowTextW.restype = wintypes.BOOL
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long

        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        changed = False
        seen = set()
        for key in ("outer_hwnd", "main_hwnd", "content_top_hwnd"):
            raw = session.get(key)
            if not raw:
                continue
            hwnd = _as_hwnd(raw)
            value = _hwnd_int(raw)
            if not value or value in seen or not user32.IsWindow(hwnd):
                continue
            seen.add(value)
            user32.SetWindowTextW(hwnd, "Tekzite Browser")
            exstyle = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE)) & 0xFFFFFFFF
            exstyle = (exstyle | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
            signed = ctypes.c_long(exstyle).value
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, signed)
            changed = True
        if changed:
            session["branding"] = "Tekzite Browser"
            session["taskbar_identity"] = "toolwindow"
        return changed
    except Exception:
        return False

def embedded_chromium_debug_report():
    """Human-readable native-window diagnostics for Copy Full Debug."""
    session = _EDGE_SESSION or {}
    lines = ["EMBEDDED CHROMIUM WINDOW DEBUG", "-" * 80]
    process = session.get("process")
    launch = _CHROMIUM_LAUNCH_DEBUG or {}
    lines.append(f"launch_attempts: {launch.get('attempts')}")
    lines.append(f"launch_executable: {launch.get('executable')}")
    lines.append(f"launch_port: {launch.get('port')}")
    lines.append(f"launch_profile: {launch.get('profile')}")
    lines.append(f"launch_recovered: {launch.get('recovered')}")
    lines.append(f"launch_last_error: {launch.get('last_error')}")
    lines.append(f"launch_errors: {launch.get('errors')}")
    lines.append(f"launch_handoff_detected: {launch.get('handoff_detected')}")
    lines.append(f"launch_original_pid: {launch.get('original_pid')}")
    lines.append(f"launch_adopted_pid: {launch.get('adopted_pid')}")
    lines.append(f"launch_launcher_exit_code: {launch.get('launcher_exit_code')}")
    lines.append(f"launch_profile_processes_found: {launch.get('profile_processes_found')}")
    lines.append(f"launch_profile_processes_terminated: {launch.get('profile_processes_terminated')}")
    lines.append(f"launch_geometry_requested: {launch.get('launch_geometry_requested')}")
    lines.append(f"native_occlusion_disabled: {launch.get('native_occlusion_disabled')}")
    lines.append(f"renderer_backgrounding_disabled: {launch.get('renderer_backgrounding_disabled')}")
    lines.append(f"background_timer_throttling_disabled: {launch.get('background_timer_throttling_disabled')}")
    lines.append(f"occluded_window_backgrounding_disabled: {launch.get('occluded_window_backgrounding_disabled')}")
    lines.append(f"launch_effective_flags: {launch.get('launch_effective_flags')}")
    lines.append(f"typography_lcd_text_enabled: {launch.get('typography_lcd_text_enabled')}")
    lines.append(f"typography_subpixel_positioning_enabled: {launch.get('typography_subpixel_positioning_enabled')}")
    lines.append(f"typography_directwrite_ui_enabled: {launch.get('typography_directwrite_ui_enabled')}")
    lines.append(f"typography_css_override_used: {launch.get('typography_css_override_used')}")
    lines.append(f"launch_geometry: {session.get('launch_geometry')}")
    lines.append(f"native_launch_in_place: {session.get('native_launch_in_place')}")
    lines.append(f"native_launch_geometry: {session.get('native_launch_geometry')}")
    lines.append(f"native_app_target_reused: {session.get('native_app_target_reused')}")
    lines.append(f"native_app_target_id: {session.get('native_app_target_id')}")
    lines.append(f"native_app_target_reuse_error: {session.get('native_app_target_reuse_error')}")
    lines.append(f"native_app_target_strict: {session.get('native_app_target_strict')}")
    lines.append(f"native_direct_app_launch: {session.get('native_direct_app_launch')}")
    lines.append(f"native_direct_app_url: {session.get('native_direct_app_url')}")
    lines.append(f"native_direct_app_target_match: {session.get('native_direct_app_target_match')}")
    lines.append(f"native_direct_app_navigation_skipped: {session.get('native_direct_app_navigation_skipped')}")
    lines.append(f"helper_pid: {getattr(process, 'pid', None)}")
    lines.append(f"embedded_hwnd: {session.get('embedded_hwnd')}")
    lines.append(f"content_hwnd: {session.get('content_hwnd')}")
    lines.append(f"content_class: {session.get('content_class')}")
    lines.append(f"outer_hwnd: {session.get('outer_hwnd')}")
    lines.append(f"main_hwnd: {session.get('main_hwnd')}")
    lines.append(f"main_class: {session.get('main_class')}")
    lines.append(f"main_launch_fingerprint: {session.get('main_launch_fingerprint')}")
    lines.append(f"content_selection: {session.get('content_selection')}")
    lines.append(f"pre_attach_owner_validated: {session.get('pre_attach_owner_validated')}")
    lines.append(f"pre_attach_owner_reselected: {session.get('pre_attach_owner_reselected')}")
    lines.append(f"pre_attach_owner_hwnd: {session.get('pre_attach_owner_hwnd')}")
    lines.append(f"pre_attach_owner_rejected_hwnd: {session.get('pre_attach_owner_rejected_hwnd')}")
    lines.append(f"pre_attach_owner_error: {session.get('pre_attach_owner_error')}")
    lines.append(f"chrome_crop: {session.get('chrome_crop')}")
    lines.append(f"live_render_crop: {session.get('live_render_crop')}")
    lines.append(f"live_render_crop_raw: {session.get('live_render_crop_raw')}")
    lines.append(f"live_render_crop_normalized: {session.get('live_render_crop_normalized')}")
    lines.append(f"live_render_owner_size: {session.get('live_render_owner_size')}")
    lines.append(f"live_render_host_size: {session.get('live_render_host_size')}")
    lines.append(f"live_render_crop_space: {session.get('live_render_crop_space')}")
    lines.append(f"render_host_geometry_owned_by: {session.get('render_host_geometry_owned_by')}")
    lines.append(f"live_render_crop_error: {session.get('live_render_crop_error')}")
    lines.append(f"owner_locked_render_refresh: {session.get('owner_locked_render_refresh')}")
    lines.append(f"owner_locked_render_count: {session.get('owner_locked_render_count')}")
    lines.append(f"owner_locked_render_size: {session.get('owner_locked_render_size')}")
    lines.append(f"owner_locked_render_hwnd: {session.get('owner_locked_render_hwnd')}")
    lines.append(f"owner_locked_render_error: {session.get('owner_locked_render_error')}")
    lines.append(f"post_attach_crop_corrected: {session.get('post_attach_crop_corrected')}")
    lines.append(f"post_resize_crop_corrected: {session.get('post_resize_crop_corrected')}")
    lines.append(f"embedded_parent_client_size: {session.get('embedded_parent_client_size')}")
    lines.append(f"render_host_forced_visible: {session.get('render_host_forced_visible')}")
    lines.append(f"render_host_embedded_size: {session.get('render_host_embedded_size')}")
    lines.append(f"cold_start_geometry_wait: {session.get('cold_start_geometry_wait')}")
    lines.append(f"cold_start_expected_size: {session.get('cold_start_expected_size')}")
    lines.append(f"cold_start_render_size: {session.get('cold_start_render_size')}")
    lines.append(f"cold_start_resize_kick_attempted: {session.get('cold_start_resize_kick_attempted')}")
    lines.append(f"cold_start_resize_before: {session.get('cold_start_resize_before')}")
    lines.append(f"cold_start_resize_after: {session.get('cold_start_resize_after')}")
    lines.append(f"cold_start_resize_kick_error: {session.get('cold_start_resize_kick_error')}")
    lines.append(f"compositor_prime_attempted: {session.get('compositor_prime_attempted')}")
    lines.append(f"compositor_prime_skipped: {session.get('compositor_prime_skipped')}")
    lines.append(f"compositor_prime_render_touched: {session.get('compositor_prime_render_touched')}")
    lines.append(f"compositor_prime_owner_touched: {session.get('compositor_prime_owner_touched')}")
    lines.append(f"render_host_hands_off: {session.get('render_host_hands_off')}")
    lines.append(f"render_host_mutation_calls: {session.get('render_host_mutation_calls')}")
    lines.append(f"compositor_prime_owner_visible: {session.get('compositor_prime_owner_visible')}")
    lines.append(f"compositor_prime_render_visible: {session.get('compositor_prime_render_visible')}")
    lines.append(f"compositor_prime_owner_size: {session.get('compositor_prime_owner_size')}")
    lines.append(f"compositor_prime_render_size: {session.get('compositor_prime_render_size')}")
    lines.append(f"compositor_prime_error: {session.get('compositor_prime_error')}")
    lines.append(f"first_frame_ready: {session.get('first_frame_ready')}")
    lines.append(f"first_frame_committed: {session.get('first_frame_committed')}")
    lines.append(f"navigation_generation: {session.get('navigation_generation')}")
    lines.append(f"first_frame_generation: {session.get('first_frame_generation')}")
    lines.append(f"attached_frame_generation: {session.get('attached_frame_generation')}")
    lines.append(f"attached_frame_stale_generation: {session.get('attached_frame_stale_generation')}")
    lines.append(f"first_frame_ready_state: {session.get('first_frame_ready_state')}")
    lines.append(f"first_frame_text_len: {session.get('first_frame_text_len')}")
    lines.append(f"first_frame_nodes: {session.get('first_frame_nodes')}")
    lines.append(f"first_frame_png_chars: {session.get('first_frame_png_chars')}")
    lines.append(f"first_frame_probe: {session.get('first_frame_probe')}")
    lines.append(f"first_frame_empty_shell_rejected: {session.get('first_frame_empty_shell_rejected')}")
    lines.append(f"first_frame_blank_png_rejected: {session.get('first_frame_blank_png_rejected')}")
    lines.append(f"first_frame_visual_black_ratio: {session.get('first_frame_visual_black_ratio')}")
    lines.append(f"first_frame_visual_white_ratio: {session.get('first_frame_visual_white_ratio')}")
    lines.append(f"first_frame_visual_span: {session.get('first_frame_visual_span')}")
    lines.append(f"first_frame_preattach_timeout: {session.get('first_frame_preattach_timeout')}")
    lines.append(f"attached_frame_timeout: {session.get('attached_frame_timeout')}")
    lines.append(f"attached_frame_ready_state: {session.get('attached_frame_ready_state')}")
    lines.append(f"attached_frame_text_len: {session.get('attached_frame_text_len')}")
    lines.append(f"attached_frame_nodes: {session.get('attached_frame_nodes')}")
    lines.append(f"attached_frame_png_chars: {session.get('attached_frame_png_chars')}")
    lines.append(f"attached_frame_visual: {session.get('attached_frame_visual')}")
    lines.append(f"post_interaction_blank_confirmed: {session.get('post_interaction_blank_confirmed')}")
    lines.append(f"post_interaction_recovered: {session.get('post_interaction_recovered')}")
    lines.append(f"post_interaction_probe_error: {session.get('post_interaction_probe_error')}")
    lines.append(f"visible_surface_probe_attempt: {session.get('visible_surface_probe_attempt')}")
    lines.append(f"visible_surface_blank: {session.get('visible_surface_blank')}")
    lines.append(f"visible_surface_span: {session.get('visible_surface_span')}")
    lines.append(f"visible_surface_dominant_ratio: {session.get('visible_surface_dominant_ratio')}")
    lines.append(f"visible_surface_software_fallback: {session.get('visible_surface_software_fallback')}")
    lines.append(f"visible_surface_probe_error: {session.get('visible_surface_probe_error')}")
    lines.append(f"native_resize_recovery_attempted: {session.get('native_resize_recovery_attempted')}")
    lines.append(f"native_resize_recovery_viewport: {session.get('native_resize_recovery_viewport')}")
    lines.append(f"native_resize_recovery_succeeded: {session.get('native_resize_recovery_succeeded')}")
    lines.append(f"native_geometry_sync_attempted: {session.get('native_geometry_sync_attempted')}")
    lines.append(f"native_geometry_sync_requested: {session.get('native_geometry_sync_requested')}")
    lines.append(f"native_geometry_sync_render_size: {session.get('native_geometry_sync_render_size')}")
    lines.append(f"native_geometry_sync_succeeded: {session.get('native_geometry_sync_succeeded')}")
    lines.append(f"native_geometry_sync_error: {session.get('native_geometry_sync_error')}")
    lines.append(f"native_recovery_render_stable: {session.get('native_recovery_render_stable')}")
    lines.append(f"native_recovery_render_hwnd: {session.get('native_recovery_render_hwnd')}")
    lines.append(f"native_recovery_render_size: {session.get('native_recovery_render_size')}")
    lines.append(f"native_overlay_region_reapplied: {session.get('native_overlay_region_reapplied')}")
    lines.append(f"native_embed_mode: {session.get('native_embed_mode')}")
    lines.append(f"native_setparent_used: {session.get('native_setparent_used')}")
    lines.append(f"dwm_thumbnail_registered: {session.get('dwm_thumbnail_registered')}")
    lines.append(f"dwm_thumbnail_visible: {session.get('dwm_thumbnail_visible')}")
    lines.append(f"dwm_thumbnail_error: {session.get('dwm_thumbnail_error')}")
    lines.append(f"dwm_source_hwnd: {session.get('dwm_source_hwnd')}")
    lines.append(f"dwm_destination_hwnd: {session.get('dwm_destination_hwnd')}")
    lines.append(f"dwm_destination_requested_hwnd: {session.get('dwm_destination_requested_hwnd')}")
    lines.append(f"dwm_destination_resolved_hwnd: {session.get('dwm_destination_resolved_hwnd')}")
    lines.append(f"dwm_destination_class: {session.get('dwm_destination_class')}")
    lines.append(f"dwm_destination_pid: {session.get('dwm_destination_pid')}")
    lines.append(f"dwm_destination_is_top_level: {session.get('dwm_destination_is_top_level')}")
    lines.append(f"dwm_source_requested_hwnd: {session.get('dwm_source_requested_hwnd')}")
    lines.append(f"dwm_source_resolved_hwnd: {session.get('dwm_source_resolved_hwnd')}")
    lines.append(f"dwm_source_class: {session.get('dwm_source_class')}")
    lines.append(f"dwm_source_pid: {session.get('dwm_source_pid')}")
    lines.append(f"dwm_source_is_top_level: {session.get('dwm_source_is_top_level')}")
    lines.append(f"dwm_registering_process_pid: {session.get('dwm_registering_process_pid')}")
    lines.append(f"dwm_source_mapped: {session.get('dwm_source_mapped')}")
    lines.append(f"dwm_source_parked: {session.get('dwm_source_parked')}")
    lines.append(f"dwm_source_park_position: {session.get('dwm_source_park_position')}")
    lines.append(f"dwm_source_prepositioned_before_show: {session.get('dwm_source_prepositioned_before_show')}")
    lines.append(f"chromium_launch_offscreen: {bool(session.get('launch_geometry') and session.get('launch_geometry')[0] <= -30000)}")
    lines.append(f"dwm_chromium_presenter_count: {session.get('dwm_chromium_presenter_count')}")
    lines.append(f"dwm_aux_presenters_visible_before_park: {session.get('dwm_aux_presenters_visible_before_park')}")
    lines.append(f"dwm_presenter_park_error: {session.get('dwm_presenter_park_error')}")
    for i, row in enumerate((session.get("dwm_chromium_presenters_parked") or [])[:12], 1):
        lines.append(f"  dwm_presenter[{i}]: {row}")
    lines.append(f"dwm_source_window_size: {session.get('dwm_source_window_size')}")
    lines.append(f"dwm_source_client_only: {session.get('dwm_source_client_only')}")
    lines.append(f"dwm_source_client_size_before: {session.get('dwm_source_client_size_before')}")
    lines.append(f"dwm_source_client_size: {session.get('dwm_source_client_size')}")
    lines.append(f"dwm_source_nonclient_margins: {session.get('dwm_source_nonclient_margins')}")
    lines.append(f"dwm_custom_chrome_height: {session.get('dwm_custom_chrome_height')}")
    lines.append(f"dwm_chrome_height_locked: {session.get('dwm_chrome_height_locked')}")
    lines.append(f"dwm_chrome_candidate: {session.get('dwm_chrome_candidate')}")
    lines.append(f"dwm_chrome_pending_candidate: {session.get('dwm_chrome_pending_candidate')}")
    lines.append(f"dwm_chrome_pending_count: {session.get('dwm_chrome_pending_count')}")
    lines.append(f"dwm_chrome_height_committed: {session.get('dwm_chrome_height_committed')}")
    lines.append(f"dwm_source_resize_skipped_stable: {session.get('dwm_source_resize_skipped_stable')}")
    lines.append(f"dwm_render_size_before_chrome_expand: {session.get('dwm_render_size_before_chrome_expand')}")
    lines.append(f"dwm_render_size_after_chrome_expand: {session.get('dwm_render_size_after_chrome_expand')}")
    lines.append(f"dwm_source_crop: {session.get('dwm_source_crop')}")
    lines.append(f"dwm_navigation_recrop_count: {session.get('dwm_navigation_recrop_count')}")
    lines.append(f"dwm_navigation_recrop_render_hwnd: {session.get('dwm_navigation_recrop_render_hwnd')}")
    lines.append(f"dwm_source_render_hwnd: {session.get('dwm_source_render_hwnd')}")
    lines.append(f"dwm_source_render_offset: {session.get('dwm_source_render_offset')}")
    lines.append(f"dwm_source_render_offset_after_expand: {session.get('dwm_source_render_offset_after_expand')}")
    lines.append(f"dwm_source_render_size: {session.get('dwm_source_render_size')}")
    lines.append(f"dwm_chrome_measurement: {session.get('dwm_chrome_measurement')}")
    lines.append(f"dwm_thumbnail_source_rect: {session.get('dwm_thumbnail_source_rect')}")
    lines.append(f"dwm_thumbnail_destination_rect: {session.get('dwm_thumbnail_destination_rect')}")
    lines.append(f"dwm_input_offset: {session.get('dwm_input_offset')}")
    lines.append(f"dwm_input_render_offset: {session.get('dwm_input_render_offset')}")
    lines.append(f"dwm_input_page_owner_rect: {session.get('dwm_input_page_owner_rect')}")
    lines.append(f"dwm_input_render_rect: {session.get('dwm_input_render_rect')}")
    lines.append(f"dwm_input_transform_error: {session.get('dwm_input_transform_error')}")
    lines.append(f"dwm_input_zoom_factor: {session.get('dwm_input_zoom_factor')}")
    lines.append(f"dwm_input_zoom_active: {session.get('dwm_input_zoom_active')}")
    lines.append(f"dwm_zoom_percent: {session.get('dwm_zoom_percent')}")
    lines.append(f"preferences_zoom_percent: {session.get('preferences_zoom_percent')}")
    lines.append(f"page_zoom_strategy: {session.get('page_zoom_strategy')}")
    lines.append(f"zoom_watchdog_strategy: {session.get('zoom_watchdog_strategy')}")
    lines.append(f"native_zoom_extension_id: {session.get('native_zoom_extension_id')}")
    lines.append(f"native_zoom_extension_loaded: {session.get('native_zoom_extension_loaded')}")
    lines.append(f"native_zoom_bridge_apply_count: {session.get('native_zoom_bridge_apply_count')}")
    lines.append(f"native_zoom_bridge_last_title: {session.get('native_zoom_bridge_last_title')}")
    lines.append(f"native_zoom_bridge_error: {session.get('native_zoom_bridge_error')}")
    lines.append(f"zoom_watchdog_expected_percent: {session.get('zoom_watchdog_expected_percent')}")
    lines.append(f"zoom_watchdog_last_observed: {session.get('zoom_watchdog_last_observed')}")
    lines.append(f"preferences_zoom_seeded_before_target: {session.get('preferences_zoom_seeded_before_target')}")
    lines.append(f"preferences_zoom_pre_navigation_applied: {session.get('preferences_zoom_pre_navigation_applied')}")
    lines.append(f"preferences_zoom_post_navigation_applied: {session.get('preferences_zoom_post_navigation_applied')}")
    lines.append(f"dwm_zoom_refresh_count: {session.get('dwm_zoom_refresh_count')}")
    lines.append(f"dwm_thumbnail_scale_x: {session.get('dwm_thumbnail_scale_x')}")
    lines.append(f"dwm_thumbnail_scale_y: {session.get('dwm_thumbnail_scale_y')}")
    lines.append(f"native_overlay_root: {session.get('native_overlay_root')}")
    lines.append(f"native_overlay_screen_origin: {session.get('native_overlay_screen_origin')}")
    lines.append(f"native_owner_seed_crop: {session.get('native_owner_seed_crop')}")
    lines.append(f"native_owner_seed_rect: {session.get('native_owner_seed_rect')}")
    lines.append(f"native_owner_mapped_before_measure: {session.get('native_owner_mapped_before_measure')}")
    lines.append(f"native_owner_visible_before_measure: {session.get('native_owner_visible_before_measure')}")
    lines.append(f"native_render_visible_before_measure: {session.get('native_render_visible_before_measure')}")
    lines.append(f"native_owner_rect_before_measure: {session.get('native_owner_rect_before_measure')}")
    lines.append(f"native_render_rect_before_measure: {session.get('native_render_rect_before_measure')}")
    lines.append(f"native_geometry_crop_measured: {session.get('native_geometry_crop_measured')}")
    lines.append(f"native_geometry_crop_raw_after_map: {session.get('native_geometry_crop_raw_after_map')}")
    lines.append(f"native_geometry_visible_rect_before: {session.get('native_geometry_visible_rect_before')}")
    lines.append(f"native_geometry_visible_size_before: {session.get('native_geometry_visible_size_before')}")
    lines.append(f"native_geometry_render_overflow: {session.get('native_geometry_render_overflow')}")
    lines.append(f"native_geometry_target_owner: {session.get('native_geometry_target_owner')}")
    lines.append(f"native_geometry_second_pass_needed: {session.get('native_geometry_second_pass_needed')}")
    lines.append(f"native_geometry_final_owner_rect: {session.get('native_geometry_final_owner_rect')}")
    lines.append(f"native_geometry_final_render_rect: {session.get('native_geometry_final_render_rect')}")
    lines.append(f"native_geometry_final_render_size: {session.get('native_geometry_final_render_size')}")
    lines.append(f"native_geometry_final_visible_rect: {session.get('native_geometry_final_visible_rect')}")
    lines.append(f"native_geometry_final_visible_size: {session.get('native_geometry_final_visible_size')}")
    lines.append(f"native_geometry_page_aligned: {session.get('native_geometry_page_aligned')}")
    lines.append(f"native_overlay_error: {session.get('native_overlay_error')}")
    lines.append(f"native_overlay_preposition_rect: {session.get('native_overlay_preposition_rect')}")
    lines.append(f"native_overlay_position_reapplied: {session.get('native_overlay_position_reapplied')}")
    lines.append(f"native_overlay_owner_assigned: {session.get('native_overlay_owner_assigned')}")
    lines.append(f"native_overlay_style_mutated: {session.get('native_overlay_style_mutated')}")
    lines.append(f"native_overlay_render_forced: {session.get('native_overlay_render_forced')}")
    lines.append(f"native_overlay_region_used: {session.get('native_overlay_region_used')}")
    lines.append(f"embedded_after_first_frame: {session.get('embedded_after_first_frame')}")
    lines.append(f"presentation_mode: {session.get('presentation_mode')}")
    lines.append(f"tab_switch_fast_path_count: {session.get('tab_switch_fast_path_count', 0)}")
    lines.append(f"branding: {session.get('branding')}")
    lines.append(f"taskbar_identity: {session.get('taskbar_identity')}")
    lines.append(f"activation_pulse_sent: {session.get('activation_pulse_sent')}")
    lines.append(f"activation_pulse_root: {session.get('activation_pulse_root')}")
    lines.append(f"activation_pulse_dwm_flush: {session.get('activation_pulse_dwm_flush')}")
    lines.append(f"activation_pulse_error: {session.get('activation_pulse_error')}")
    lines.append(f"post_activation_crop_reapplied: {session.get('post_activation_crop_reapplied')}")
    lines.append(f"post_activation_crop: {session.get('post_activation_crop')}")
    lines.append(f"post_activation_crop_attempts: {session.get('post_activation_crop_attempts')}")
    lines.append(f"post_activation_crop_dwm_flush: {session.get('post_activation_crop_dwm_flush')}")
    lines.append(f"post_activation_crop_error: {session.get('post_activation_crop_error')}")
    lines.append(f"wake_dwm_flush: {session.get('wake_dwm_flush')}")
    lines.append(f"focus_hwnd: {session.get('focus_hwnd')}")
    lines.append(f"focus_target_class: {session.get('focus_target_class')}")
    lines.append(f"focus_root_activated: {session.get('focus_root_activated')}")
    lines.append(f"focus_error: {session.get('focus_error')}")
    main_candidates = session.get("main_window_candidates") or []
    lines.append(f"main_candidates: {len(main_candidates)}")
    for i, row in enumerate(main_candidates[:10], 1):
        lines.append(f"  main[{i}] hwnd={row.get('hwnd')} class={row.get('class')!r} pos=({row.get('left')},{row.get('top')}) size={row.get('width')}x{row.get('height')} score={row.get('score')}")
    tree = session.get("window_tree") or []
    lines.append(f"windows_recorded: {len(tree)}")
    if not tree and session:
        try:
            tree = _chromium_window_tree(session)
            session["window_tree"] = tree
        except Exception as exc:
            lines.append(f"window_tree_error: {exc}")
            tree = []
    for i, row in enumerate(tree[:60], 1):
        lines.append(
            f"[{i}] depth={row.get('depth')} hwnd={row.get('hwnd')} "
            f"parent={row.get('parent')} pid={row.get('pid')} "
            f"visible={row.get('visible')} class={row.get('class')!r} "
            f"rect={row.get('rect')}"
        )
    if len(tree) > 60:
        lines.append(f"... {len(tree) - 60} more windows omitted")
    return "\n".join(lines)



def _native_client_size(hwnd, fallback_width=1, fallback_height=1):
    """Return the actual Win32 client size for a host HWND.

    Tk event/winfo dimensions may be DPI-virtualized on Windows.  Chromium's
    native child windows use Win32 device pixels, so querying the host HWND is
    the authoritative size for native embedding.
    """
    width = max(1, int(fallback_width or 1))
    height = max(1, int(fallback_height or 1))
    if os.name != "nt" or not hwnd:
        return width, height
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        rect = wintypes.RECT()
        if user32.GetClientRect(_as_hwnd(hwnd), ctypes.byref(rect)):
            real_w = max(1, int(rect.right) - int(rect.left))
            real_h = max(1, int(rect.bottom) - int(rect.top))
            # A freshly-created but still-unmapped Tk host commonly reports
            # 1x1.  That is a lifecycle placeholder, not an authoritative
            # Chromium viewport.  Never let it collapse an already-known
            # content size to a postage stamp.
            min_ready = 64
            if real_w < min_ready or real_h < min_ready:
                if width >= min_ready and height >= min_ready:
                    return width, height
            return real_w, real_h
    except Exception:
        pass
    return width, height





def _validate_embed_owner_before_reparent(session, candidate_hwnd, expected_width=None, expected_height=None):
    """Validate the Chromium owner immediately before SetParent().

    Chromium can swap RenderWidgetHost ownership after the first-frame probe.
    A Chrome_WidgetWin that was correct a few milliseconds earlier may remain
    as a valid HWND but no longer own any drawable page surface. Reparenting
    that stale widget gives Tekzite a permanent black frame.

    Keep an already-good owner, but if it no longer contains a meaningful
    RenderWidgetHost, reselect from a fresh Chromium window tree. The chosen
    owner is only considered valid when a real page-sized render host is still
    its descendant at the moment we are about to embed it.
    """
    if os.name != "nt" or not session:
        return _hwnd_int(candidate_hwnd or 0)
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        ew = max(1, int(expected_width or 1280))
        eh = max(1, int(expected_height or 720))

        def inspect(owner_raw):
            owner = _hwnd_int(owner_raw or 0)
            if not owner or not user32.IsWindow(_as_hwnd(owner)):
                return None
            rows = []
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            @WNDENUMPROC
            def enum_child(hwnd, lparam):
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, len(cls))
                name = cls.value
                if name == "Chrome_RenderWidgetHostHWND" or "RenderWidgetHost" in name:
                    rect = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        rw = max(0, int(rect.right) - int(rect.left))
                        rh = max(0, int(rect.bottom) - int(rect.top))
                        if rw >= 200 and rh >= 150:
                            delta = abs(rw - ew) + abs(rh - eh)
                            area = rw * rh
                            visible_bonus = 50000 if user32.IsWindowVisible(hwnd) else 0
                            score = area + max(0, 300000 - delta * 250) + visible_bonus
                            rows.append((score, area, -delta, _hwnd_int(hwnd), name,
                                         (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))))
                return True

            user32.EnumChildWindows(_as_hwnd(owner), enum_child, 0)
            if not rows:
                return None
            rows.sort(reverse=True, key=lambda item: item[:3])
            return rows[0], len(rows)

        original = _hwnd_int(candidate_hwnd or 0)
        found = inspect(original)
        if found:
            row, count = found
            _, _, _, render, cls, rect = row
            session["pre_attach_owner_validated"] = True
            session["pre_attach_owner_reselected"] = False
            session["pre_attach_owner_hwnd"] = original
            session["render_hwnd"] = render
            session["render_class"] = cls
            session["render_rect"] = rect
            session["owner_locked_render_count"] = count
            return original

        session["pre_attach_owner_validated"] = False
        session["pre_attach_owner_rejected_hwnd"] = original or None

        # Do not let an old embedded_hwnd outrank the freshly selected owner
        # while recovering. _select_chromium_content_window() updates
        # content_hwnd/render_hwnd from the current process tree.
        old_embedded = session.get("embedded_hwnd")
        session["embedded_hwnd"] = None
        selected = _select_chromium_content_window(session, timeout=1.25)
        found = inspect(selected)
        if not found:
            # The main browser widget is a final safe candidate. This is the
            # exact topology seen when Chromium moved the RWH out of a transient
            # Chrome_WidgetWin_0 during YouTube startup/consent.
            main = _hwnd_int(session.get("main_hwnd") or 0)
            found_main = inspect(main)
            if found_main:
                selected = main
                found = found_main
                session["content_hwnd"] = main
                session["content_class"] = session.get("main_class") or "Chrome_WidgetWin_1"
                session["content_selection"] = "main-owner live-render fallback"

        if found:
            row, count = found
            _, _, _, render, cls, rect = row
            session["render_hwnd"] = render
            session["render_class"] = cls
            session["render_rect"] = rect
            session["owner_locked_render_count"] = count
            session["pre_attach_owner_validated"] = True
            session["pre_attach_owner_reselected"] = (_hwnd_int(selected) != original)
            session["pre_attach_owner_hwnd"] = _hwnd_int(selected)
            return _hwnd_int(selected)

        # Restore the old field for diagnostics only; attach will fail safely
        # rather than embedding a known owner with no live render surface.
        session["embedded_hwnd"] = old_embedded
        session["pre_attach_owner_error"] = "no live RenderWidgetHost owner"
        return 0
    except Exception as exc:
        session["pre_attach_owner_validated"] = False
        session["pre_attach_owner_error"] = str(exc)
        return 0


def _refresh_render_host_within_owner(session, expected_width=None, expected_height=None):
    """Refresh only the RenderWidgetHost *inside the already selected owner*.

    v4.71/v4.72 tried to follow Chromium navigation by switching Tekzite to a
    different Chrome_WidgetWin owner.  That can pick an inactive compositor
    owner that has perfect geometry but paints only black.  v4.73 keeps the
    known-good v4.70 owner fixed and is allowed to refresh only the page render
    host that is a descendant of that owner.  This preserves compositor
    ownership while still following RWH swaps inside the live browser window.
    """
    if os.name != "nt" or not session:
        return False
    owner = _hwnd_int(session.get("embedded_hwnd") or session.get("content_hwnd") or 0)
    if not owner:
        session["owner_locked_render_refresh"] = False
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(owner)):
            session["owner_locked_render_refresh"] = False
            return False

        ew = max(1, int(expected_width or (session.get("embedded_size") or (1280, 720))[0] or 1280))
        eh = max(1, int(expected_height or (session.get("embedded_size") or (1280, 720))[1] or 720))
        rows = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @WNDENUMPROC
        def enum_child(hwnd, lparam):
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, len(cls))
            name = cls.value
            if name == "Chrome_RenderWidgetHostHWND" or "RenderWidgetHost" in name:
                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    rw = max(0, int(rect.right) - int(rect.left))
                    rh = max(0, int(rect.bottom) - int(rect.top))
                    if rw >= 200 and rh >= 150:
                        delta = abs(rw - ew) + abs(rh - eh)
                        area = rw * rh
                        visible_bonus = 50000 if user32.IsWindowVisible(hwnd) else 0
                        score = area + max(0, 300000 - delta * 250) + visible_bonus
                        rows.append((score, area, -delta, _hwnd_int(hwnd), name,
                                     (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))))
            return True

        user32.EnumChildWindows(_as_hwnd(owner), enum_child, 0)
        if not rows:
            session["owner_locked_render_refresh"] = False
            session["owner_locked_render_count"] = 0
            return False
        rows.sort(reverse=True, key=lambda item: item[:3])
        _, _, _, render, cls, rect = rows[0]
        session["render_hwnd"] = render
        session["render_class"] = cls
        session["render_rect"] = rect
        session["owner_locked_render_refresh"] = True
        session["owner_locked_render_count"] = len(rows)
        session["owner_locked_render_size"] = (rect[2]-rect[0], rect[3]-rect[1])
        session["owner_locked_render_hwnd"] = render
        return True
    except Exception as exc:
        session["owner_locked_render_refresh"] = False
        session["owner_locked_render_error"] = str(exc)
        return False


def _refresh_render_host_stable(session, expected_width=None, expected_height=None, timeout=0.45):
    """Refresh the live RWH until HWND/geometry settles for native recovery.

    Chromium can replace or resize the RenderWidgetHost shortly after navigation.
    A single sample can therefore preserve launch-time 800x479 geometry even while
    the current live child has already reached the Tekzite viewport.  Recovery
    must act on the current child, not that stale sample.
    """
    if os.name != "nt" or not session:
        return False
    deadline = time.monotonic() + max(0.05, float(timeout))
    last = None
    stable_count = 0
    ew = int(expected_width or 0)
    eh = int(expected_height or 0)
    while time.monotonic() < deadline:
        _refresh_render_host_within_owner(session, expected_width, expected_height)
        current = (
            _hwnd_int(session.get("render_hwnd") or 0),
            tuple(session.get("owner_locked_render_size") or ()),
        )
        if current == last and current[0]:
            stable_count += 1
        else:
            stable_count = 0
            last = current
        size = current[1]
        matches = bool(len(size) == 2 and ew > 0 and eh > 0 and abs(int(size[0])-ew) <= 2 and abs(int(size[1])-eh) <= 2)
        if current[0] and (matches or stable_count >= 2):
            session["native_recovery_render_stable"] = True
            session["native_recovery_render_hwnd"] = current[0]
            session["native_recovery_render_size"] = size
            return True
        time.sleep(0.045)
    session["native_recovery_render_stable"] = False
    session["native_recovery_render_hwnd"] = _hwnd_int(session.get("render_hwnd") or 0)
    session["native_recovery_render_size"] = tuple(session.get("owner_locked_render_size") or ())
    return bool(session.get("render_hwnd"))


def _normalize_locked_owner_crop(left, top, right, bottom, owner_size=None, render_size=None):
    """Normalize transient Chromium crop orientation from locked-owner geometry.

    Some Chromium/Win32 combinations briefly report the entire non-content
    vertical inset as a *bottom* crop even though the page RenderWidgetHost is
    actually below browser chrome.  When that happens together with a small
    total horizontal frame inset, reconstruct the ordinary window frame:
    symmetric side/bottom border + toolbar above the page.

    Example seen in the wild: owner 1294x804, render 1280x676 and raw crop
    (0, 0, 14, 128) is the same geometry as (7, 121, 7, 7).
    """
    left, top, right, bottom = map(int, (left, top, right, bottom))
    raw = (left, top, right, bottom)
    h_total = max(0, left + right)
    v_total = max(0, top + bottom)

    # The transient signature is very specific: page appears flush to the top,
    # while a toolbar-sized inset is incorrectly attributed to the bottom.
    if top <= 8 and 48 <= bottom <= 260 and h_total <= 40:
        # Chromium's native frame is normally symmetric left/right.  Derive the
        # border from the total horizontal delta and use the same border below.
        border = int(round(h_total / 2.0)) if h_total else 0
        border = max(0, min(border, 24))
        left = border
        right = max(0, h_total - border)
        top = max(0, v_total - border)
        bottom = border

    return (left, top, right, bottom), raw

def _live_render_host_crop(session):
    """Measure webpage insets relative to the *whole locked Chromium owner*.

    v4.81 deliberately uses window-space deltas here, not ScreenToClient().
    Chromium's toolbar/tab strip lives inside the owner's client area, so
    ScreenToClient can normalize the live page host to y=0 and turn the real
    top toolbar inset into a bogus bottom crop.  Once the compositor owner is
    locked/reparented, both HWND rectangles share the same screen coordinate
    space, making the direct rectangle delta stable and unambiguous.
    """
    if os.name != "nt" or not session:
        return None
    owner = _hwnd_int(session.get("embedded_hwnd") or session.get("content_hwnd") or 0)
    render = _hwnd_int(session.get("render_hwnd") or 0)
    if not owner or not render:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(owner)) or not user32.IsWindow(_as_hwnd(render)):
            return None

        orect = wintypes.RECT()
        rrect = wintypes.RECT()
        if not user32.GetWindowRect(_as_hwnd(owner), ctypes.byref(orect)):
            return None
        if not user32.GetWindowRect(_as_hwnd(render), ctypes.byref(rrect)):
            return None

        ow = max(0, int(orect.right) - int(orect.left))
        oh = max(0, int(orect.bottom) - int(orect.top))
        left = max(0, int(rrect.left) - int(orect.left))
        top = max(0, int(rrect.top) - int(orect.top))
        rw = max(0, int(rrect.right) - int(rrect.left))
        rh = max(0, int(rrect.bottom) - int(rrect.top))
        if rw < 200 or rh < 150:
            return None
        right = max(0, ow - left - rw) if ow else 0
        bottom = max(0, oh - top - rh) if oh else 0

        # A normal Chromium toolbar is roughly 80-220 px at common DPI scales.
        # Insets far beyond these bounds indicate a stale/unrelated render host.
        if left > 240 or top > 360 or right > 240 or bottom > 240:
            return None

        crop, raw_crop = _normalize_locked_owner_crop(
            left, top, right, bottom, owner_size=(ow, oh), render_size=(rw, rh)
        )
        session["live_render_crop_raw"] = raw_crop
        session["live_render_crop_normalized"] = tuple(crop) != tuple(raw_crop)
        session["live_render_crop"] = crop
        session["live_render_owner_size"] = (ow, oh)
        session["live_render_host_size"] = (rw, rh)
        session["live_render_crop_space"] = "locked-owner-window"
        session["render_host_geometry_owned_by"] = "chromium"
        session["live_render_crop_error"] = None
        return crop
    except Exception as exc:
        session["live_render_crop_error"] = str(exc)
        return None

def _embedded_chrome_crop(session):
    """Return crop needed to expose the render host inside its owner widget.

    v4.46 keeps Chromium's compositor hierarchy intact by embedding the widget
    that owns the render host.  When a render-host locator is available, derive
    the crop from its rectangle instead of assuming Edge's browser chrome.
    """
    live_crop = _live_render_host_crop(session)
    if live_crop is not None:
        return live_crop

    render_rect = session.get("render_rect")
    expected = session.get("content_expected_size") or (800, 600)
    if render_rect and session.get("content_selection") == "render-host owner-widget":
        try:
            rx1, ry1, rx2, ry2 = map(int, render_rect)
            rw = max(1, rx2 - rx1)
            rh = max(1, ry2 - ry1)
            ew, eh = map(int, expected)

            owner_row = None
            content = _hwnd_int(session.get("content_hwnd") or 0)
            for row in session.get("window_tree") or []:
                if _hwnd_int(row.get("hwnd") or 0) == content:
                    owner_row = row
                    break
            if owner_row and owner_row.get("rect"):
                ox1, oy1, ox2, oy2 = map(int, owner_row["rect"])
                ow, oh = max(0, ox2 - ox1), max(0, oy2 - oy1)
            else:
                ox1 = oy1 = 0
                ow = oh = 0

            # Zero-sized hidden owner widgets report child coordinates as if
            # rooted at (0,0). Use the helper's launch viewport as the owner's
            # logical size until SetWindowPos gives it real geometry.
            if ow < 1 or oh < 1:
                ox1 = oy1 = 0
                ow, oh = ew, eh

            left = max(0, rx1 - ox1)
            top = max(0, ry1 - oy1)
            right = max(0, ow - left - rw)
            bottom = max(0, oh - top - rh)
            # Guard against bizarre stale coordinates. Chromium's app chrome
            # is small relative to the viewport; fall back conservatively.
            if left <= 120 and top <= 180 and right <= 120 and bottom <= 120:
                return left, top, right, bottom
        except Exception:
            pass

    left = 8
    top = 80
    right = 8
    bottom = 8
    try:
        main = int(session.get("main_hwnd") or session.get("outer_hwnd") or 0)
        tree = session.get("window_tree") or []
        main_row = next((r for r in tree if int(r.get("hwnd") or 0) == main), None)
        if main_row and main_row.get("rect"):
            _, my1, _, _ = main_row["rect"]
            candidates = []
            for row in tree:
                if str(row.get("class") or "") != "Chrome_WidgetWin_2":
                    continue
                rect = row.get("rect")
                if not rect:
                    continue
                _, y1, _, _ = rect
                dy = int(y1) - int(my1)
                if 48 <= dy <= 140:
                    candidates.append(dy)
            if candidates:
                top = min(candidates) + 4
    except Exception:
        pass
    return left, top, right, bottom

def _show_embedded_render_host(session, width: int, height: int):
    """Observe Chromium's RenderWidgetHost without mutating it.

    v5.25: the RenderWidgetHost belongs entirely to Chromium. Older recovery
    code called ShowWindow/RedrawWindow/UpdateWindow on the RWH. Even without
    SetParent, touching the child directly can desynchronise Chromium's
    DirectComposition visual tree from its HWND hierarchy and leave the native
    presenter black. Tekzite now treats the RWH as read-only and positions only
    its top-level Chromium owner.
    """
    if os.name != "nt" or not session:
        return False
    render = _hwnd_int(session.get("render_hwnd") or 0)
    owner = _hwnd_int(session.get("embedded_hwnd") or session.get("content_hwnd") or 0)
    if not render or not owner:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(render)) or not user32.IsWindow(_as_hwnd(owner)):
            return False
        rect = wintypes.RECT()
        if user32.GetWindowRect(_as_hwnd(render), ctypes.byref(rect)):
            session["render_host_embedded_size"] = (
                max(1, int(rect.right) - int(rect.left)),
                max(1, int(rect.bottom) - int(rect.top)),
            )
        else:
            session["render_host_embedded_size"] = None
        session["render_host_forced_visible"] = False
        session["render_host_geometry_owned_by"] = "chromium"
        session["render_host_hands_off"] = True
        session["render_host_mutation_calls"] = 0
        return True
    except Exception as exc:
        session["render_host_visibility_error"] = str(exc)
        return False

def _prime_chromium_compositor_surface(session, width: int, height: int):
    """v5.25: do not prime Chromium by touching its native child surface.

    DirectComposition presentation is established by Chromium itself. The old
    prime path resized and showed Chrome_RenderWidgetHostHWND directly before
    overlay placement. That contradicted the later hands-off geometry policy and
    could detach the HWND state from Chromium's compositor visual tree. Direct
    app launch already gives Chromium a real top-level surface, so the correct
    prime is no prime at all.
    """
    if os.name != "nt" or not session:
        return False
    session["compositor_prime_attempted"] = False
    session["compositor_prime_skipped"] = "hands-off-render-host"
    session["compositor_prime_render_touched"] = False
    session["compositor_prime_owner_touched"] = False
    session["render_host_hands_off"] = True
    session["render_host_mutation_calls"] = 0
    return True


def _park_chromium_top_level_presenters(session, source_hwnd=0, passes=1, settle_delay=0.0):
    """Keep Chromium's own top-level presenter windows off the desktop.

    v5.31: DWM mirrors the real Chromium app window into Tekzite, so Chromium's
    auxiliary ``Chrome_WidgetWin_*`` top-level windows must never become a
    second visible browser surface.  Only top-level Chromium windows from this
    dedicated helper process tree are moved.  Child RenderWidgetHost HWNDs are
    deliberately ignored.
    """
    if os.name != "nt" or not session:
        return []
    try:
        import ctypes
        from ctypes import wintypes

        process = session.get("process")
        if process is None:
            return []
        user32 = _typed_user32()
        pids = _windows_descendant_pids(process.pid)
        if not pids:
            pids = {int(process.pid)}
        source_hwnd = _hwnd_int(source_hwnd or 0)
        parked = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        HWND_BOTTOM = 1
        base_x, base_y = -32000, -32000

        for pass_index in range(max(1, int(passes))):
            seen_this_pass = []

            @WNDENUMPROC
            def enum_proc(hwnd, lparam):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) not in pids or not user32.IsWindow(hwnd):
                    return True
                # EnumWindows gives top-level windows, but retain the parent
                # check so we never accidentally mutate a child presenter.
                if user32.GetParent(hwnd):
                    return True
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, len(cls))
                if not cls.value.startswith("Chrome_WidgetWin"):
                    return True
                hwnd_i = _hwnd_int(hwnd)
                visible = bool(user32.IsWindowVisible(hwnd))
                rect = wintypes.RECT()
                old_rect = None
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    old_rect = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
                # Keep every Chromium presenter outside the visible desktop.
                # The active DWM source remains mapped; hidden utility windows
                # remain hidden and are merely pre-positioned off-screen.
                offset = len(seen_this_pass) * 32
                target_x = base_x - offset
                target_y = base_y - offset
                user32.SetWindowPos(
                    hwnd, _as_hwnd(HWND_BOTTOM), target_x, target_y, 0, 0,
                    SWP_NOSIZE | SWP_NOACTIVATE,
                )
                # v7.8: auxiliary presenter windows are not DWM sources and do
                # not need to stay mapped. Hide them after parking so neither a
                # black helper square nor Chromium chrome can leak behind Tekzite.
                if hwnd_i != source_hwnd:
                    user32.ShowWindow(hwnd, 0)  # SW_HIDE
                row = {
                    "hwnd": hwnd_i, "class": cls.value, "pid": int(pid.value),
                    "visible": visible, "is_dwm_source": hwnd_i == source_hwnd,
                    "old_rect": old_rect, "park_position": (target_x, target_y),
                }
                seen_this_pass.append(row)
                return True

            user32.EnumWindows(enum_proc, 0)
            parked = seen_this_pass
            if settle_delay and pass_index + 1 < max(1, int(passes)):
                time.sleep(float(settle_delay))

        session["dwm_chromium_presenters_parked"] = parked
        session["dwm_chromium_presenter_count"] = len(parked)
        session["dwm_aux_presenters_visible_before_park"] = sum(
            1 for row in parked if row.get("visible") and not row.get("is_dwm_source")
        )
        return parked
    except Exception as exc:
        session["dwm_presenter_park_error"] = f"{type(exc).__name__}: {exc}"
        return []

def _position_native_chromium_overlay(session, width: int, height: int):
    """Present Chromium through a DWM thumbnail owned by Tekzite.

    v5.28 stops trying to make Chromium's compositor HWND itself behave like an
    embeddable child.  The real Chromium app window stays a genuine top-level
    DComp source, while DWM mirrors a cropped live view into a Tekzite-owned
    top-level viewport.  The source RenderWidgetHost is never moved, resized,
    reparented, shown or repainted by Tekzite.
    """
    if os.name != "nt" or not session:
        return False
    requested_destination = _hwnd_int(session.get("embedded_parent") or 0)
    requested_source = _hwnd_int(session.get("main_hwnd") or session.get("outer_hwnd") or 0)
    if not requested_destination or not requested_source:
        session["dwm_thumbnail_error"] = "missing destination or Chromium source HWND"
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(requested_destination)):
            raise RuntimeError("Tekzite DWM destination HWND is invalid")
        if not user32.IsWindow(_as_hwnd(requested_source)):
            raise RuntimeError("Chromium DWM source HWND is invalid")

        # Tk/Tkinter top-levels on Windows have a native wrapper HWND around
        # the inner Tk client HWND returned by winfo_id(). DwmRegisterThumbnail
        # rejects non-top-level handles with E_INVALIDARG, so always resolve
        # both ends through GA_ROOT before registration. This is harmless for
        # Chromium because its Chrome_WidgetWin_1 is already top-level.
        GA_ROOT = 2
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        destination = _hwnd_int(user32.GetAncestor(_as_hwnd(requested_destination), GA_ROOT)) or requested_destination
        source = _hwnd_int(user32.GetAncestor(_as_hwnd(requested_source), GA_ROOT)) or requested_source

        def _window_class(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            try:
                user32.GetClassNameW(_as_hwnd(hwnd), buf, len(buf))
                return buf.value
            except Exception:
                return ""

        def _window_pid(hwnd):
            pid = wintypes.DWORD()
            try:
                user32.GetWindowThreadProcessId(_as_hwnd(hwnd), ctypes.byref(pid))
                return int(pid.value)
            except Exception:
                return None

        WS_CHILD = 0x40000000
        GWL_STYLE = -16
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        dest_style = int(user32.GetWindowLongPtrW(_as_hwnd(destination), GWL_STYLE))
        src_style = int(user32.GetWindowLongPtrW(_as_hwnd(source), GWL_STYLE))
        session["dwm_destination_requested_hwnd"] = requested_destination
        session["dwm_destination_resolved_hwnd"] = destination
        session["dwm_destination_class"] = _window_class(destination)
        session["dwm_destination_pid"] = _window_pid(destination)
        session["dwm_destination_is_top_level"] = not bool(dest_style & WS_CHILD)
        session["dwm_source_requested_hwnd"] = requested_source
        session["dwm_source_resolved_hwnd"] = source
        session["dwm_source_class"] = _window_class(source)
        session["dwm_source_pid"] = _window_pid(source)
        session["dwm_source_is_top_level"] = not bool(src_style & WS_CHILD)
        session["dwm_registering_process_pid"] = os.getpid()

        if not user32.IsWindow(_as_hwnd(destination)) or (dest_style & WS_CHILD):
            raise RuntimeError("Tekzite DWM destination did not resolve to a top-level HWND")
        if not user32.IsWindow(_as_hwnd(source)) or (src_style & WS_CHILD):
            raise RuntimeError("Chromium DWM source did not resolve to a top-level HWND")
        if session["dwm_destination_pid"] != os.getpid():
            raise RuntimeError("Tekzite DWM destination is not owned by the registering process")

        width, height = _native_client_size(destination, width, height)
        width, height = max(1, int(width)), max(1, int(height))
        session["embedded_parent_client_size"] = (width, height)
        session["dwm_zoom_percent"] = int(session.get("default_page_zoom_percent") or 100)
        session["dwm_zoom_refresh_count"] = int(session.get("dwm_zoom_refresh_count") or 0) + 1

        # v5.40: keep the known-good Chrome_WidgetWin_1 DWM source from v5.38,
        # but account for Chromium's custom-drawn app chrome living *inside*
        # its client area.  First size the source client to the Tekzite
        # viewport, then measure how much shorter the real page RenderWidgetHost
        # is.  That shortfall is the custom chrome strip.  Grow the source
        # client by exactly that amount and crop the strip from the DWM source.
        # This preserves the reliable outer source while producing a true
        # webpage-only 1:1 mirror.
        src_rect = wintypes.RECT()
        client_rect = wintypes.RECT()
        if not user32.GetWindowRect(_as_hwnd(source), ctypes.byref(src_rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not user32.GetClientRect(_as_hwnd(source), ctypes.byref(client_rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        src_w = max(1, int(src_rect.right - src_rect.left))
        src_h = max(1, int(src_rect.bottom - src_rect.top))
        client_w = max(1, int(client_rect.right - client_rect.left))
        client_h = max(1, int(client_rect.bottom - client_rect.top))
        nonclient_w = max(0, src_w - client_w)
        nonclient_h = max(0, src_h - client_h)

        source_crop = (0, 0, 0, 0)
        crop_left = crop_top = crop_right = crop_bottom = 0
        session["dwm_source_client_only"] = True
        session["dwm_source_client_size_before"] = (client_w, client_h)
        session["dwm_source_nonclient_margins"] = (nonclient_w, nonclient_h)
        session["dwm_pre_visual_source_crop"] = (0, 0, 0, 0)
        session["dwm_visual_crop_correction"] = (0, 0)
        session["dwm_input_offset"] = (0, 0)
        # v6.2: preserve the last proven Chromium custom-chrome height across
        # navigation recrops.  Older builds reset this to zero on every pass,
        # briefly shrinking the real Chromium viewport before expanding it
        # again.  Sites with a scrollbar visibly bounced during that two-pass
        # resize cycle.
        previous_chrome_h = max(0, int(session.get("dwm_custom_chrome_height") or 0))
        session["dwm_custom_chrome_height"] = previous_chrome_h
        session["dwm_chrome_height_locked"] = previous_chrome_h
        session["dwm_render_size_before_chrome_expand"] = None
        session["dwm_render_size_after_chrome_expand"] = None

        # v5.43: the DWM source is Chrome_WidgetWin_1, so its crop must be
        # measured from a RenderWidgetHost that is actually a descendant of
        # *that source HWND*.  The normal session render_hwnd belongs to the
        # separate Chrome_WidgetWin_0 presenter on current Chromium builds and
        # can report a perfect viewport-sized surface even while the DWM source
        # itself still has ~31 px of custom app chrome above its page renderer.
        # Measuring the wrong tree made URL-bar navigation reveal Chromium's
        # title strip again.
        session["dwm_navigation_recrop_count"] = int(session.get("dwm_navigation_recrop_count") or 0) + 1
        session["dwm_navigation_recrop_render_hwnd"] = None
        session["dwm_source_render_hwnd"] = None
        session["dwm_source_render_offset"] = None
        session["dwm_source_render_size"] = None

        def _measure_source_render_host():
            rows = []
            try:
                WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                client_origin = wintypes.POINT(0, 0)
                if not user32.ClientToScreen(_as_hwnd(source), ctypes.byref(client_origin)):
                    client_origin.x = int(src_rect.left)
                    client_origin.y = int(src_rect.top)

                @WNDENUMPROC
                def _enum_source_child(hwnd, lparam):
                    cls = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cls, len(cls))
                    name = cls.value
                    if name == "Chrome_RenderWidgetHostHWND" or "RenderWidgetHost" in name:
                        rr = wintypes.RECT()
                        if user32.GetWindowRect(hwnd, ctypes.byref(rr)):
                            rw = max(0, int(rr.right - rr.left))
                            rh = max(0, int(rr.bottom - rr.top))
                            if rw >= 200 and rh >= 150:
                                ox = int(rr.left) - int(client_origin.x)
                                oy = int(rr.top) - int(client_origin.y)
                                # Prefer the page-sized child nearest the viewport
                                # dimensions, then the largest surface.
                                delta = abs(rw - int(width)) + abs(rh - int(height))
                                score = max(0, 500000 - delta * 400) + rw * rh
                                rows.append((score, rw * rh, -delta, _hwnd_int(hwnd), rw, rh, ox, oy))
                    return True

                user32.EnumChildWindows(_as_hwnd(source), _enum_source_child, 0)
            except Exception:
                return None
            if not rows:
                return None
            rows.sort(reverse=True, key=lambda row: row[:3])
            return rows[0]

        source_render_measurement = _measure_source_render_host()
        if source_render_measurement:
            _, _, _, source_render, source_rw, source_rh, source_ox, source_oy = source_render_measurement
            session["dwm_navigation_recrop_render_hwnd"] = source_render
            session["dwm_source_render_hwnd"] = source_render
            session["dwm_source_render_offset"] = (source_ox, source_oy)
            session["dwm_source_render_size"] = (source_rw, source_rh)

        # v6.2: size directly to the last stable page+chrome contract.  Do not
        # collapse to the bare viewport first.  This keeps Chromium's actual
        # page viewport constant while a new site/SPA settles.
        target_src_w = max(1, int(width) + nonclient_w)
        target_src_h = max(1, int(height) + int(previous_chrome_h) + nonclient_h)
        SW_SHOWNA = 8
        HWND_BOTTOM = 1
        SWP_NOACTIVATE = 0x0010
        park_x, park_y = -32000, -32000
        resize_needed = (abs(int(src_w) - int(target_src_w)) > 1 or
                         abs(int(src_h) - int(target_src_h)) > 1 or
                         int(src_rect.left) != int(park_x) or
                         int(src_rect.top) != int(park_y))
        session["dwm_source_resize_skipped_stable"] = not resize_needed
        # v7.8: never show Chromium at its previous/on-screen coordinates. Move
        # the source off-screen first, then map it for DWM with no activation.
        # DWM still receives a live top-level source, but the physical Chromium
        # window can never flash behind Tekzite.
        if resize_needed:
            user32.SetWindowPos(
                _as_hwnd(source), _as_hwnd(HWND_BOTTOM), park_x, park_y,
                target_src_w, target_src_h, SWP_NOACTIVATE,
            )
        else:
            user32.SetWindowPos(
                _as_hwnd(source), _as_hwnd(HWND_BOTTOM), park_x, park_y,
                0, 0, 0x0001 | SWP_NOACTIVATE,  # SWP_NOSIZE
            )
        session["dwm_source_prepositioned_before_show"] = True
        user32.ShowWindow(_as_hwnd(source), SW_SHOWNA)
        if resize_needed:
            try:
                ctypes.windll.dwmapi.DwmFlush()
            except Exception:
                pass
            time.sleep(0.012)

        resized_rect = wintypes.RECT()
        resized_client = wintypes.RECT()
        if user32.GetWindowRect(_as_hwnd(source), ctypes.byref(resized_rect)):
            src_w = max(1, int(resized_rect.right - resized_rect.left))
            src_h = max(1, int(resized_rect.bottom - resized_rect.top))
        if user32.GetClientRect(_as_hwnd(source), ctypes.byref(resized_client)):
            client_w = max(1, int(resized_client.right - resized_client.left))
            client_h = max(1, int(resized_client.bottom - resized_client.top))

        # Measure Chromium's custom top chrome from the page renderer that is
        # actually inside the DWM source.  Its Y offset is authoritative.  Fall
        # back to the old height-shortfall calculation only if Chromium exposes
        # no usable source-local RenderWidgetHost.
        source_render_measurement = _measure_source_render_host()
        render = render_w = render_h = 0
        source_render_y = None
        if source_render_measurement:
            _, _, _, render, render_w, render_h, source_render_x, source_render_y = source_render_measurement
            session["dwm_navigation_recrop_render_hwnd"] = render
            session["dwm_source_render_hwnd"] = render
            session["dwm_source_render_offset"] = (source_render_x, source_render_y)
            session["dwm_source_render_size"] = (render_w, render_h)
        session["dwm_render_size_before_chrome_expand"] = (render_w, render_h) if render_w and render_h else None

        candidate_chrome_h = previous_chrome_h
        if source_render_y is not None and 0 < int(source_render_y) <= 160:
            candidate_chrome_h = int(source_render_y)
            session["dwm_chrome_measurement"] = "source-render-offset"
        elif render_h:
            # When the source is already expanded by the locked chrome height,
            # the renderer should match the viewport.  Only infer from a
            # shortfall when we have no established lock yet.
            shortfall = int(height) - int(render_h)
            if previous_chrome_h == 0 and 0 < shortfall <= 160:
                candidate_chrome_h = shortfall
                session["dwm_chrome_measurement"] = "source-render-shortfall"
        else:
            session["dwm_chrome_measurement"] = "none"

        session["dwm_chrome_candidate"] = int(candidate_chrome_h)
        existing_thumb = bool(session.get("dwm_thumbnail_handle"))
        candidate_changed = int(candidate_chrome_h) != int(previous_chrome_h)
        if candidate_changed and existing_thumb:
            last_candidate = int(session.get("dwm_chrome_pending_candidate") or -1)
            count = int(session.get("dwm_chrome_pending_count") or 0)
            if last_candidate == int(candidate_chrome_h):
                count += 1
            else:
                last_candidate = int(candidate_chrome_h)
                count = 1
            session["dwm_chrome_pending_candidate"] = last_candidate
            session["dwm_chrome_pending_count"] = count
            # Require the same changed measurement three consecutive times
            # before changing the physical Chromium viewport.  Transient 0/31
            # oscillations during navigation therefore stay invisible.
            if count >= 3:
                chrome_h = int(candidate_chrome_h)
                session["dwm_chrome_pending_count"] = 0
                session["dwm_chrome_height_committed"] = True
            else:
                chrome_h = int(previous_chrome_h)
                session["dwm_chrome_height_committed"] = False
        else:
            chrome_h = int(candidate_chrome_h)
            session["dwm_chrome_pending_candidate"] = int(candidate_chrome_h)
            session["dwm_chrome_pending_count"] = 0
            session["dwm_chrome_height_committed"] = not candidate_changed or not existing_thumb
        session["dwm_custom_chrome_height"] = int(chrome_h)

        # Only resize if a newly committed chrome height actually changes the
        # required source size.  The old two-pass resize is intentionally gone.
        final_target_src_h = max(1, int(height) + int(chrome_h) + nonclient_h)
        if abs(int(src_h) - int(final_target_src_h)) > 1:
            user32.SetWindowPos(
                _as_hwnd(source), _as_hwnd(HWND_BOTTOM), park_x, park_y,
                target_src_w, final_target_src_h, SWP_NOACTIVATE,
            )
            try:
                ctypes.windll.dwmapi.DwmFlush()
            except Exception:
                pass
            time.sleep(0.012)
            if user32.GetWindowRect(_as_hwnd(source), ctypes.byref(resized_rect)):
                src_w = max(1, int(resized_rect.right - resized_rect.left))
                src_h = max(1, int(resized_rect.bottom - resized_rect.top))
            if user32.GetClientRect(_as_hwnd(source), ctypes.byref(resized_client)):
                client_w = max(1, int(resized_client.right - resized_client.left))
                client_h = max(1, int(resized_client.bottom - resized_client.top))
            source_render_after = _measure_source_render_host()
            if source_render_after:
                _, _, _, render_after, rw_after, rh_after, ox_after, oy_after = source_render_after
                session["dwm_source_render_hwnd"] = render_after
                session["dwm_source_render_offset_after_expand"] = (ox_after, oy_after)
                session["dwm_render_size_after_chrome_expand"] = (rw_after, rh_after)
        target_src_h = final_target_src_h

        source_crop = (0, int(chrome_h), 0, 0)
        crop_top = int(chrome_h)
        session["dwm_source_crop"] = source_crop
        session["dwm_source_hwnd"] = source
        session["dwm_destination_hwnd"] = destination
        session["dwm_source_window_size"] = (src_w, src_h)
        session["dwm_source_client_size"] = (client_w, client_h)
        session["dwm_source_target_size"] = (target_src_w, target_src_h)
        session["dwm_source_resized_for_viewport"] = True
        session["dwm_thumbnail_pixel_contract"] = (int(width), int(height))
        session["dwm_source_mapped"] = bool(user32.IsWindowVisible(_as_hwnd(source)))
        session["dwm_source_parked"] = True
        session["dwm_source_park_position"] = (park_x, park_y)
        # Park every Chromium top-level presenter, not just the app source.
        # This prevents auxiliary Chrome_WidgetWin_0 surfaces from appearing as
        # giant black squares next to Tekzite while DWM is mirroring the page.
        _park_chromium_top_level_presenters(session, source, passes=1)

        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        HTHUMBNAIL = wintypes.HANDLE

        class DWM_THUMBNAIL_PROPERTIES(ctypes.Structure):
            _fields_ = [
                ("dwFlags", wintypes.DWORD),
                ("rcDestination", wintypes.RECT),
                ("rcSource", wintypes.RECT),
                ("opacity", ctypes.c_ubyte),
                ("fVisible", wintypes.BOOL),
                ("fSourceClientAreaOnly", wintypes.BOOL),
            ]

        dwmapi.DwmRegisterThumbnail.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.POINTER(HTHUMBNAIL)]
        dwmapi.DwmRegisterThumbnail.restype = wintypes.HRESULT
        dwmapi.DwmUpdateThumbnailProperties.argtypes = [HTHUMBNAIL, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
        dwmapi.DwmUpdateThumbnailProperties.restype = wintypes.HRESULT
        dwmapi.DwmUnregisterThumbnail.argtypes = [HTHUMBNAIL]
        dwmapi.DwmUnregisterThumbnail.restype = wintypes.HRESULT
        dwmapi.DwmFlush.argtypes = []
        dwmapi.DwmFlush.restype = wintypes.HRESULT

        old_thumb = session.get("dwm_thumbnail_handle")
        old_source = _hwnd_int(session.get("dwm_thumbnail_source") or 0)
        old_destination = _hwnd_int(session.get("dwm_thumbnail_destination") or 0)
        thumb = None
        if old_thumb and old_source == source and old_destination == destination:
            thumb = HTHUMBNAIL(_hwnd_int(old_thumb))
        else:
            if old_thumb:
                try:
                    dwmapi.DwmUnregisterThumbnail(HTHUMBNAIL(_hwnd_int(old_thumb)))
                except Exception:
                    pass
            new_thumb = HTHUMBNAIL()
            hr = int(dwmapi.DwmRegisterThumbnail(_as_hwnd(destination), _as_hwnd(source), ctypes.byref(new_thumb)))
            if hr != 0:
                raise RuntimeError(f"DwmRegisterThumbnail failed HRESULT=0x{hr & 0xffffffff:08X}")
            thumb = new_thumb
            session["dwm_thumbnail_handle"] = _hwnd_int(new_thumb)
            session["dwm_thumbnail_source"] = source
            session["dwm_thumbnail_destination"] = destination
            session["dwm_thumbnail_registered"] = True

        DWM_TNP_RECTDESTINATION = 0x00000001
        DWM_TNP_RECTSOURCE = 0x00000002
        DWM_TNP_OPACITY = 0x00000004
        DWM_TNP_VISIBLE = 0x00000008
        DWM_TNP_SOURCECLIENTAREAONLY = 0x00000010
        props = DWM_THUMBNAIL_PROPERTIES()
        props.dwFlags = (
            DWM_TNP_RECTDESTINATION | DWM_TNP_RECTSOURCE | DWM_TNP_OPACITY |
            DWM_TNP_VISIBLE | DWM_TNP_SOURCECLIENTAREAONLY
        )
        props.rcDestination = wintypes.RECT(0, 0, width, height)
        props.rcSource = wintypes.RECT(0, int(chrome_h), int(width), int(chrome_h) + int(height))
        props.opacity = 255
        props.fVisible = True
        props.fSourceClientAreaOnly = True
        hr = int(dwmapi.DwmUpdateThumbnailProperties(thumb, ctypes.byref(props)))
        if hr != 0:
            raise RuntimeError(f"DwmUpdateThumbnailProperties failed HRESULT=0x{hr & 0xffffffff:08X}")
        dwmapi.DwmFlush()
        # Chromium can materialize an auxiliary top-level presenter shortly
        # after its first committed frame. Re-scan a few times so a late
        # Chrome_WidgetWin_0 never leaks onto the desktop.
        _park_chromium_top_level_presenters(session, source, passes=3, settle_delay=0.04)

        session["native_embed_mode"] = "dwm-thumbnail"
        session["native_setparent_used"] = False
        session["dwm_thumbnail_destination_rect"] = (0, 0, width, height)
        session["dwm_thumbnail_source_rect"] = (0, int(chrome_h), int(width), int(chrome_h) + int(height))
        session["dwm_thumbnail_scale_x"] = 1.0
        session["dwm_thumbnail_scale_y"] = 1.0
        session["dwm_thumbnail_visible"] = True
        session["dwm_thumbnail_error"] = None
        # Legacy overlay diagnostics are explicitly neutral in this mode.
        session["native_overlay_error"] = None
        session["native_overlay_owner_assigned"] = False
        session["native_overlay_style_mutated"] = False
        session["native_overlay_render_forced"] = False
        session["native_overlay_region_used"] = False
        return True
    except Exception as exc:
        session["dwm_thumbnail_registered"] = False
        session["dwm_thumbnail_visible"] = False
        session["dwm_thumbnail_error"] = f"{type(exc).__name__}: {exc}"
        session["native_overlay_error"] = session["dwm_thumbnail_error"]
        return False

def attach_embedded_chromium(parent_hwnd: int, width: int, height: int):
    """Re-parent Chromium's web-content HWND into a native Tk host frame.

    Tekzite keeps all browser chrome. Chromium's outer browser shell remains
    off-screen; only the descendant window that owns page pixels is attached
    to the Tk content area.
    """
    if os.name != "nt":
        raise RuntimeError("Native Chromium embedding is currently Windows-only")
    import ctypes

    user32 = _typed_user32()
    session = _start_persistent_chromium_session()
    session["presentation_mode"] = "native"
    width, height = _native_client_size(parent_hwnd, width, height)
    session["embedded_parent_client_size"] = (int(width), int(height))

    # Keep the browser shell off-screen and host the real content child.  On
    # current Chromium builds the top-level Chrome_WidgetWin_1 can paint only
    # its blank client background after SetParent, while the actual webpage is
    # owned by a descendant such as Chrome_RenderWidgetHostHWND.
    outer_hwnd = session.get("outer_hwnd")
    if not outer_hwnd or not user32.IsWindow(_as_hwnd(outer_hwnd)):
        outer_hwnd = _find_chromium_window(session)
        session["outer_hwnd"] = _hwnd_int(outer_hwnd)

    _apply_tekzite_chromium_branding(session)

    hwnd = session.get("embedded_hwnd")
    if not hwnd or not user32.IsWindow(_as_hwnd(hwnd)):
        hwnd = _select_chromium_content_window(session, timeout=4.0)

    # v4.96: first-frame readiness and HWND ownership are separate races.
    # Validate that the candidate still owns a page-sized RenderWidgetHost
    # immediately before compositor priming/reparenting. Never embed a stale
    # Chrome_WidgetWin just because IsWindow() still returns true.
    hwnd = _validate_embed_owner_before_reparent(session, hwnd, width, height)
    if not hwnd:
        raise RuntimeError("Chromium page owner lost its live render host before embedding")

    # v4.48: prime Chromium/DWM while the owner is still a genuine top-level
    # window.  Doing this after WS_CHILD/SetParent is too late on some builds.
    _prime_chromium_compositor_surface(session, width, height)

    # Priming itself can trigger a late Chromium widget/RWH migration. Recheck
    # once more at the last safe point before SetParent(). If ownership moved,
    # prime the newly selected owner instead of carrying a dead compositor into
    # Tekzite.
    verified_hwnd = _validate_embed_owner_before_reparent(session, hwnd, width, height)
    if not verified_hwnd:
        raise RuntimeError("Chromium page owner became stale during compositor prime")
    if _hwnd_int(verified_hwnd) != _hwnd_int(hwnd):
        hwnd = verified_hwnd
        _prime_chromium_compositor_surface(session, width, height)

    # Chromium may alter toolbar/layout geometry once the target becomes live.
    # Refresh the native tree and derive the crop from the current render host
    # immediately before reparenting, rather than trusting launch-time insets.
    try:
        session["window_tree"] = _chromium_window_tree(session)
    except Exception:
        pass
    session["content_hwnd"] = _hwnd_int(hwnd)
    try:
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(_as_hwnd(hwnd), cls_buf, len(cls_buf))
        if cls_buf.value:
            session["content_class"] = cls_buf.value
    except Exception:
        pass
    live_crop = _live_render_host_crop(session)
    if live_crop is not None:
        session["chrome_crop"] = live_crop

    # v5.13: preserve Chromium DirectComposition by keeping the compositor
    # owner top-level. SetParent()/WS_CHILD is retained below only as a legacy
    # fallback if overlay setup fails unexpectedly.
    session["embedded_hwnd"] = _hwnd_int(hwnd)
    session["embedded_parent"] = _hwnd_int(parent_hwnd)
    if _position_native_chromium_overlay(session, width, height):
        session["native_setparent_used"] = False
        return _hwnd_int(hwnd)
    session["native_setparent_used"] = False
    raise RuntimeError(session.get("dwm_thumbnail_error") or "DWM thumbnail presentation failed")

    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    SW_RESTORE = 9
    SW_SHOW = 5
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040

    # GWL_STYLE is a 32-bit LONG even on Win64.  Use the W APIs with an
    # explicit signed 32-bit conversion instead of an untyped Python int.
    style = int(user32.GetWindowLongW(_as_hwnd(hwnd), GWL_STYLE)) & 0xFFFFFFFF
    style |= WS_CHILD
    style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU |
               WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
    signed_style = ctypes.c_int32(style & 0xFFFFFFFF).value
    user32.SetWindowLongW(_as_hwnd(hwnd), GWL_STYLE, signed_style)
    if not user32.SetParent(_as_hwnd(hwnd), _as_hwnd(parent_hwnd)):
        # SetParent returns the previous parent, which is NULL for a normal
        # top-level window, so a NULL return is not itself an error.
        pass
    user32.ShowWindow(_as_hwnd(hwnd), SW_SHOW)

    # v4.24: fully merge the compatibility surface into Tekzite.  Keep the
    # proven, interactive top-level Chromium window, but position its native
    # browser chrome above/around the clipping host.  Child windows are clipped
    # to their parent on Win32, so the user sees only the live webpage viewport
    # directly below Tekzite's own toolbar.
    crop_left, crop_top, crop_right, crop_bottom = session.get("chrome_crop") or _embedded_chrome_crop(session)
    session["chrome_crop"] = (crop_left, crop_top, crop_right, crop_bottom)
    user32.SetWindowPos(
        _as_hwnd(hwnd), _as_hwnd(0),
        -int(crop_left), -int(crop_top),
        max(1, int(width) + int(crop_left) + int(crop_right)),
        max(1, int(height) + int(crop_top) + int(crop_bottom)),
        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    )

    # v4.73: keep the known-good compositor owner fixed. Chromium may replace
    # only its RenderWidgetHost child after navigation, so refresh that child
    # inside the already embedded owner before measuring the final content crop.
    _refresh_render_host_within_owner(session, width, height)

    # v4.69: Chromium can decide to expose normal browser chrome only *after*
    # its owner is mapped/re-parented.  The launch-time crop can therefore be
    # zero even though the live RenderWidgetHost later starts 150-200 px below
    # the owner.  Measure again after the provisional placement and immediately
    # correct the owner position/size so only page pixels remain in Tekzite.
    post_crop = _live_render_host_crop(session)
    if post_crop is not None and tuple(post_crop) != (crop_left, crop_top, crop_right, crop_bottom):
        crop_left, crop_top, crop_right, crop_bottom = map(int, post_crop)
        session["chrome_crop"] = (crop_left, crop_top, crop_right, crop_bottom)
        session["post_attach_crop_corrected"] = True
        user32.SetWindowPos(
            _as_hwnd(hwnd), _as_hwnd(0),
            -crop_left, -crop_top,
            max(1, int(width) + crop_left + crop_right),
            max(1, int(height) + crop_top + crop_bottom),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
    else:
        session["post_attach_crop_corrected"] = False

    # Re-parenting a Chromium/DComp window can leave the child showing the
    # compositor's initial black backing surface until Windows requests a
    # real repaint. Force that repaint now that the window is visible inside
    # Tekzite.
    RDW_INVALIDATE = 0x0001
    RDW_FRAME = 0x0400
    RDW_UPDATENOW = 0x0100
    RDW_ALLCHILDREN = 0x0080
    user32.RedrawWindow(
        _as_hwnd(hwnd), None, None,
        RDW_INVALIDATE | RDW_FRAME | RDW_UPDATENOW | RDW_ALLCHILDREN,
    )
    user32.UpdateWindow(_as_hwnd(hwnd))
    session["embedded_hwnd"] = _hwnd_int(hwnd)
    session["embedded_parent"] = _hwnd_int(parent_hwnd)
    session["embedded_size"] = (max(1, int(width)), max(1, int(height)))
    _show_embedded_render_host(session, width, height)
    return _hwnd_int(hwnd)


def _initial_chromium_launch_geometry(parent_hwnd: int, width: int, height: int):
    """Return the initial Chromium source rectangle, always outside the desktop.

    v7.8 never lets Chromium's own app window become a user-visible background
    window. The real top-level source is born off-screen at approximately the
    final viewport size and remains there for DWM composition. This preserves
    the stable near-final DirectComposition geometry without an on-screen flash.
    """
    if os.name != "nt" or not parent_hwnd:
        return None
    try:
        w, h = _native_client_size(parent_hwnd, width, height)
        left, top, right, bottom = (8, 80, 8, 8)
        return (-32000, -32000,
                max(320, int(w)+left+right), max(240, int(h)+top+bottom))
    except Exception:
        return None

def open_embedded_chromium(parent_hwnd: int, width: int, height: int, url: str, target_id: str = None, create_new_target: bool = False, attach_native: bool = True, preferred_zoom_percent: int = 100):
    """Load off-screen, wait for a real frame, then embed the painted window.

    v4.40 optionally binds the navigation to a dedicated Chromium target so
    each Tekzite tab can retain a live JS/media page without reloading it.

    Earlier builds attached Chromium before navigation.  That can race the
    compositor and leave Tekzite showing only its gray host until a manual
    title-bar activation.  The helper already starts 32,000 pixels off-screen,
    so it is safe to navigate there first, verify a paintable frame via CDP,
    and only then re-parent it into Tekzite.
    """
    launch_geometry = _initial_chromium_launch_geometry(parent_hwnd, width, height) if attach_native else None
    first_native_bootstrap = bool(attach_native and not target_id and not create_new_target and _EDGE_SESSION is None)
    direct_launch_url = str(url or "about:blank") if first_native_bootstrap else None
    session = _start_persistent_chromium_session(
        launch_geometry=launch_geometry, launch_url=direct_launch_url
    )
    # v6.3: Preferences owns page zoom browser-wide. Seed the persistent
    # Chromium session *before* a target is created/claimed so every new tab
    # inherits the saved zoom rather than briefly/defaulting to 100%.
    try:
        preferred_zoom_percent = max(50, min(300, int(preferred_zoom_percent)))
    except Exception:
        preferred_zoom_percent = 100
    session["default_page_zoom_percent"] = preferred_zoom_percent
    session["dwm_zoom_percent"] = preferred_zoom_percent
    session["preferences_zoom_percent"] = preferred_zoom_percent
    session["preferences_zoom_seeded_before_target"] = True
    session["native_direct_app_launch"] = bool(first_native_bootstrap and direct_launch_url)
    if launch_geometry and not session.get("native_launch_in_place"):
        session["native_launch_in_place"] = True
        session["native_launch_geometry"] = tuple(launch_geometry)

    # v5.19: the first native tab must *actually* claim Chromium's bootstrap
    # --app=about:blank target before any navigation.  Earlier builds had the
    # claiming helper but the first-tab path skipped it, so _pick_devtools_page
    # silently selected whichever page/presenter Chromium exposed and could
    # recreate the extra Chrome_WidgetWin_0 topology we were trying to avoid.
    if attach_native and not target_id and not create_new_target:
        target_id = create_embedded_chromium_target(
            str(url or "about:blank"), require_bootstrap=True
        )

    # v6.5: never mutate document zoom before navigation.  Keep only the saved
    # preference in session state and let the destination document initialize
    # normally.  Zoom is applied after navigation once readyState is no longer
    # ``loading``.
    session["preferences_zoom_pre_navigation_applied"] = False

    session = navigate_embedded_chromium(
        url, wait_for_first_frame=True, target_id=target_id,
        create_new_target=create_new_target,
    )
    # Try once after navigation. If the document is still ``loading`` the zoom
    # helper intentionally defers; the UI-side retry window will apply the saved
    # preference once the document reaches interactive/complete.
    try:
        set_embedded_chromium_zoom(
            preferred_zoom_percent, target_id=session.get("target_id"), timeout=3
        )
        session["preferences_zoom_post_navigation_applied"] = True
    except Exception:
        session["preferences_zoom_post_navigation_applied"] = False
    if attach_native:
        session["presentation_mode"] = "native"
        # A tab that previously used the CDP software surface may still have a
        # device-metrics override installed. Clear it before native embedding so
        # Chromium's HWND owns viewport sizing exclusively.
        try:
            _clear_embedded_chromium_device_metrics(session, target_id=session.get("target_id"))
        except Exception:
            pass
        attach_embedded_chromium(parent_hwnd, width, height)
        session["embedded_after_first_frame"] = True
        attached_ready = _wait_for_attached_first_frame(session, timeout=6.0)
        if attached_ready:
            session["first_frame_ready"] = True
            session["first_frame_committed"] = True
            session["first_frame_generation"] = int(session.get("navigation_generation") or 0)
    else:
        session["presentation_mode"] = "software"
        session["embedded_after_first_frame"] = False
    return session


def record_embedded_native_recovery(attempted=True, viewport=None, succeeded=None):
    """Record v5.04 native-presentation retry diagnostics."""
    if not _EDGE_SESSION:
        return False
    _EDGE_SESSION["native_resize_recovery_attempted"] = bool(attempted)
    if viewport is not None:
        try:
            _EDGE_SESSION["native_resize_recovery_viewport"] = (int(viewport[0]), int(viewport[1]))
        except Exception:
            _EDGE_SESSION["native_resize_recovery_viewport"] = viewport
    if succeeded is not None:
        _EDGE_SESSION["native_resize_recovery_succeeded"] = bool(succeeded)
    return True



def sync_embedded_chromium_native_geometry(width: int, height: int):
    """Force owner + live RenderWidgetHost to the requested recovery viewport.

    v5.04 uses this only while retrying native presentation after a visible-surface
    software fallback. Normal native resize still leaves RWH geometry to Chromium.
    A stalled compositor can otherwise keep the child at the old pre-fullscreen
    size even though the Tekzite host has already grown.
    """
    session = _EDGE_SESSION
    if os.name != "nt" or not session:
        return False
    owner = _hwnd_int(session.get("embedded_hwnd") or session.get("content_hwnd") or 0)
    if not owner:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(owner)):
            return False
        parent = session.get("embedded_parent")
        width, height = _native_client_size(parent, width, height)
        width, height = max(1, int(width)), max(1, int(height))
        session["native_geometry_sync_attempted"] = True
        session["native_geometry_sync_requested"] = (width, height)

        # v5.14 detached overlay: do not force Chromium's RWH geometry during
        # recovery. Reposition/reclip the untouched top-level owner and only
        # measure the child that Chromium itself owns.
        if session.get("native_embed_mode") in {"detached-top-level-overlay", "detached-unclipped-top-level-overlay"}:
            _position_native_chromium_overlay(session, width, height)
            _refresh_render_host_stable(session, width, height, timeout=0.55)
            render = _hwnd_int(session.get("render_hwnd") or 0)
            actual = None
            if render and user32.IsWindow(_as_hwnd(render)):
                rect = wintypes.RECT()
                if user32.GetWindowRect(_as_hwnd(render), ctypes.byref(rect)):
                    actual = (max(0, int(rect.right)-int(rect.left)),
                              max(0, int(rect.bottom)-int(rect.top)))
            session["native_geometry_sync_render_size"] = actual
            session["render_host_embedded_size"] = actual
            ok = bool(actual and abs(actual[0]-width) <= 2 and abs(actual[1]-height) <= 2)
            session["native_geometry_sync_succeeded"] = ok
            session["native_geometry_sync_error"] = None if ok else f"Chromium-owned render host {actual} != {(width, height)}"
            return ok

        # Refresh only inside the locked owner. Never select a different owner here.
        _refresh_render_host_within_owner(session, width, height)
        render = _hwnd_int(session.get("render_hwnd") or 0)
        if not render or not user32.IsWindow(_as_hwnd(render)):
            session["native_geometry_sync_error"] = "no live render host in locked owner"
            return False

        crop = _live_render_host_crop(session) or _embedded_chrome_crop(session)
        left, top, right, bottom = map(int, crop)
        session["chrome_crop"] = (left, top, right, bottom)

        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040
        flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW

        # First resize the owner to the full desired clipped extent.
        user32.SetWindowPos(
            _as_hwnd(owner), _as_hwnd(0), -left, -top,
            width + left + right, height + top + bottom, flags,
        )
        # Recovery-only override: force the page child to the actual viewport.
        user32.SetWindowPos(
            _as_hwnd(render), _as_hwnd(0), left, top, width, height, flags,
        )
        user32.ShowWindow(_as_hwnd(owner), 5)
        user32.ShowWindow(_as_hwnd(render), 5)
        user32.RedrawWindow(_as_hwnd(owner), None, None, 0x0001 | 0x0400 | 0x0100 | 0x0080)
        user32.UpdateWindow(_as_hwnd(render))
        user32.UpdateWindow(_as_hwnd(owner))
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except Exception:
            pass

        rect = wintypes.RECT()
        actual = None
        if user32.GetWindowRect(_as_hwnd(render), ctypes.byref(rect)):
            actual = (max(0, int(rect.right)-int(rect.left)),
                      max(0, int(rect.bottom)-int(rect.top)))
        session["native_geometry_sync_render_size"] = actual
        session["render_host_embedded_size"] = actual
        ok = bool(actual and abs(actual[0]-width) <= 2 and abs(actual[1]-height) <= 2)
        session["native_geometry_sync_succeeded"] = ok
        if not ok:
            session["native_geometry_sync_error"] = f"render host {actual} != {(width, height)}"
        else:
            session["native_geometry_sync_error"] = None
        return ok
    except Exception as exc:
        session["native_geometry_sync_attempted"] = True
        session["native_geometry_sync_succeeded"] = False
        session["native_geometry_sync_error"] = f"{type(exc).__name__}: {exc}"
        return False

def resize_embedded_chromium(width: int, height: int):
    if os.name != "nt" or not _EDGE_SESSION:
        return False
    if _EDGE_SESSION.get("presentation_mode") == "software":
        return False
    hwnd = _EDGE_SESSION.get("embedded_hwnd")
    if not hwnd:
        return False
    try:
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(hwnd)):
            return False
        parent_hwnd = _EDGE_SESSION.get("embedded_parent")
        width, height = _native_client_size(parent_hwnd, width, height)
        _EDGE_SESSION["embedded_parent_client_size"] = (int(width), int(height))
        if _EDGE_SESSION.get("native_embed_mode") in {"top-level-overlay", "detached-top-level-overlay", "detached-unclipped-top-level-overlay", "dwm-thumbnail"}:
            return _position_native_chromium_overlay(_EDGE_SESSION, width, height)
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        crop_left, crop_top, crop_right, crop_bottom = _embedded_chrome_crop(_EDGE_SESSION)
        _EDGE_SESSION["chrome_crop"] = (crop_left, crop_top, crop_right, crop_bottom)
        user32.SetWindowPos(
            _as_hwnd(hwnd), _as_hwnd(0),
            -int(crop_left), -int(crop_top),
            max(1, int(width) + int(crop_left) + int(crop_right)),
            max(1, int(height) + int(crop_top) + int(crop_bottom)),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

        # v4.73: never swap Chrome_WidgetWin owners during resize. Refresh only
        # the live page RenderWidgetHost descendant of the already embedded owner.
        _refresh_render_host_within_owner(_EDGE_SESSION, width, height)

        # v4.69: re-measure after the owner has its provisional live size.
        # This catches Chromium switching from app chrome to a normal toolbar
        # during startup/activation without ever exposing that toolbar in
        # Tekzite.  A second pass converges on the RenderWidgetHost inset.
        post_crop = _live_render_host_crop(_EDGE_SESSION)
        if post_crop is not None and tuple(post_crop) != (crop_left, crop_top, crop_right, crop_bottom):
            crop_left, crop_top, crop_right, crop_bottom = map(int, post_crop)
            _EDGE_SESSION["chrome_crop"] = (crop_left, crop_top, crop_right, crop_bottom)
            _EDGE_SESSION["post_resize_crop_corrected"] = True
            user32.SetWindowPos(
                _as_hwnd(hwnd), _as_hwnd(0),
                -crop_left, -crop_top,
                max(1, int(width) + crop_left + crop_right),
                max(1, int(height) + crop_top + crop_bottom),
                SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        else:
            _EDGE_SESSION["post_resize_crop_corrected"] = False

        _EDGE_SESSION["embedded_size"] = (max(1, int(width)), max(1, int(height)))
        _show_embedded_render_host(_EDGE_SESSION, width, height)
        return True
    except Exception:
        return False




def _pulse_tekzite_top_level_activation(session=None):
    """Force the native activation transition a real title-bar click provides.

    v4.74: SetForegroundWindow/SetActiveWindow alone can be a no-op when the
    Tekzite root is already foreground.  Current Chromium/DWM combinations can
    then leave an embedded GPU surface allocated but unpresented until Windows
    observes a genuine non-client activation transition.  Pulse the top-level
    activation state, force a frame/child redraw, wait for DWM to consume it,
    and leave the root active.  This never changes the root geometry.
    """
    session = session or _EDGE_SESSION
    if os.name != "nt" or not session or session.get("presentation_mode") == "software":
        return False
    parent = _hwnd_int(session.get("embedded_parent") or 0)
    owner = _hwnd_int(session.get("embedded_hwnd") or 0)
    render = _hwnd_int(session.get("render_hwnd") or 0)
    if not parent:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        user32.RedrawWindow.restype = wintypes.BOOL
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.UpdateWindow.restype = wintypes.BOOL

        GA_ROOT = 2
        root = _hwnd_int(user32.GetAncestor(_as_hwnd(parent), GA_ROOT) or 0)
        if not root or not user32.IsWindow(_as_hwnd(root)):
            return False

        # A SetForegroundWindow call can be optimized away when the root is
        # already active.  Explicitly pulse the activation messages so the
        # non-client frame and DWM compositor see a real state transition.
        WM_ACTIVATE = 0x0006
        WM_NCACTIVATE = 0x0086
        WM_ACTIVATEAPP = 0x001C
        WA_INACTIVE = 0
        WA_ACTIVE = 1
        user32.SendMessageW(_as_hwnd(root), WM_NCACTIVATE, 0, 0)
        user32.SendMessageW(_as_hwnd(root), WM_ACTIVATE, WA_INACTIVE, 0)
        user32.SendMessageW(_as_hwnd(root), WM_ACTIVATEAPP, 0, 0)
        user32.SendMessageW(_as_hwnd(root), WM_ACTIVATEAPP, 1, 0)
        user32.SendMessageW(_as_hwnd(root), WM_NCACTIVATE, 1, 0)
        user32.SendMessageW(_as_hwnd(root), WM_ACTIVATE, WA_ACTIVE, 0)

        HWND_TOP = 0
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOOWNERZORDER = 0x0200
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(
            _as_hwnd(root), _as_hwnd(HWND_TOP), 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOOWNERZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        user32.SetForegroundWindow(_as_hwnd(root))
        user32.SetActiveWindow(_as_hwnd(root))

        RDW_INVALIDATE = 0x0001
        RDW_ERASE = 0x0004
        RDW_FRAME = 0x0400
        RDW_ALLCHILDREN = 0x0080
        RDW_UPDATENOW = 0x0100
        redraw_flags = RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW
        for value in (root, parent, owner, render):
            if value and user32.IsWindow(_as_hwnd(value)):
                user32.RedrawWindow(_as_hwnd(value), None, None, redraw_flags)
                user32.UpdateWindow(_as_hwnd(value))

        # DwmFlush is the important boundary: do not hand focus back until the
        # desktop compositor has consumed the activation/redraw work.
        dwm_ok = False
        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmFlush.argtypes = []
            dwmapi.DwmFlush.restype = wintypes.HRESULT
            dwm_ok = (int(dwmapi.DwmFlush()) == 0)
        except Exception:
            dwm_ok = False

        session["activation_pulse_root"] = int(root)
        session["activation_pulse_sent"] = True
        session["activation_pulse_dwm_flush"] = bool(dwm_ok)
        return True
    except Exception as exc:
        session["activation_pulse_error"] = str(exc)
        return False


def _reapply_native_content_crop_after_activation(session=None):
    """Re-measure Chromium chrome after the v4.74 activation pulse.

    Some Chromium builds expose or resize their normal tab/address chrome only
    when the top-level application becomes genuinely active.  Cropping before
    that transition is therefore stale: the page wakes correctly, but Chromium
    chrome becomes visible inside Tekzite.  Keep the activated compositor owner
    locked, refresh only its live page RenderWidgetHost child, then position the
    owner so that the render-host rectangle maps exactly onto Tekzite's host.
    """
    session = session or _EDGE_SESSION
    if os.name != "nt" or not session or session.get("presentation_mode") == "software":
        return False
    owner = _hwnd_int(session.get("embedded_hwnd") or 0)
    parent = _hwnd_int(session.get("embedded_parent") or 0)
    if not owner or not parent:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(owner)) or not user32.IsWindow(_as_hwnd(parent)):
            return False

        size = session.get("embedded_size") or session.get("embedded_parent_client_size") or (1, 1)
        width, height = _native_client_size(parent, int(size[0]), int(size[1]))
        session["embedded_parent_client_size"] = (int(width), int(height))

        # The owner is deliberately locked (v4.73).  Only refresh the active
        # page child inside that owner after activation changed its chrome.
        # Chromium may publish the activated browser-chrome geometry one or two
        # compositor ticks after WM_ACTIVATE.  Do not freeze the pre-activation
        # geometry (often top=0/bottom~=toolbar height).  Retry briefly until the
        # large page RenderWidgetHost has moved to its stable content inset.
        crop = None
        attempts = 0
        for attempts in range(1, 4):
            _refresh_render_host_within_owner(session, width, height)
            candidate = _live_render_host_crop(session)
            if candidate is not None:
                left0, top0, right0, bottom0 = map(int, candidate)
                crop = candidate
                # A normal Chromium frame has its non-content chrome above the
                # page.  top~=0 with a large bottom inset is a known transient
                # seen immediately after activation, so give Chromium another
                # compositor tick before accepting it.
                if not (top0 <= 8 and bottom0 >= 48):
                    break
            if attempts < 3:
                try:
                    ctypes.windll.kernel32.Sleep(35)
                except Exception:
                    import time
                    time.sleep(0.035)
        session["post_activation_crop_attempts"] = int(attempts)
        if crop is None:
            session["post_activation_crop_reapplied"] = False
            session["post_activation_crop_error"] = "no live render-host crop"
            return False
        left, top, right, bottom = map(int, crop)
        session["chrome_crop"] = (left, top, right, bottom)
        session["post_activation_crop"] = (left, top, right, bottom)

        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040
        ok = bool(user32.SetWindowPos(
            _as_hwnd(owner), _as_hwnd(0),
            -left, -top,
            max(1, int(width) + left + right),
            max(1, int(height) + top + bottom),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        ))
        session["post_activation_crop_reapplied"] = bool(ok)
        session["embedded_size"] = (max(1, int(width)), max(1, int(height)))

        # Keep the actual page child visible at the newly measured inset.  Do
        # this after moving the owner so the page lands at (0,0) in Tekzite.
        _show_embedded_render_host(session, width, height)

        RDW_INVALIDATE = 0x0001
        RDW_FRAME = 0x0400
        RDW_ALLCHILDREN = 0x0080
        RDW_UPDATENOW = 0x0100
        flags = RDW_INVALIDATE | RDW_FRAME | RDW_ALLCHILDREN | RDW_UPDATENOW
        user32.RedrawWindow(_as_hwnd(owner), None, None, flags)
        user32.UpdateWindow(_as_hwnd(owner))

        dwm_ok = False
        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmFlush.argtypes = []
            dwmapi.DwmFlush.restype = wintypes.HRESULT
            dwm_ok = (int(dwmapi.DwmFlush()) == 0)
        except Exception:
            dwm_ok = False
        session["post_activation_crop_dwm_flush"] = bool(dwm_ok)
        return bool(ok)
    except Exception as exc:
        session["post_activation_crop_reapplied"] = False
        session["post_activation_crop_error"] = str(exc)
        return False


def wake_embedded_chromium():
    """Activate and repaint Tekzite's embedded Chromium surface.

    Some Chromium/Windows combinations do not present their first compositor
    frame until the containing top-level window receives a native activation
    event.  A manual title-bar click provides that event.  Reproduce it here
    without user interaction: activate Tekzite's root HWND, refresh the clipped
    Chromium geometry, invalidate both host and child, and then focus the page.
    """
    if os.name != "nt" or not _EDGE_SESSION:
        return False
    if _EDGE_SESSION.get("presentation_mode") == "software":
        return False
    hwnd = _EDGE_SESSION.get("embedded_hwnd")
    parent = _EDGE_SESSION.get("embedded_parent")
    if not hwnd or not parent:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _typed_user32()
        _apply_tekzite_chromium_branding(_EDGE_SESSION)
        target = _as_hwnd(hwnd)
        host = _as_hwnd(parent)
        if not user32.IsWindow(target) or not user32.IsWindow(host):
            return False

        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.InvalidateRect.restype = wintypes.BOOL

        GA_ROOT = 2
        SW_SHOW = 5
        root = user32.GetAncestor(host, GA_ROOT)
        if root:
            user32.ShowWindow(root, SW_SHOW)
            user32.SetForegroundWindow(root)
            user32.SetActiveWindow(root)

        # v4.74: reproduce the non-client activation transition that a manual
        # title-bar click was still required to generate on some systems.
        _pulse_tekzite_top_level_activation(_EDGE_SESSION)

        # Re-applying the same size generates the native size/position work
        # Chromium normally receives after a title-bar activation.
        size = _EDGE_SESSION.get("embedded_size") or (1, 1)
        try:
            resize_embedded_chromium(max(1, int(size[0])), max(1, int(size[1])))
        except Exception:
            pass

        # v4.75: activation itself can make Chromium expose/re-size normal
        # browser chrome.  Re-measure and reapply the content crop *after* the
        # activation pulse so only page pixels remain visible.
        _reapply_native_content_crop_after_activation(_EDGE_SESSION)

        user32.ShowWindow(target, SW_SHOW)
        user32.BringWindowToTop(target)

        RDW_INVALIDATE = 0x0001
        RDW_ERASE = 0x0004
        RDW_ALLCHILDREN = 0x0080
        RDW_UPDATENOW = 0x0100
        flags = RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW
        for window in (host, target):
            user32.InvalidateRect(window, None, True)
            user32.RedrawWindow(window, None, None, flags)
            user32.UpdateWindow(window)

        # Commit the child redraw before handing keyboard focus to Chromium.
        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmFlush()
            _EDGE_SESSION["wake_dwm_flush"] = True
        except Exception:
            _EDGE_SESSION["wake_dwm_flush"] = False

        # Finish with the existing cross-thread focus bridge.
        focus_embedded_chromium()
        _EDGE_SESSION["last_wake_hwnd"] = _hwnd_int(hwnd)
        return True
    except Exception:
        return False


def focus_embedded_chromium():
    """Activate Tekzite and give keyboard focus to Chromium's real page HWND.

    v4.70: focusing the embedded owner widget is not enough on current Chromium
    builds.  The visible webpage lives in Chrome_RenderWidgetHostHWND, often on
    a different UI thread.  A manual title-bar click activates Tekzite's root
    input queue, after which Chromium can accept keyboard focus.  Reproduce
    that sequence explicitly: activate the Tekzite root, temporarily join the
    Tk/root/render input queues, focus the render host, then detach again.
    """
    if os.name != "nt" or not _EDGE_SESSION:
        return False
    if _EDGE_SESSION.get("presentation_mode") == "software":
        return False
    owner_hwnd = _hwnd_int(_EDGE_SESSION.get("embedded_hwnd") or 0)
    # v4.89: navigation/login can replace Chrome_RenderWidgetHostHWND while
    # keeping the locked compositor owner. Refresh the descendant immediately
    # before every focus handoff so SetFocus never targets a stale/hidden RWH.
    try:
        _refresh_render_host_within_owner(_EDGE_SESSION)
    except Exception:
        pass
    render_hwnd = _hwnd_int(_EDGE_SESSION.get("render_hwnd") or 0)
    parent_hwnd = _hwnd_int(_EDGE_SESSION.get("embedded_parent") or 0)
    # Prefer the actual page surface. Fall back to the owner only for older
    # Chromium layouts where a render host could not be discovered.
    focus_hwnd = render_hwnd or owner_hwnd
    if not focus_hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = _typed_user32()
        target = _as_hwnd(focus_hwnd)
        owner = _as_hwnd(owner_hwnd or focus_hwnd)
        host = _as_hwnd(parent_hwnd) if parent_hwnd else owner
        if not user32.IsWindow(target):
            return False

        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        GA_ROOT = 2
        SW_SHOW = 5
        root = user32.GetAncestor(host, GA_ROOT) if host else None
        if root:
            user32.ShowWindow(root, SW_SHOW)
            user32.SetForegroundWindow(root)
            user32.SetActiveWindow(root)

        current_tid = int(kernel32.GetCurrentThreadId())
        root_tid = int(user32.GetWindowThreadProcessId(root, None)) if root else current_tid
        owner_tid = int(user32.GetWindowThreadProcessId(owner, None)) if owner else 0
        target_tid = int(user32.GetWindowThreadProcessId(target, None))

        # Attach every distinct foreign UI queue to the Tk caller for the
        # shortest possible time.  This lets SetFocus cross process/thread
        # boundaries without leaving queues permanently joined.
        attached = []
        for tid in (root_tid, owner_tid, target_tid):
            if not tid or tid == current_tid or tid in attached:
                continue
            if user32.AttachThreadInput(current_tid, tid, True):
                attached.append(tid)
        try:
            if root:
                user32.SetActiveWindow(root)
            if owner and user32.IsWindow(owner):
                user32.ShowWindow(owner, SW_SHOW)
                user32.BringWindowToTop(owner)
            user32.ShowWindow(target, SW_SHOW)
            user32.SetFocus(target)
        finally:
            for tid in reversed(attached):
                user32.AttachThreadInput(current_tid, tid, False)

        _EDGE_SESSION["focus_hwnd"] = int(focus_hwnd)
        _EDGE_SESSION["focus_target_class"] = "Chrome_RenderWidgetHostHWND" if render_hwnd else "owner-fallback"
        _EDGE_SESSION["focus_root_activated"] = bool(root)
        return True
    except Exception as exc:
        _EDGE_SESSION["focus_error"] = str(exc)
        return False


def _clear_embedded_chromium_device_metrics(session=None, target_id: str = None, timeout: int = 3):
    """Remove CDP viewport overrides before a tab returns to native HWND mode."""
    session = session or _EDGE_SESSION
    if not session or not session.get("port"):
        return False
    try:
        channel = _get_persistent_page_cdp_channel(
            session, target_id=target_id, timeout=timeout, purpose="control"
        )
        _persistent_page_cdp_call(
            session, "Emulation.clearDeviceMetricsOverride",
            target_id=channel["target_id"], timeout=timeout, purpose="control",
        )
        # Capture lane caches its own last override. Invalidate it so a later
        # software presentation reinstalls the correct metrics exactly once.
        for key, item in list((session.get("cdp_channels") or {}).items()):
            if isinstance(item, dict) and item.get("target_id") == channel["target_id"]:
                item["device_metrics"] = None
        return True
    except Exception:
        return False


def set_embedded_chromium_presentation(mode: str, target_id: str = None):
    """Select one authoritative presentation path for the active Chromium tab."""
    session = _EDGE_SESSION or _start_persistent_chromium_session()
    mode = "software" if str(mode).lower() == "software" else "native"
    session["presentation_mode"] = mode
    if mode == "native":
        _clear_embedded_chromium_device_metrics(session, target_id=target_id)
    return mode


def _png_dimensions(data: bytes):
    """Return PNG width/height without decoding the whole image."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 24:
        return None
    if bytes(data[:8]) != b"\x89PNG\r\n\x1a\n" or bytes(data[12:16]) != b"IHDR":
        return None
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def _apply_native_chromium_zoom_extension(session, percent: int, timeout: float = 4.0):
    """Set true Chromium tab zoom through Tekzite's local extension.

    The extension uses chrome.tabs.setZoom(), so this is browser zoom rather than
    CSS document scaling. Its background worker also listens to onZoomChange and
    navigation events and restores the saved value if a page/tab changes it.
    """
    factor = max(0.5, min(3.0, float(percent) / 100.0))
    url = (
        f"chrome-extension://{TEKZITE_ZOOM_EXTENSION_ID}/bridge.html"
        f"?zoom={factor:.6f}&t={int(time.time() * 1000)}"
    )
    target_id = None
    try:
        result = _browser_cdp_call(
            session, "Target.createTarget",
            {"url": url, "newWindow": False, "background": True},
            message_id=701, timeout=timeout,
        )
        target_id = result.get("targetId")
        if not target_id:
            raise RuntimeError("zoom bridge target was not created")
        deadline = time.monotonic() + max(0.8, float(timeout))
        done_title = None
        while time.monotonic() < deadline:
            try:
                pages = _devtools_json(session["port"], "/json/list", timeout=0.8)
                page = next((item for item in pages if item.get("id") == target_id), None)
                if page and page.get("webSocketDebuggerUrl"):
                    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=1.0)
                    try:
                        result = _cdp_call(
                            ws, "Runtime.evaluate",
                            {"expression": "document.title", "returnByValue": True},
                            message_id=1, timeout=1.0,
                        )
                        done_title = (((result or {}).get("result") or {}).get("value"))
                    finally:
                        try: ws.close()
                        except Exception: pass
                    if str(done_title or "").startswith("TEKZITE_ZOOM_DONE:"):
                        break
            except Exception:
                pass
            time.sleep(0.04)
        ok = str(done_title or "").startswith("TEKZITE_ZOOM_DONE:")
        verified = None
        eligible = None
        applied = None
        if ok:
            try:
                parts = str(done_title).split(":")
                applied = int(parts[3])
                verified = int(parts[4])
                eligible = int(parts[5])
                ok = bool(eligible == 0 or verified == eligible)
            except Exception:
                pass
        session["native_zoom_extension_id"] = TEKZITE_ZOOM_EXTENSION_ID
        session["native_zoom_extension_loaded"] = ok
        session["native_zoom_bridge_last_title"] = done_title
        session["native_zoom_bridge_applied_tabs"] = applied
        session["native_zoom_bridge_verified_tabs"] = verified
        session["native_zoom_bridge_eligible_tabs"] = eligible
        session["native_zoom_bridge_apply_count"] = int(session.get("native_zoom_bridge_apply_count") or 0) + 1
        session["page_zoom_strategy"] = "chromium-tabs-setZoom"
        session["zoom_watchdog_strategy"] = "extension-tabs.onZoomChange"
        return ok
    except Exception as exc:
        session["native_zoom_extension_loaded"] = False
        session["native_zoom_bridge_error"] = f"{type(exc).__name__}: {exc}"
        return False
    finally:
        if target_id:
            try:
                _browser_cdp_call(
                    session, "Target.closeTarget", {"targetId": target_id},
                    message_id=702, timeout=2.0,
                )
            except Exception:
                pass


def check_embedded_chromium_zoom(percent: int = 100, target_id: str = None, timeout: int = 2):
    """Report the native Chromium zoom watchdog state without touching page DOM.

    v7.0 monitoring lives in the local extension itself. chrome.tabs.onZoomChange
    observes the real browser zoom and immediately restores the Preferences value.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    try:
        percent = max(50, min(300, int(percent)))
    except Exception:
        percent = 100
    status = {
        "ready": bool(session and session.get("port")),
        "matches": bool(session and session.get("native_zoom_extension_loaded")),
        "target_id": target_id,
        "expected": percent / 100.0,
        "strategy": "extension-tabs.onZoomChange",
        "extension_id": TEKZITE_ZOOM_EXTENSION_ID,
    }
    if session:
        session["zoom_watchdog_last_observed"] = dict(status)
        session["zoom_watchdog_expected_percent"] = percent
    return status


def set_embedded_chromium_zoom(percent: int = 100, target_id: str = None, timeout: int = 3):
    """Apply true Chromium browser zoom to every Tekzite page tab.

    No documentElement.style.zoom or other site DOM mutation is used. The local
    extension applies chrome.tabs.setZoom() and continuously enforces the same
    value through Chromium's own tab lifecycle and zoom-change events.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return False
    try:
        percent = max(50, min(300, int(percent)))
    except Exception:
        percent = 100
    session["default_page_zoom_percent"] = percent
    session["dwm_zoom_percent"] = percent
    session["preferences_zoom_percent"] = percent
    session["page_zoom_dom_observer"] = False
    session["page_zoom_site_specific_hacks"] = False
    session["page_zoom_new_document_script"] = False
    session["page_zoom_deferred_while_loading"] = False
    return _apply_native_chromium_zoom_extension(session, percent, timeout=max(3, timeout))

def _software_viewport_state(session, target_id, timeout, purpose="capture"):
    result = _persistent_page_cdp_call(
        session,
        "Runtime.evaluate",
        {
            "expression": "(() => ({iw: innerWidth, ih: innerHeight, dpr: devicePixelRatio, scale: (visualViewport && visualViewport.scale) || 1}))()",
            "returnByValue": True,
        },
        target_id=target_id, timeout=timeout, purpose=purpose,
    )
    try:
        return dict(result.get("result", {}).get("value") or {})
    except Exception:
        return {}


def _apply_strict_software_viewport(session, channel, width, height, timeout, force=False):
    """Install one deterministic CSS/pixel viewport for software presentation.

    v5.08 keeps a short-lived validated contract cache. The old software loop
    sent setPageScaleFactor + Runtime.evaluate before *every* screenshot even
    when neither target nor viewport had changed. During interactive ~30 FPS
    capture those extra synchronous CDP round-trips were a major latency source.
    Resizes still invalidate immediately because ``metrics`` changes, and a
    periodic revalidation keeps the strict contract self-healing.
    """
    metrics = (max(1, int(width)), max(1, int(height)), 1)
    now = time.monotonic()
    cached_contract = channel.get("viewport_contract") or {}
    cached_at = float(channel.get("viewport_contract_checked_at") or 0.0)
    if (
        not force
        and channel.get("device_metrics") == metrics
        and cached_contract.get("ok") is True
        and tuple(cached_contract.get("expected") or ()) == metrics[:2]
        and (now - cached_at) < 1.5
    ):
        channel["viewport_contract_cache_hit"] = True
        return True, cached_contract
    channel["viewport_contract_cache_hit"] = False
    if force or channel.get("device_metrics") != metrics:
        _persistent_page_cdp_call(
            session,
            "Emulation.setDeviceMetricsOverride",
            {
                "width": metrics[0],
                "height": metrics[1],
                "deviceScaleFactor": 1,
                "mobile": False,
                "screenWidth": metrics[0],
                "screenHeight": metrics[1],
                "positionX": 0,
                "positionY": 0,
                "scale": 1,
                "dontSetVisibleSize": False,
            },
            target_id=channel["target_id"], timeout=timeout, purpose="capture",
        )
        channel["device_metrics"] = metrics
    # A previous Chromium/browser zoom state can survive while the bitmap itself
    # still has the expected dimensions. Lock visual page scale as well so a
    # 1280x676 image cannot secretly contain a zoomed 1024px CSS viewport.
    _persistent_page_cdp_call(
        session, "Emulation.setPageScaleFactor", {"pageScaleFactor": 1},
        target_id=channel["target_id"], timeout=timeout, purpose="capture",
    )
    state = _software_viewport_state(session, channel["target_id"], timeout, purpose="capture")
    iw = int(round(float(state.get("iw", -1) or -1)))
    ih = int(round(float(state.get("ih", -1) or -1)))
    dpr = float(state.get("dpr", -1) or -1)
    scale = float(state.get("scale", -1) or -1)
    known = (iw >= 0 and ih >= 0 and dpr >= 0 and scale >= 0)
    ok = (not known) or (abs(iw - metrics[0]) <= 1 and abs(ih - metrics[1]) <= 1
          and abs(dpr - 1.0) <= 0.01 and abs(scale - 1.0) <= 0.01)
    channel["viewport_contract"] = {
        "expected": metrics[:2], "inner": (iw, ih), "dpr": dpr, "scale": scale,
        "known": known, "ok": ok
    }
    channel["viewport_contract_checked_at"] = time.monotonic()
    return ok, channel["viewport_contract"]


def capture_embedded_chromium_frame(timeout: int = 4, target_id: str = None, viewport_width: int = None, viewport_height: int = None):
    """Return a lossless frame that strictly matches Tekzite's latched viewport.

    v4.67 rejects frames whose CSS viewport, DPR/page scale, or PNG dimensions
    drift away from the active software-surface contract. The capture lane is
    rebuilt and the contract reapplied before retrying, rather than displaying
    an oversized frame and making the page appear to zoom.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        raise RuntimeError("Chromium helper is not running")
    session["presentation_mode"] = "software"
    expected = None
    if viewport_width and viewport_height:
        expected = (max(1, int(viewport_width)), max(1, int(viewport_height)))

    last_problem = None
    for attempt in range(3):
        channel = _get_persistent_page_cdp_channel(
            session, target_id=target_id, timeout=timeout, purpose="capture"
        )
        if "Page" not in channel["enabled_domains"]:
            _persistent_page_cdp_call(
                session, "Page.enable", target_id=channel["target_id"], timeout=timeout, purpose="capture"
            )
            channel["enabled_domains"].add("Page")

        if expected:
            ok, contract = _apply_strict_software_viewport(
                session, channel, expected[0], expected[1], timeout, force=(attempt > 0)
            )
            if not ok:
                last_problem = f"viewport contract {contract}"
                _close_persistent_page_cdp_channels(session, target_id=channel["target_id"])
                continue

        shot = _persistent_page_cdp_call(
            session,
            "Page.captureScreenshot",
            {
                "format": "png",
                "fromSurface": True,
                "captureBeyondViewport": False,
                "optimizeForSpeed": True,
            },
            target_id=channel["target_id"], timeout=timeout, purpose="capture",
        )
        data = shot.get("data", "") if isinstance(shot, dict) else ""
        if not data:
            last_problem = "empty screenshot"
            _close_persistent_page_cdp_channels(session, target_id=channel["target_id"])
            continue
        png = base64.b64decode(data)
        dims = _png_dimensions(png)
        if expected and dims is not None and dims != expected:
            last_problem = f"PNG {dims} != viewport {expected}"
            _close_persistent_page_cdp_channels(session, target_id=channel["target_id"])
            continue
        return png

    raise RuntimeError(f"Chromium software frame contract failed: {last_problem or 'unknown mismatch'}")



def record_embedded_surface_probe(blank, span=None, dominant=None, attempt=1, fallback=False, error=None):
    """Record final on-screen native presentation health for Full Debug."""
    session = _EDGE_SESSION
    if not session:
        return False
    session["visible_surface_probe_attempt"] = int(attempt or 0)
    session["visible_surface_blank"] = bool(blank)
    session["visible_surface_span"] = span
    session["visible_surface_dominant_ratio"] = dominant
    session["visible_surface_software_fallback"] = bool(fallback)
    session["visible_surface_probe_error"] = error
    return True


def validate_and_recover_embedded_chromium_frame(target_id: str = None, timeout: float = 2.0):
    """Detect a consent/navigation compositor blank after a native interaction.

    Some Chromium sites (YouTube cookie consent is a reproducible example) can
    briefly replace the renderer/surface after a click.  If two successive CDP
    captures are near-uniform black/white, refresh the live render HWND and run
    the existing native wake/compositor-prime path instead of leaving Tekzite
    showing the dead surface. Normal dark pages and popup menus are untouched.
    """
    session = _EDGE_SESSION
    if not session or session.get("presentation_mode") == "software":
        return False
    try:
        def capture_metrics():
            result = _persistent_page_cdp_call(
                session, "Page.captureScreenshot",
                {"format":"png", "fromSurface":True,
                 "captureBeyondViewport":False, "optimizeForSpeed":True},
                target_id=target_id, timeout=max(0.5, float(timeout)),
            )
            data = (result or {}).get("data", "")
            return _analyze_embedded_frame_png(data), len(data) if isinstance(data, str) else 0

        m1, n1 = capture_metrics()
        session["post_interaction_probe_chars"] = n1
        session["post_interaction_black_ratio"] = m1.get("black_ratio")
        session["post_interaction_white_ratio"] = m1.get("white_ratio")
        session["post_interaction_visual"] = m1.get("visual")
        if m1.get("visual"):
            session["post_interaction_recovered"] = False
            return False

        time.sleep(0.12)
        m2, n2 = capture_metrics()
        if m2.get("visual"):
            session["post_interaction_recovered"] = False
            return False

        session["post_interaction_blank_confirmed"] = True
        try:
            _refresh_render_host_within_owner(session)
        except Exception:
            pass
        recovered = bool(wake_embedded_chromium())
        session["post_interaction_recovered"] = recovered
        session["post_interaction_probe2_chars"] = n2
        return recovered
    except Exception as exc:
        session["post_interaction_probe_error"] = type(exc).__name__
        return False


def get_embedded_chromium_dwm_input_offset():
    """Return the live DWM-to-CDP pointer coordinate correction."""
    session = _EDGE_SESSION or {}
    try:
        x, y = session.get("dwm_input_offset") or (0, 0)
        return float(x), float(y)
    except Exception:
        return 0.0, 0.0




def get_embedded_chromium_input_zoom_factor():
    """Return the native Chromium zoom factor used for DWM -> CDP input mapping.

    Chromium's DWM surface is presented in physical pixels, while CDP mouse and
    elementFromPoint coordinates are expressed in CSS viewport pixels. Once the
    v7 native zoom extension is confirmed active, divide visible DWM coordinates
    by this factor before sending input. If native zoom has not been verified,
    return 1.0 so input never gets mis-scaled speculatively.
    """
    session = _EDGE_SESSION or {}
    try:
        if not bool(session.get("native_zoom_extension_loaded")):
            session["dwm_input_zoom_factor"] = 1.0
            session["dwm_input_zoom_active"] = False
            return 1.0
        percent = max(50, min(300, int(session.get("default_page_zoom_percent") or 100)))
        factor = float(percent) / 100.0
        session["dwm_input_zoom_factor"] = factor
        session["dwm_input_zoom_active"] = True
        return factor
    except Exception:
        session["dwm_input_zoom_factor"] = 1.0
        session["dwm_input_zoom_active"] = False
        return 1.0


def dispatch_embedded_chromium_mouse(event_type: str, x: float, y: float, *,
                                     button: str = "none", buttons: int = None,
                                     delta_x: float = 0.0, delta_y: float = 0.0,
                                     click_count: int = 1,
                                     target_id: str = None, timeout: int = 3):
    """Forward pointer/wheel input over the tab's persistent CDP channel."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return False
    params = {"type": str(event_type), "x": float(x), "y": float(y)}
    if event_type == "mouseWheel":
        params.update({"deltaX": float(delta_x), "deltaY": float(delta_y)})
    else:
        params.update({"button": button, "clickCount": int(click_count)})
        if buttons is not None:
            params["buttons"] = int(buttons)
    _persistent_page_cdp_call(
        session, "Input.dispatchMouseEvent", params,
        target_id=target_id, timeout=timeout, purpose="input",
    )
    return True


def get_embedded_chromium_cursor(x: float, y: float, *, target_id: str = None, timeout: int = 2):
    """Return the effective CSS cursor for the element under page coordinates.

    DWM mirrors Chromium pixels into a Tekzite-owned input plane, so Windows
    cannot inherit Chromium's native cursor automatically. This tiny CDP probe
    mirrors the page cursor without activating or moving Chromium's HWND.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return "auto"
    expr = f"""(() => {{
      const el = document.elementFromPoint({float(x)!r}, {float(y)!r});
      if (!el) return 'auto';
      let cursor = '';
      try {{ cursor = String(getComputedStyle(el).cursor || ''); }} catch (_) {{}}
      if (cursor && cursor !== 'auto') return cursor;
      const clickable = el.closest && el.closest('a[href], button, summary, [role="button"], [onclick]');
      if (clickable) return 'pointer';
      const editable = el.closest && el.closest('input, textarea, [contenteditable="true"]');
      if (editable) return 'text';
      return cursor || 'auto';
    }})()"""
    result = _persistent_page_cdp_call(
        session, "Runtime.evaluate",
        {"expression": expr, "returnByValue": True},
        target_id=target_id, timeout=timeout, purpose="input",
    )
    value = (((result or {}).get("result") or {}).get("value"))
    return str(value or "auto")


def get_embedded_chromium_context(x: float, y: float, *, target_id: str = None, timeout: int = 3):
    """Return context-menu metadata using the persistent page CDP channel."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return {}
    expr = f"""(() => {{
      const x = {float(x)!r}, y = {float(y)!r};
      const el = document.elementFromPoint(x, y);
      const a = el && el.closest ? el.closest('a[href]') : null;
      const img = el && el.closest ? el.closest('img') : null;
      const sel = String(window.getSelection ? window.getSelection() : '');
      return {{
        tag: el ? String(el.tagName || '').toLowerCase() : '',
        text: el ? String(el.innerText || el.textContent || '').trim().slice(0, 500) : '',
        href: a ? String(a.href || '') : '',
        image_src: img ? String(img.currentSrc || img.src || '') : '',
        selected_text: sel.slice(0, 5000),
        editable: !!(el && (el.isContentEditable || /^(INPUT|TEXTAREA)$/.test(el.tagName || ''))),
        page_url: String(location.href || ''),
        page_title: String(document.title || '')
      }};
    }})()"""
    result = _persistent_page_cdp_call(
        session, "Runtime.evaluate",
        {"expression": expr, "returnByValue": True},
        target_id=target_id, timeout=timeout,
    )
    value = (((result or {}).get("result") or {}).get("value"))
    return value if isinstance(value, dict) else {}


def focus_embedded_chromium_point(x: float, y: float, *, target_id: str = None, timeout: int = 3):
    """Focus an editable element at page coordinates without activating Chromium's HWND."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return False
    expr = f"""(() => {{
      const el = document.elementFromPoint({float(x)!r}, {float(y)!r});
      if (!el) return {{focused:false, tag:''}};
      const editable = el.closest && el.closest('input, textarea, [contenteditable="true"]');
      const target = editable || el;
      try {{ if (target && target.focus) target.focus({{preventScroll:true}}); }} catch (_) {{ try {{ target.focus(); }} catch (_) {{}} }}
      return {{
        focused: document.activeElement === target || document.activeElement === editable,
        editable: !!editable,
        tag: String((document.activeElement && document.activeElement.tagName) || '').toLowerCase()
      }};
    }})()"""
    result = _persistent_page_cdp_call(
        session, "Runtime.evaluate", {"expression": expr, "returnByValue": True},
        target_id=target_id, timeout=timeout, purpose="input",
    )
    value = (((result or {}).get("result") or {}).get("value"))
    return bool(isinstance(value, dict) and value.get("focused"))


def dispatch_embedded_chromium_key(key: str = "", *, text: str = "",
                                   event_type: str = "keyDown", modifiers: int = 0,
                                   windows_vk: int = 0, code: str = "",
                                   target_id: str = None, timeout: int = 3):
    """Forward keyboard input over the tab's persistent CDP channel."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return False
    if text and event_type == "insertText":
        _persistent_page_cdp_call(
            session, "Input.insertText", {"text": text},
            target_id=target_id, timeout=timeout, purpose="input",
        )
        return True
    params = {"type": event_type, "key": key, "modifiers": int(modifiers)}
    if code:
        params["code"] = code
    if windows_vk:
        params["windowsVirtualKeyCode"] = int(windows_vk)
        params["nativeVirtualKeyCode"] = int(windows_vk)
    if text and event_type in {"keyDown", "char"}:
        params["text"] = text
        params["unmodifiedText"] = text
    _persistent_page_cdp_call(
        session, "Input.dispatchKeyEvent", params,
        target_id=target_id, timeout=timeout, purpose="input",
    )
    return True



def get_embedded_chromium_page_state(*, target_id: str = None, include_favicon: bool = False, timeout: int = 3):
    """Return lightweight live page metadata for Tekzite's browser chrome."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get('port'):
        return {}
    expr = r'''(() => {
      const icon = document.querySelector('link[rel~="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]');
      return {
        title: String(document.title || ''),
        url: String(location.href || ''),
        readyState: String(document.readyState || ''),
        favicon: icon ? String(icon.href || '') : ((location.protocol === 'http:' || location.protocol === 'https:') ? String(new URL('/favicon.ico', location.href)) : '')
      };
    })()'''
    result = _persistent_page_cdp_call(
        session, 'Runtime.evaluate',
        {'expression': expr, 'returnByValue': True},
        target_id=target_id, timeout=timeout, purpose='page-state',
    )
    value = (((result or {}).get('result') or {}).get('value'))
    if not isinstance(value, dict):
        return {}
    if include_favicon and value.get('favicon'):
        fav_expr = r'''(async () => {
          try {
            const el = document.querySelector('link[rel~="icon"], link[rel="shortcut icon"], link[rel="apple-touch-icon"]');
            if (!el || !el.href) return '';
            const r = await fetch(el.href, {credentials:'include', cache:'force-cache'});
            if (!r.ok) return '';
            const b = await r.blob();
            if (b.size > 524288) return '';
            const ab = await b.arrayBuffer();
            let binary = '';
            const bytes = new Uint8Array(ab);
            for (let i=0; i<bytes.length; i+=0x8000) binary += String.fromCharCode(...bytes.subarray(i, i+0x8000));
            return btoa(binary);
          } catch (_) { return ''; }
        })()'''
        try:
            fav = _persistent_page_cdp_call(
                session, 'Runtime.evaluate',
                {'expression': fav_expr, 'returnByValue': True, 'awaitPromise': True},
                target_id=target_id, timeout=max(timeout, 5), purpose='page-state',
            )
            data = (((fav or {}).get('result') or {}).get('value'))
            if isinstance(data, str):
                value['favicon_b64'] = data
        except Exception:
            pass
    return value


def find_embedded_chromium_text(query: str, *, target_id: str = None, backwards: bool = False, timeout: int = 3):
    """Find/select the next occurrence of text using Chromium's live DOM."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get('port'):
        return False
    import json as _json
    q = _json.dumps(str(query or ''))
    expr = f"window.find({q}, false, {str(bool(backwards)).lower()}, true, false, true, false)"
    result = _persistent_page_cdp_call(
        session, 'Runtime.evaluate',
        {'expression': expr, 'returnByValue': True},
        target_id=target_id, timeout=timeout, purpose='input',
    )
    return bool((((result or {}).get('result') or {}).get('value')))

def get_embedded_chromium_html(timeout: int = 8):
    """Return the live outerHTML of Tekzite's embedded Chromium page.

    This inspects the current DOM after site JavaScript has run.  It does not
    navigate or reload the page, so it is suitable for View Source / HTML
    inspection while preserving the user's current Chromium state.
    """
    session = _start_persistent_chromium_session(timeout=min(timeout, 8))
    page = _pick_devtools_page(session["port"], session)
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    try:
        result = _cdp_call(
            ws,
            "Runtime.evaluate",
            {
                "expression": "document.documentElement ? document.documentElement.outerHTML : ''",
                "returnByValue": True,
            },
            message_id=1,
            timeout=float(timeout),
        )
        html = (
            result.get("result", {}).get("value", "")
            if isinstance(result, dict) else ""
        )
        if not isinstance(html, str):
            html = str(html or "")
        if not html:
            raise RuntimeError("Chromium page exposed no HTML")
        return html
    finally:
        try:
            ws.close()
        except Exception:
            pass

def get_embedded_chromium_layout_snapshot(timeout: int = 10, max_elements: int = 2500):
    """Return Chromium's live DOM geometry + computed style snapshot."""
    session = _start_persistent_chromium_session(timeout=min(timeout, 8))
    page = _pick_devtools_page(session["port"], session)
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    try:
        limit = max(1, min(int(max_elements), 10000))
        expression = r'''(() => {
          const limit = __LIMIT__;
          const pickText = (el) => {
            let out = '';
            for (const node of el.childNodes || []) {
              if (node.nodeType === Node.TEXT_NODE) out += ' ' + (node.textContent || '');
            }
            return out.replace(/\s+/g, ' ').trim().slice(0, 1200);
          };
          const visible = (el, cs, r) => {
            if (!r || r.width <= 0 || r.height <= 0) return false;
            if (cs.display === 'none' || cs.visibility === 'hidden') return false;
            if (Number(cs.opacity || '1') === 0) return false;
            return true;
          };
          const items = [];
          const all = Array.from(document.querySelectorAll('*'));
          for (let i = 0; i < all.length && items.length < limit; i++) {
            const el = all[i];
            const r = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            if (!visible(el, cs, r)) continue;
            items.push({
              tag: (el.tagName || '').toLowerCase(),
              id: el.id || '',
              className: typeof el.className === 'string' ? el.className : '',
              directText: pickText(el),
              rect: {x:r.x,y:r.y,width:r.width,height:r.height,top:r.top,right:r.right,bottom:r.bottom,left:r.left},
              style: {
                display: cs.display, position: cs.position, color: cs.color,
                backgroundColor: cs.backgroundColor, fontFamily: cs.fontFamily,
                fontSize: cs.fontSize, fontWeight: cs.fontWeight, fontStyle: cs.fontStyle,
                lineHeight: cs.lineHeight, textAlign: cs.textAlign,
                textDecoration: cs.textDecorationLine, borderRadius: cs.borderRadius,
                opacity: cs.opacity, overflow: cs.overflow, zIndex: cs.zIndex,
                transform: cs.transform
              }
            });
          }
          const bodyStyle = document.body ? getComputedStyle(document.body) : null;
          return {
            url: location.href, title: document.title || '',
            viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
            devicePixelRatio: window.devicePixelRatio || 1,
            scrollX: window.scrollX || 0, scrollY: window.scrollY || 0,
            bodyBackground: bodyStyle ? bodyStyle.backgroundColor : '',
            totalElements: all.length,
            truncated: items.length >= limit && all.length > items.length,
            elements: items
          };
        })()'''.replace('__LIMIT__', str(limit))
        result = _cdp_call(
            ws,
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            message_id=1,
            timeout=float(timeout),
        )
        value = result.get("result", {}).get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise RuntimeError("Chromium exposed no layout snapshot")
        value.setdefault("elements", [])
        value["source"] = "chromium-layout-oracle"
        return value
    finally:
        try:
            ws.close()
        except Exception:
            pass

def embedded_chromium_history(delta: int):
    """Move Chromium history by *delta* (-1 back, +1 forward)."""
    session = _start_persistent_chromium_session()
    page = _pick_devtools_page(session["port"], session)
    ws = _open_devtools_websocket(page["webSocketDebuggerUrl"], timeout=5)
    try:
        expression = "history.back()" if int(delta) < 0 else "history.forward()"
        _cdp_call(ws, "Runtime.evaluate", {"expression": expression}, message_id=1)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def close_embedded_chromium(clear_profile=False):
    """Shut down Chromium; optionally erase all compatibility profile data."""
    global _EDGE_SESSION
    session = _EDGE_SESSION
    _EDGE_SESSION = None
    if session:
        thumb = session.get("dwm_thumbnail_handle")
        if thumb and os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
                dwmapi.DwmUnregisterThumbnail.argtypes = [wintypes.HANDLE]
                dwmapi.DwmUnregisterThumbnail.restype = wintypes.HRESULT
                dwmapi.DwmUnregisterThumbnail(wintypes.HANDLE(_hwnd_int(thumb)))
            except Exception:
                pass
        _close_persistent_page_cdp_channels(session)
        process = session.get("process")
        if process is not None and process.poll() is None:
            _terminate_helper_process_tree(process)
        profile = session.get("profile") or ""
        _clear_profile_owner(profile, getattr(process, "pid", None))
        if clear_profile and profile:
            try:
                shutil.rmtree(profile, ignore_errors=True)
            except Exception:
                pass
    if clear_profile:
        try:
            _COOKIE_JAR.clear()
        except Exception:
            pass
        try:
            fetch_bytes.cache_clear()
            fetch_document.cache_clear()
        except Exception:
            pass

def _extract_session_cookies(response, request):
    try:
        _COOKIE_JAR.extract_cookies(response, request)
    except Exception:
        # Test doubles and unusual response wrappers may not expose the full
        # urllib response API; cookie persistence is best-effort there.
        pass


@lru_cache(maxsize=256)
def fetch_bytes(url: str) -> bytes:

    if str(url).lower().startswith("data:"):
        header, separator, payload = str(url).partition(",")
        if not separator:
            raise ValueError("invalid data URI")

        if ";base64" in header.lower():
            return base64.b64decode(payload)

        return unquote_to_bytes(payload)

    request = Request(url, headers=SUBRESOURCE_HEADERS)
    _add_session_cookies(request)

    with _network_urlopen(request, timeout=SUBRESOURCE_TIMEOUT) as response:
        _extract_session_cookies(response, request)
        return response.read()


@lru_cache(maxsize=128)
def fetch_document(url: str):
    """Fetch a top-level text document and preserve its final redirected URL."""
    request = Request(url, headers=DOCUMENT_HEADERS)
    _add_session_cookies(request)

    with _network_urlopen(request, timeout=DOCUMENT_TIMEOUT) as response:
        _extract_session_cookies(response, request)
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read()
        final_url = response.geturl() or url

    html = body.decode(charset, errors="replace")

    # Google Search now returns a JavaScript gate to lightweight HTTP clients
    # instead of result HTML. When that happens, let an installed Chromium
    # engine execute the page once and hand the resulting DOM back to Tekzite.
    # Tekzite still owns parsing, CSS, layout and painting after this point.
    if _is_google_search_url(final_url) and _looks_like_google_js_gate(html):
        try:
            rendered = fetch_rendered_dom(final_url)
            if rendered and not _looks_like_google_js_gate(rendered):
                html = rendered
        except Exception:
            # Keep the original response as a graceful fallback. Debug output
            # will still make the JS gate obvious if no compatible browser is
            # installed or the headless launch is blocked.
            pass

    return html, final_url


@lru_cache(maxsize=256)
def fetch_url(url: str) -> str:
    """Fetch a decoded text subresource without document-navigation semantics.

    CSS and JavaScript should not inherit the top-level document request profile
    or its longer timeout. Keep this text-only compatibility API, but perform a
    real subresource request so a dead stylesheet/script cannot hold navigation
    for the full document timeout.
    """

    if str(url).lower().startswith("data:"):
        return fetch_bytes(url).decode("utf-8", errors="replace")

    request = Request(url, headers=SUBRESOURCE_HEADERS)
    _add_session_cookies(request)
    with _network_urlopen(request, timeout=SUBRESOURCE_TIMEOUT) as response:
        _extract_session_cookies(response, request)
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read()

    return body.decode(charset, errors="replace")


def clear_network_cache():
    fetch_bytes.cache_clear()
    fetch_document.cache_clear()
    fetch_url.cache_clear()
