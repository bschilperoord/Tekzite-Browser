from functools import lru_cache
from urllib.request import Request, urlopen, ProxyHandler, build_opener
from urllib.parse import unquote_to_bytes, quote, urljoin
from http.cookiejar import CookieJar
import base64
import io
import os
import shutil
import subprocess
import tempfile
import json
import re
import hashlib
import shutil
import sqlite3
import tempfile
import socket
import ipaddress
import secrets
import time
import sys
import signal
import atexit
import threading
from pathlib import Path
from urllib.request import urlopen as _stdlib_urlopen
from urllib.parse import urlsplit, unquote
from loopback_policy import allow_loopback_port, revoke_loopback_port, snapshot as loopback_policy_snapshot
from .udp_peer_etw import ensure_udp_peer_monitor, stop_udp_peer_monitor

# ctypes.wintypes does not expose HRESULT on every supported Python build
# (notably some packaged Windows/Python combinations). HRESULT is always a
# signed 32-bit LONG, so keep one stable local alias instead of depending on
# that optional wintypes attribute at runtime.
import ctypes as _ctypes
try:
    from ctypes import wintypes as _ctypes_wintypes
    HRESULT = getattr(_ctypes_wintypes, "HRESULT", _ctypes.c_int32)
except Exception:
    HRESULT = _ctypes.c_int32



_ORIGINAL_URLOPEN = urlopen

if sys.platform.startswith("linux"):
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
else:
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

# Security bounds for untrusted webpage metadata crossing the CDP boundary.
MAX_PAGE_TITLE_CHARS = 1024
MAX_PAGE_URL_CHARS = 32768
MAX_FAVICON_URL_CHARS = 8192
MAX_ORIGIN_CHARS = 4096
MAX_HOST_CHARS = 1024
MAX_CDP_WEBSOCKET_FRAME_BYTES = 16 * 1024 * 1024
MAX_CDP_WEBSOCKET_MESSAGE_BYTES = 32 * 1024 * 1024

# One cookie jar for the browser session. urllib follows HTTP redirects for us,
# but does not persist cookies between separate urlopen() calls by itself.
_COOKIE_JAR = CookieJar()

# v4.34: one network process for both Tekzite's native renderer and Chromium.
_NETWORK_ENGINE = None
_NETWORK_OPENER = None
_NETWORK_ENGINE_LOG_HANDLE = None
_NETWORK_ENGINE_LOCK = threading.RLock()

# v10.5.74: request-attribution monitor used only while Live Socket View is
# active. It observes Chromium CDP Network metadata in RAM and never retains
# full URLs, paths, query strings, headers, cookies, or payloads.
_REQUEST_AUDIT_MONITOR = None
_REQUEST_AUDIT_LOCK = threading.RLock()
_REQUEST_AUDIT_MAX_AGE = 45.0
_REQUEST_AUDIT_MAX_RECORDS = 2048

# v10.5.80: browser-owned network work is tracked separately from page CDP
# requests so Tekzite can explain its own minimal helper traffic without
# pretending it came from website JavaScript. Records are hostname-only,
# RAM-only, and short-lived.
_INTERNAL_NETWORK_ACTIVITY = []
_INTERNAL_NETWORK_ACTIVITY_LOCK = threading.RLock()
_INTERNAL_NETWORK_ACTIVITY_MAX_AGE = 15.0
_INTERNAL_NETWORK_ACTIVITY_MAX_RECORDS = 128


def _network_engine_root():
    return Path(__file__).resolve().parent.parent



TEKZITE_ZOOM_EXTENSION_ID = "afhkpeiilpolfogelgpkdijgnmofdiho"

def _zoom_extension_dir():
    return (_network_engine_root() / "chromium_zoom_extension").resolve()


def _configured_user_extension_dirs():
    """Return validated unpacked extension directories requested by Tekzite.

    ``main.py`` exports the enabled Extension Manager entries as JSON. Keeping
    the parsing here means the Chromium launch command remains the final source
    of truth and malformed/stale paths are simply ignored rather than breaking
    browser startup.
    """
    raw = os.environ.get("TEKZITE_USER_EXTENSIONS", "")
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    builtin = os.path.normcase(str(_zoom_extension_dir()))
    for value in values:
        try:
            path = Path(str(value)).expanduser().resolve()
        except Exception:
            continue
        # Chromium's switch uses a comma-separated path list. Reject the rare
        # ambiguous path rather than silently loading the wrong directory.
        if "," in str(path) or not path.is_dir() or not (path / "manifest.json").is_file():
            continue
        key = os.path.normcase(str(path))
        if key == builtin or key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _chromium_extension_dirs():
    return [_zoom_extension_dir(), *_configured_user_extension_dirs()]

def _set_adblock_fallback(enabled):
    from browser_state import write_json
    write_json(_network_engine_state_dir() / "adblock-policy.json", {"enabled": bool(enabled)})


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
    with _NETWORK_ENGINE_LOCK:
        return _stop_network_engine_unlocked()


def _stop_network_engine_unlocked():
    global _NETWORK_ENGINE, _NETWORK_OPENER, _NETWORK_ENGINE_LOG_HANDLE
    state = _NETWORK_ENGINE
    _NETWORK_ENGINE = None
    _NETWORK_OPENER = None

    if state:
        state_port = state.get("port")
        proc = state.get("process")

        # The tracked Popen object is authoritative only while that exact
        # process handle is still alive. Resolve the real listener independently of proc.poll(),
        # but never trust that listener PID without identity verification. Listener PIDs discovered later from the
        # TCP table are never trusted by number alone because Windows can reuse
        # a PID/port after a crash. They must carry this launch's random helper
        # token and expected proxy port on their command line.
        pids = []
        if proc is not None:
            try:
                if proc.poll() is None:
                    pid = int(proc.pid)
                    if pid > 0 and pid != os.getpid():
                        pids.append(pid)
            except Exception:
                pass

        listener_pid = None
        if os.name == "nt" and state_port:
            try:
                candidate = _listener_pid_for_port(int(state_port))
                if candidate and _network_helper_pid_matches_state(candidate, state):
                    listener_pid = int(candidate)
            except Exception:
                listener_pid = None
        if listener_pid and listener_pid not in pids:
            pids.append(listener_pid)

        if os.name == "nt":
            for pid in pids:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception:
                    pass

            if state_port:
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    try:
                        candidate = _listener_pid_for_port(int(state_port))
                    except Exception:
                        candidate = None
                    if candidate is None:
                        break
                    # Stop waiting if another process has legitimately reused
                    # the port. Never kill it merely because the port matches.
                    if not _network_helper_pid_matches_state(candidate, state):
                        break
                    time.sleep(0.05)

                # Final exact-port fallback, still guarded by the per-launch
                # helper identity token so a reused port/PID can never be killed.
                try:
                    final_pid = _listener_pid_for_port(int(state_port))
                except Exception:
                    final_pid = None
                if final_pid and _network_helper_pid_matches_state(final_pid, state):
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", str(int(final_pid)), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                    except Exception:
                        pass
        elif proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass

        if proc is not None:
            try:
                wait = getattr(proc, "wait", None)
                if callable(wait):
                    wait(timeout=1)
            except Exception:
                pass

        if state_port:
            revoke_loopback_port(state_port)

    if _NETWORK_ENGINE_LOG_HANDLE is not None:
        try:
            _NETWORK_ENGINE_LOG_HANDLE.close()
        except Exception:
            pass
        _NETWORK_ENGINE_LOG_HANDLE = None

atexit.register(_stop_network_engine)
atexit.register(stop_udp_peer_monitor)


def _ensure_network_engine_locked():
    """Start/reuse the loopback proxy while holding _NETWORK_ENGINE_LOCK."""
    global _NETWORK_ENGINE, _NETWORK_OPENER, _NETWORK_ENGINE_LOG_HANDLE
    preferred_port = None
    recovering = False
    if _NETWORK_ENGINE:
        proc = _NETWORK_ENGINE.get("process")
        if proc is not None and proc.poll() is None:
            return _NETWORK_ENGINE
        # Chromium keeps the proxy URL it received at process launch. If the
        # local proxy crashes, restart it on the exact same port so open tabs
        # recover without forcing a Chromium/browser restart.
        preferred_port = _NETWORK_ENGINE.get("port")
        recovering = preferred_port is not None
        _NETWORK_ENGINE = None
        _NETWORK_OPENER = None
        if _NETWORK_ENGINE_LOG_HANDLE is not None:
            try:
                _NETWORK_ENGINE_LOG_HANDLE.close()
            except Exception:
                pass
            _NETWORK_ENGINE_LOG_HANDLE = None

    host = "127.0.0.1"
    try:
        port = int(preferred_port) if preferred_port is not None else _free_loopback_port()
    except (TypeError, ValueError):
        port = _free_loopback_port()
    # Python may connect to loopback only for explicitly registered Tekzite
    # services. Register the proxy destination before the readiness probe.
    allow_loopback_port(port, "Tekzite Network proxy (HTTP/HTTPS filtering and ad blocking)", owner="tekzite-network")
    root = _network_engine_root()
    exe = root / ("tekzite-network.exe" if os.name == "nt" else "tekzite-network")
    script = root / "tekzite_network.py"
    instance_token = secrets.token_hex(16)
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
    command += ["--instance-token", instance_token]
    command += ["--log-level", log_level]
    command += ["--privacy-stats", str(state_dir / "privacy-stats.json")]
    adblock_enabled = str(os.environ.get("TEKZITE_ADBLOCK_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
    tracker_blocking = str(os.environ.get("TEKZITE_TRACKER_BLOCKING", "1")).strip().lower() not in {"0", "false", "no", "off"}
    https_first = str(os.environ.get("TEKZITE_HTTPS_FIRST", "1")).strip().lower() not in {"0", "false", "no", "off"}
    # Retain proxy protection until the optional extension confirms its rules.
    _set_adblock_fallback(adblock_enabled)
    command += ["--adblock-policy", str(state_dir / "adblock-policy.json")]
    if not adblock_enabled:
        command.append("--disable-adblock")
    if not tracker_blocking:
        command.append("--disable-tracker-blocking")
    if not https_first:
        command.append("--disable-https-first")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=(os.name != "nt"),
    )
    try:
        _wait_tcp_port(host, port, proc)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        revoke_loopback_port(port)
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
        "instance_token": instance_token,
        "log_path": str(log_path),
        "recovered_same_port": bool(recovering),
    }
    return _NETWORK_ENGINE


def ensure_network_engine():
    """Thread-safe network-engine bootstrap and same-port crash recovery."""
    with _NETWORK_ENGINE_LOCK:
        return _ensure_network_engine_locked()


def network_engine_debug(start=True):
    """Return network-helper state; optionally avoid starting it for diagnostics UI."""
    state = ensure_network_engine() if start else (_NETWORK_ENGINE or {})
    proc = state.get("process") if state else None
    return {
        "mode": state.get("mode") if state else None,
        "pid": getattr(proc, "pid", None),
        "alive": bool(proc is not None and proc.poll() is None),
        "proxy": state.get("proxy_url") if state else None,
        "log_path": state.get("log_path") if state else None,
        "loopback_policy": loopback_policy_snapshot(),
    }


def privacy_stats():
    """Return aggregate counters for the currently running helper only."""
    state = _NETWORK_ENGINE or {}
    proc = state.get("process") if state else None
    if proc is None or proc.poll() is not None:
        return {"telemetry_blocked": 0, "trackers_blocked": 0, "ads_blocked": 0, "https_upgrades": 0, "started_at": None}
    path = _network_engine_state_dir() / "privacy-stats.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "telemetry_blocked": int(data.get("telemetry_blocked", 0) or 0),
                "trackers_blocked": int(data.get("trackers_blocked", 0) or 0),
                "ads_blocked": int(data.get("ads_blocked", 0) or 0),
                "https_upgrades": int(data.get("https_upgrades", 0) or 0),
                "started_at": data.get("started_at"),
            }
    except Exception:
        pass
    return {"telemetry_blocked": 0, "trackers_blocked": 0, "ads_blocked": 0, "https_upgrades": 0, "started_at": None}


def connection_overview(start=False, timeout=0.25):
    """Return the current helper session's RAM-only destination ledger."""
    state = ensure_network_engine() if start else (_NETWORK_ENGINE or {})
    proc = state.get("process") if state else None
    if proc is None or proc.poll() is not None:
        return {"started_at": None, "updated_at": None, "connections": []}
    host = str(state.get("host") or "127.0.0.1")
    port = int(state.get("port") or 0)
    token = str(state.get("instance_token") or "")
    if not port or not token:
        return {"started_at": None, "updated_at": None, "connections": []}
    request = (
        "GET http://tekzite.internal/__connections HTTP/1.1\r\n"
        "Host: tekzite.internal\r\n"
        f"X-Tekzite-Instance-Token: {token}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        with socket.create_connection((host, port), timeout=max(0.05, float(timeout))) as sock:
            sock.settimeout(max(0.05, float(timeout)))
            sock.sendall(request)
            chunks = []
            total = 0
            while total < 1024 * 1024:
                chunk = sock.recv(min(65536, 1024 * 1024 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        raw = b"".join(chunks)
        head, body = raw.split(b"\r\n\r\n", 1)
        if not head.startswith(b"HTTP/1.1 200"):
            raise ValueError("connection overview endpoint unavailable")
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return {"started_at": None, "updated_at": None, "connections": []}
    if not isinstance(data, dict):
        return {"started_at": None, "updated_at": None, "connections": []}
    rows = []
    for item in list(data.get("connections") or [])[:512]:
        if not isinstance(item, dict):
            continue
        host_name = str(item.get("host") or "")[:253]
        if not host_name:
            continue
        rows.append({
            "host": host_name,
            "port": int(item.get("port", 0) or 0),
            "protocol": str(item.get("protocol") or "TCP")[:16],
            "status": str(item.get("status") or "unknown")[:32],
            "count": max(0, int(item.get("count", 0) or 0)),
            "active": max(0, int(item.get("active", 0) or 0)),
            "first_seen": float(item.get("first_seen", 0) or 0),
            "last_seen": float(item.get("last_seen", 0) or 0),
        })
    upstreams = []
    for item in list(data.get("active_upstreams") or [])[:512]:
        if not isinstance(item, dict):
            continue
        host_name = str(item.get("host") or "")[:253]
        local_address = str(item.get("local_address") or "")[:128]
        remote_address = str(item.get("remote_address") or "")[:128]
        try:
            local_port = int(item.get("local_port", 0) or 0)
            remote_port = int(item.get("remote_port", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not host_name or not local_port or not remote_port:
            continue
        upstreams.append({
            "host": host_name,
            "protocol": str(item.get("protocol") or "TCP")[:16],
            "local_address": local_address,
            "local_port": local_port,
            "remote_address": remote_address,
            "remote_port": remote_port,
            "opened_at": float(item.get("opened_at", 0) or 0),
        })
    return {
        "started_at": data.get("started_at"),
        "updated_at": data.get("updated_at"),
        "connections": rows,
        "active_upstreams": upstreams,
    }



_TCP_STATE_NAMES = {
    1: "CLOSED", 2: "LISTEN", 3: "SYN-SENT", 4: "SYN-RECEIVED",
    5: "ESTABLISHED", 6: "FIN-WAIT-1", 7: "FIN-WAIT-2",
    8: "CLOSE-WAIT", 9: "CLOSING", 10: "LAST-ACK", 11: "TIME-WAIT",
    12: "DELETE-TCB",
}


def _normalize_socket_address(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    raw = value.split("%", 1)[0]
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError:
        return raw


def _windows_process_snapshot():
    """Return {pid: {ppid, exe}} from Toolhelp without third-party modules."""
    if os.name != "nt":
        return {}
    try:
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = _ctypes.c_void_p(-1).value
        MAX_PATH = 260

        class PROCESSENTRY32W(_ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", _ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * MAX_PATH),
            ]

        kernel32 = _ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, _ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, _ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not handle or int(handle) == int(INVALID_HANDLE_VALUE):
            return {}
        rows = {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = _ctypes.sizeof(PROCESSENTRY32W)
            ok = bool(kernel32.Process32FirstW(handle, _ctypes.byref(entry)))
            while ok:
                pid = int(entry.th32ProcessID)
                if pid > 0:
                    rows[pid] = {
                        "pid": pid,
                        "ppid": int(entry.th32ParentProcessID),
                        "exe": str(entry.szExeFile or "")[:260],
                    }
                ok = bool(kernel32.Process32NextW(handle, _ctypes.byref(entry)))
        finally:
            kernel32.CloseHandle(handle)
        return rows
    except Exception:
        return {}


_LINUX_TCP_STATE_NAMES = {
    "01": "ESTABLISHED", "02": "SYN-SENT", "03": "SYN-RECEIVED",
    "04": "FIN-WAIT-1", "05": "FIN-WAIT-2", "06": "TIME-WAIT",
    "07": "CLOSED", "08": "CLOSE-WAIT", "09": "LAST-ACK",
    "0A": "LISTEN", "0B": "CLOSING", "0C": "SYN-RECEIVED",
}


def _linux_process_snapshot(proc_root="/proc"):
    """Return {pid: {ppid, exe}} using procfs without third-party process modules/root access."""
    if not sys.platform.startswith("linux"):
        return {}
    root = Path(proc_root)
    rows = {}
    try:
        entries = list(root.iterdir())
    except Exception:
        return rows
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            end = stat.rfind(")")
            if end < 0:
                continue
            tail = stat[end + 2:].split()
            # After the closing parenthesis: state, ppid, pgrp, ...
            ppid = int(tail[1]) if len(tail) > 1 else 0
            exe = ""
            try:
                exe = os.path.basename(os.readlink(entry / "exe"))
            except Exception:
                try:
                    exe = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
                except Exception:
                    exe = ""
            rows[pid] = {"pid": pid, "ppid": ppid, "exe": str(exe or "")[:260]}
        except Exception:
            continue
    return rows


def _linux_owned_processes(processes=None, extra_roots=None):
    """Return Tekzite plus the complete live descendant closure from procfs."""
    processes = dict(processes if processes is not None else _linux_process_snapshot())
    roots = {int(os.getpid())}
    for state in (_NETWORK_ENGINE or {}, _EDGE_SESSION or {}):
        proc = state.get("process") if isinstance(state, dict) else None
        try:
            pid = int(getattr(proc, "pid", 0) or 0)
        except Exception:
            pid = 0
        if pid > 0:
            roots.add(pid)
    for value in list(extra_roots or []):
        try:
            pid = int(value or 0)
        except Exception:
            pid = 0
        if pid > 0:
            roots.add(pid)
    owned = set(roots)
    for _ in range(max(2, len(processes) + 1)):
        before = len(owned)
        for pid, item in processes.items():
            try:
                if int(item.get("ppid") or 0) in owned:
                    owned.add(int(pid))
            except Exception:
                continue
        if len(owned) == before:
            break
    return owned, processes


def _linux_proc_address(value, family):
    """Decode one /proc/net IPv4/IPv6 hexadecimal address."""
    try:
        raw = bytes.fromhex(str(value or ""))
        if family == "IPv4":
            if len(raw) != 4:
                return ""
            return socket.inet_ntop(socket.AF_INET, raw[::-1])
        if len(raw) != 16:
            return ""
        # procfs prints IPv6 as four little-endian 32-bit words.
        native = b"".join(raw[index:index + 4][::-1] for index in range(0, 16, 4))
        return socket.inet_ntop(socket.AF_INET6, native)
    except Exception:
        return ""


def _linux_proc_endpoint(token, family):
    try:
        address_hex, port_hex = str(token).split(":", 1)
        return _linux_proc_address(address_hex, family), int(port_hex, 16)
    except Exception:
        return "", 0


def _linux_socket_inode_owners(owned_pids, proc_root="/proc"):
    """Map socket inode -> owning Tekzite PID(s) by scanning only owned /proc FDs."""
    root = Path(proc_root)
    result = {}
    for pid in set(int(value) for value in (owned_pids or []) if int(value or 0) > 0):
        fd_dir = root / str(pid) / "fd"
        try:
            entries = list(fd_dir.iterdir())
        except Exception:
            continue
        for fd in entries:
            try:
                target = os.readlink(fd)
            except Exception:
                continue
            if not target.startswith("socket:[") or not target.endswith("]"):
                continue
            inode = target[8:-1]
            if inode:
                result.setdefault(inode, set()).add(pid)
    return result


def _linux_socket_rows(owned_pids=None, proc_root="/proc"):
    """Enumerate current Linux TCP/UDP sockets from procfs with PID ownership.

    This is intentionally dependency-free and requires no elevated privileges
    for Tekzite's own processes. Unlike the Windows ETW layer it is a snapshot,
    so very short-lived flows can still fall between refreshes in Linux Preview.
    """
    if not sys.platform.startswith("linux"):
        return []
    owned = set(int(value) for value in (owned_pids or []) if int(value or 0) > 0)
    inode_owners = _linux_socket_inode_owners(owned, proc_root=proc_root)
    root = Path(proc_root) / "net"
    result = []
    tables = (
        ("tcp", "TCP", "IPv4"), ("tcp6", "TCP", "IPv6"),
        ("udp", "UDP", "IPv4"), ("udp6", "UDP", "IPv6"),
    )
    for filename, protocol, family in tables:
        try:
            lines = (root / filename).read_text(encoding="ascii", errors="replace").splitlines()[1:]
        except Exception:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10:
                continue
            inode = parts[9]
            pids = inode_owners.get(inode)
            if not pids:
                continue
            local_address, local_port = _linux_proc_endpoint(parts[1], family)
            remote_address, remote_port = _linux_proc_endpoint(parts[2], family)
            state_code = str(parts[3]).upper()
            if protocol == "TCP":
                state = _LINUX_TCP_STATE_NAMES.get(state_code, state_code)
            else:
                try:
                    rip = ipaddress.ip_address(remote_address)
                    remote_empty = rip.is_unspecified and int(remote_port or 0) == 0
                except Exception:
                    remote_empty = not remote_address or int(remote_port or 0) == 0
                state = "ENDPOINT" if remote_empty else "CONNECTED"
                if remote_empty:
                    remote_address, remote_port = "", 0
            for pid in sorted(pids):
                result.append({
                    "pid": int(pid), "protocol": protocol, "family": family,
                    "local_address": local_address, "local_port": int(local_port),
                    "remote_address": remote_address, "remote_port": int(remote_port),
                    "state": state,
                })
    return result


def _platform_process_snapshot():
    if os.name == "nt":
        return _windows_process_snapshot()
    if sys.platform.startswith("linux"):
        return _linux_process_snapshot()
    return {}


def _platform_owned_processes(processes=None, extra_roots=None):
    if os.name == "nt":
        return _windows_owned_processes(processes, extra_roots=extra_roots)
    if sys.platform.startswith("linux"):
        return _linux_owned_processes(processes, extra_roots=extra_roots)
    return {int(os.getpid())}, dict(processes or {})


def _platform_socket_rows(owned_pids=None):
    if os.name == "nt":
        return _windows_socket_rows()
    if sys.platform.startswith("linux"):
        return _linux_socket_rows(owned_pids)
    return []


def _windows_owned_processes(processes=None, extra_roots=None):
    """Return Tekzite itself plus every live descendant visible to Toolhelp."""
    processes = dict(processes if processes is not None else _windows_process_snapshot())
    own_pid = int(os.getpid())
    roots = {own_pid}

    for state in (_NETWORK_ENGINE or {}, _EDGE_SESSION or {}):
        proc = state.get("process") if isinstance(state, dict) else None
        try:
            pid = int(getattr(proc, "pid", 0) or 0)
        except Exception:
            pid = 0
        if pid > 0:
            roots.add(pid)

    for value in list(extra_roots or []):
        try:
            pid = int(value or 0)
        except Exception:
            pid = 0
        if pid > 0:
            roots.add(pid)

    owned = set(roots)
    # Chromium's browser process can spawn several generations of renderer,
    # utility, GPU and crash-handler children. Resolve the complete descendant
    # closure rather than matching executable names globally.
    for _ in range(max(2, len(processes) + 1)):
        before = len(owned)
        for pid, item in processes.items():
            try:
                if int(item.get("ppid") or 0) in owned:
                    owned.add(int(pid))
            except Exception:
                continue
        if len(owned) == before:
            break
    return owned, processes


def _win_port(value) -> int:
    try:
        return int(socket.ntohs(int(value) & 0xFFFF))
    except Exception:
        return 0


def _win_ipv4(value) -> str:
    try:
        packed = int(value).to_bytes(4, byteorder="little", signed=False)
        return socket.inet_ntop(socket.AF_INET, packed)
    except Exception:
        return ""


def _win_ipv6(value, scope_id=0) -> str:
    try:
        packed = bytes(value)
        address = socket.inet_ntop(socket.AF_INET6, packed)
        if int(scope_id or 0) and address.lower().startswith("fe80:"):
            return f"{address}%{int(scope_id)}"
        return address
    except Exception:
        return ""


def _windows_socket_rows():
    """Enumerate Windows owner-PID TCP/UDP tables for IPv4 and IPv6.

    TCP rows include both endpoints and state. The Windows UDP owner table itself
    exposes only the local endpoint; live_socket_snapshot augments those rows
    with Kernel-Network ETW peer events when the Live Socket View is active.
    """
    if os.name != "nt":
        return []
    try:
        from ctypes import wintypes

        class MIB_TCPROW_OWNER_PID(_ctypes.Structure):
            _fields_ = [
                ("dwState", wintypes.DWORD), ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD), ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD), ("dwOwningPid", wintypes.DWORD),
            ]

        class MIB_TCP6ROW_OWNER_PID(_ctypes.Structure):
            _fields_ = [
                ("ucLocalAddr", _ctypes.c_ubyte * 16), ("dwLocalScopeId", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD), ("ucRemoteAddr", _ctypes.c_ubyte * 16),
                ("dwRemoteScopeId", wintypes.DWORD), ("dwRemotePort", wintypes.DWORD),
                ("dwState", wintypes.DWORD), ("dwOwningPid", wintypes.DWORD),
            ]

        class MIB_UDPROW_OWNER_PID(_ctypes.Structure):
            _fields_ = [
                ("dwLocalAddr", wintypes.DWORD), ("dwLocalPort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]

        class MIB_UDP6ROW_OWNER_PID(_ctypes.Structure):
            _fields_ = [
                ("ucLocalAddr", _ctypes.c_ubyte * 16), ("dwLocalScopeId", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD), ("dwOwningPid", wintypes.DWORD),
            ]

        iphlpapi = _ctypes.WinDLL("iphlpapi", use_last_error=True)
        ERROR_INSUFFICIENT_BUFFER = 122
        TCP_TABLE_OWNER_PID_ALL = 5
        UDP_TABLE_OWNER_PID = 1

        def table_rows(func_name, family, table_class, row_type):
            func = getattr(iphlpapi, func_name)
            func.argtypes = [
                _ctypes.c_void_p, _ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
            ]
            func.restype = wintypes.DWORD
            size = wintypes.DWORD(0)
            result = int(func(None, _ctypes.byref(size), False, family, table_class, 0))
            if result not in (0, ERROR_INSUFFICIENT_BUFFER) or size.value < 4:
                return []
            buf = _ctypes.create_string_buffer(int(size.value))
            result = int(func(buf, _ctypes.byref(size), False, family, table_class, 0))
            if result != 0:
                return []
            count = int(wintypes.DWORD.from_buffer_copy(buf.raw[:4]).value)
            row_size = _ctypes.sizeof(row_type)
            rows = []
            offset = 4
            for _ in range(count):
                if offset + row_size > len(buf.raw):
                    break
                rows.append(row_type.from_buffer_copy(buf.raw[offset:offset + row_size]))
                offset += row_size
            return rows

        result = []
        for row in table_rows("GetExtendedTcpTable", socket.AF_INET, TCP_TABLE_OWNER_PID_ALL, MIB_TCPROW_OWNER_PID):
            result.append({
                "pid": int(row.dwOwningPid), "protocol": "TCP", "family": "IPv4",
                "local_address": _win_ipv4(row.dwLocalAddr), "local_port": _win_port(row.dwLocalPort),
                "remote_address": _win_ipv4(row.dwRemoteAddr), "remote_port": _win_port(row.dwRemotePort),
                "state": _TCP_STATE_NAMES.get(int(row.dwState), str(int(row.dwState))),
            })
        for row in table_rows("GetExtendedTcpTable", socket.AF_INET6, TCP_TABLE_OWNER_PID_ALL, MIB_TCP6ROW_OWNER_PID):
            result.append({
                "pid": int(row.dwOwningPid), "protocol": "TCP", "family": "IPv6",
                "local_address": _win_ipv6(row.ucLocalAddr, row.dwLocalScopeId), "local_port": _win_port(row.dwLocalPort),
                "remote_address": _win_ipv6(row.ucRemoteAddr, row.dwRemoteScopeId), "remote_port": _win_port(row.dwRemotePort),
                "state": _TCP_STATE_NAMES.get(int(row.dwState), str(int(row.dwState))),
            })
        for row in table_rows("GetExtendedUdpTable", socket.AF_INET, UDP_TABLE_OWNER_PID, MIB_UDPROW_OWNER_PID):
            result.append({
                "pid": int(row.dwOwningPid), "protocol": "UDP", "family": "IPv4",
                "local_address": _win_ipv4(row.dwLocalAddr), "local_port": _win_port(row.dwLocalPort),
                "remote_address": "", "remote_port": 0, "state": "ENDPOINT",
            })
        for row in table_rows("GetExtendedUdpTable", socket.AF_INET6, UDP_TABLE_OWNER_PID, MIB_UDP6ROW_OWNER_PID):
            result.append({
                "pid": int(row.dwOwningPid), "protocol": "UDP", "family": "IPv6",
                "local_address": _win_ipv6(row.ucLocalAddr, row.dwLocalScopeId), "local_port": _win_port(row.dwLocalPort),
                "remote_address": "", "remote_port": 0, "state": "ENDPOINT",
            })
        return result
    except Exception:
        return []


def _descendant_pid_set(root_pid, processes):
    """Return one root PID plus descendants from an existing process snapshot."""
    try:
        root_pid = int(root_pid or 0)
    except Exception:
        root_pid = 0
    if not root_pid:
        return set()
    owned = {root_pid}
    processes = processes or {}
    for _ in range(max(2, len(processes) + 1)):
        before = len(owned)
        for pid, item in processes.items():
            try:
                if int(item.get("ppid") or 0) in owned:
                    owned.add(int(pid))
            except Exception:
                continue
        if len(owned) == before:
            break
    return owned


def _pid_matches(pid, values):
    try:
        pid = int(pid or 0)
    except Exception:
        return False
    if isinstance(values, (set, frozenset, list, tuple)):
        try:
            return pid in {int(value) for value in values if int(value or 0) > 0}
        except Exception:
            return False
    try:
        return bool(values) and pid == int(values)
    except Exception:
        return False


def _socket_role(pid: int, exe: str, network_pid=0, chromium_pid=0, *, network_pids=None, chromium_pids=None) -> str:
    pid = int(pid or 0)
    lower = str(exe or "").casefold()
    if pid == int(os.getpid()):
        return "Tekzite UI"
    if _pid_matches(pid, network_pids if network_pids is not None else network_pid):
        return "Tekzite Network"
    if "chrom" in lower or _pid_matches(pid, chromium_pids if chromium_pids is not None else chromium_pid):
        return "Chromium"
    if exe:
        return "Tekzite child"
    return "Tekzite process"


def _socket_path_label(row, *, network_pid=0, network_pids=None, proxy_port=0, devtools_port=0):
    state = str(row.get("state") or "")
    protocol = str(row.get("protocol") or "")
    remote = _normalize_socket_address(row.get("remote_address"))
    remote_port = int(row.get("remote_port") or 0)
    pid = int(row.get("pid") or 0)
    if state == "LISTEN":
        return "Listener"
    if protocol == "UDP" and not remote:
        return "UDP endpoint"
    try:
        ip = ipaddress.ip_address(remote) if remote else None
    except ValueError:
        ip = None
    if ip is not None and ip.is_loopback:
        if proxy_port and remote_port == int(proxy_port):
            return "Via Tekzite Network"
        if devtools_port and remote_port == int(devtools_port):
            return "Chromium DevTools"
        return "Loopback internal"
    if remote:
        if _pid_matches(pid, network_pids if network_pids is not None else network_pid):
            return "Tekzite Network upstream" if protocol != "UDP" else "Tekzite Network UDP"
        return "Direct UDP external" if protocol == "UDP" else "Direct external"
    return "Local endpoint"


def _udp_peer_candidates(peer_rows, item):
    """Return recent ETW peers matching one Windows UDP owner-table row."""
    pid = int(item.get("pid") or 0)
    family = str(item.get("family") or "")
    local_port = int(item.get("local_port") or 0)
    local_address = _normalize_socket_address(item.get("local_address"))
    try:
        bound_ip = ipaddress.ip_address(local_address) if local_address else None
    except ValueError:
        bound_ip = None
    unspecified = bound_ip is None or bound_ip.is_unspecified
    matches = []
    for peer in list(peer_rows or []):
        if int(peer.get("pid") or 0) != pid:
            continue
        if str(peer.get("family") or "") != family:
            continue
        if int(peer.get("local_port") or 0) != local_port:
            continue
        peer_local = _normalize_socket_address(peer.get("local_address"))
        if not unspecified and peer_local and peer_local != local_address:
            continue
        matches.append(peer)
    matches.sort(key=lambda row: float(row.get("last_seen", 0.0)), reverse=True)
    return matches


def _record_internal_network_activity(url, *, purpose, resource=""):
    """Remember one Tekzite-owned outbound intent without retaining its URL."""
    try:
        parts = urlsplit(str(url or ""))
        host = str(parts.hostname or "").strip().rstrip(".").lower()[:253]
    except Exception:
        host = ""
    if not host:
        return
    now = time.time()
    item = {
        "host": host,
        "purpose": str(purpose or "Tekzite internal request")[:160],
        "resource": str(resource or "")[:80],
        "seen_at": now,
    }
    with _INTERNAL_NETWORK_ACTIVITY_LOCK:
        cutoff = now - _INTERNAL_NETWORK_ACTIVITY_MAX_AGE
        _INTERNAL_NETWORK_ACTIVITY[:] = [
            row for row in _INTERNAL_NETWORK_ACTIVITY
            if float(row.get("seen_at") or 0.0) >= cutoff
        ]
        _INTERNAL_NETWORK_ACTIVITY.append(item)
        if len(_INTERNAL_NETWORK_ACTIVITY) > _INTERNAL_NETWORK_ACTIVITY_MAX_RECORDS:
            del _INTERNAL_NETWORK_ACTIVITY[:-_INTERNAL_NETWORK_ACTIVITY_MAX_RECORDS]


def _match_internal_network_activity(host, *, around=0.0):
    """Return recent Tekzite-owned activity for one exact destination host."""
    host = str(host or "").strip().rstrip(".").lower()
    if not host:
        return None
    now = time.time()
    cutoff = now - _INTERNAL_NETWORK_ACTIVITY_MAX_AGE
    try:
        around = float(around or 0.0)
    except Exception:
        around = 0.0
    with _INTERNAL_NETWORK_ACTIVITY_LOCK:
        _INTERNAL_NETWORK_ACTIVITY[:] = [
            row for row in _INTERNAL_NETWORK_ACTIVITY
            if float(row.get("seen_at") or 0.0) >= cutoff
        ]
        matches = [row for row in _INTERNAL_NETWORK_ACTIVITY if row.get("host") == host]
    if not matches:
        return None
    if around > 0:
        matches.sort(key=lambda row: abs(float(row.get("seen_at") or 0.0) - around))
        candidate = matches[0]
        if abs(float(candidate.get("seen_at") or 0.0) - around) <= 5.0:
            return dict(candidate)
    return dict(max(matches, key=lambda row: float(row.get("seen_at") or 0.0)))


def live_socket_snapshot(*, include_proxy_names=True, extra_pids=None):
    """Return current sockets owned by Tekzite and its descendant processes.

    Windows uses owner-PID tables plus optional Kernel-Network ETW enrichment.
    Linux Preview uses procfs socket tables and inode-to-PID ownership mapping,
    which requires no third-party module or elevated privileges for Tekzite's
    own processes. CDP/proxy attribution is shared across both platforms.
    """
    if os.name != "nt" and not sys.platform.startswith("linux"):
        return {
            "supported": False, "captured_at": time.time(), "sockets": [],
            "reason": "Live socket ownership is currently supported on Windows and Linux.",
        }

    processes = _platform_process_snapshot()
    owned, processes = _platform_owned_processes(processes, extra_roots=extra_pids)
    if os.name == "nt":
        # Start/update the ETW peer filter before reading the owner table. The first
        # snapshot can legitimately have no peers yet; subsequent event callbacks
        # populate the RAM ledger without waiting for another packet-table API.
        udp_peer_state = ensure_udp_peer_monitor(owned)
        peer_rows = list((udp_peer_state or {}).get("peers") or [])
        tcp_event_rows = list((udp_peer_state or {}).get("tcp_flows") or [])
    else:
        udp_peer_state = {
            "status": "snapshot-only",
            "reason": "Linux Preview reads current TCP/UDP ownership from procfs; event-level eBPF enrichment is not enabled yet.",
            "peers": [], "tcp_flows": [],
        }
        peer_rows = []
        tcp_event_rows = []

    network_state = _NETWORK_ENGINE or {}
    edge_state = _EDGE_SESSION or {}
    network_proc = network_state.get("process") if isinstance(network_state, dict) else None
    chromium_proc = edge_state.get("process") if isinstance(edge_state, dict) else None
    try:
        network_pid = int(getattr(network_proc, "pid", 0) or 0)
    except Exception:
        network_pid = 0
    try:
        chromium_pid = int(getattr(chromium_proc, "pid", 0) or 0)
    except Exception:
        chromium_pid = 0
    proxy_port = int(network_state.get("port") or 0) if isinstance(network_state, dict) else 0
    devtools_port = int(edge_state.get("port") or 0) if isinstance(edge_state, dict) else 0

    # PyInstaller one-file executables may keep the launcher PID while the real
    # helper payload runs in a child process. Treat the full helper/browser
    # descendant trees as authoritative so upstream sockets cannot be mislabeled
    # as direct Chromium/Tekzite traffic.
    network_pids = _descendant_pid_set(network_pid, processes)
    chromium_pids = _descendant_pid_set(chromium_pid, processes)

    proxy_snapshot = connection_overview(start=False, timeout=0.12) if include_proxy_names else {}
    upstream_names = {}
    upstream_details = {}
    proxy_clients = {}
    for item in list((proxy_snapshot or {}).get("active_upstreams") or []):
        key = (
            _normalize_socket_address(item.get("local_address")), int(item.get("local_port") or 0),
            _normalize_socket_address(item.get("remote_address")), int(item.get("remote_port") or 0),
        )
        upstream_names[key] = str(item.get("host") or "")[:253]
        upstream_details[key] = dict(item)
        client_address = _normalize_socket_address(item.get("client_address"))
        client_port = int(item.get("client_port") or 0)
        proxy_address = _normalize_socket_address(item.get("proxy_address"))
        proxy_client_port = int(item.get("proxy_port") or proxy_port or 0)
        if client_address and client_port and proxy_client_port:
            proxy_clients[(client_address, client_port, proxy_address or "127.0.0.1", proxy_client_port)] = str(item.get("host") or "")[:253]

    request_audit = ensure_network_request_audit_monitor(devtools_port) if devtools_port else {
        "status": "idle", "reason": "Chromium DevTools is not active.", "hosts": [], "endpoints": []
    }
    request_hosts = {str(item.get("host") or "").lower(): item for item in list((request_audit or {}).get("hosts") or []) if item.get("host")}
    request_rows = list((request_audit or {}).get("requests") or [])
    audit_started_at = float((request_audit or {}).get("started_at") or 0.0)
    request_endpoints = {
        (_normalize_socket_address(item.get("remote_address")), int(item.get("remote_port") or 0)): item
        for item in list((request_audit or {}).get("endpoints") or [])
        if _normalize_socket_address(item.get("remote_address")) and int(item.get("remote_port") or 0)
    }

    def request_for_socket(destination_host, remote_address, remote_port, opened_at=0.0):
        """Find the most defensible CDP request for one network socket.

        If the socket opened after the CDP audit started and a same-host request
        lands within a small timestamp window, that request is a likely opener.
        Otherwise endpoint/host matches are labeled as activity only; they are
        never presented as causal certainty.
        """
        destination_host = str(destination_host or "").strip().rstrip(".").lower()
        remote_address = _normalize_socket_address(remote_address)
        try:
            remote_port = int(remote_port or 0)
        except Exception:
            remote_port = 0
        try:
            opened_at = float(opened_at or 0.0)
        except Exception:
            opened_at = 0.0
        candidates = []
        for req in request_rows:
            host = str(req.get("host") or "").strip().rstrip(".").lower()
            endpoint_match = bool(
                remote_address and remote_port
                and _normalize_socket_address(req.get("remote_address")) == remote_address
                and int(req.get("remote_port") or 0) == remote_port
            )
            host_match = bool(destination_host and host == destination_host)
            if destination_host:
                # A CDN IP can serve unrelated hostnames. Once Tekzite Network
                # gives us the requested hostname, never let an IP:port-only
                # match from another hostname outrank it.
                if not host_match:
                    continue
            elif not endpoint_match:
                continue
            seen = float(req.get("first_seen") or 0.0)
            delta = abs(seen - opened_at) if opened_at and seen else 999999.0
            reused = req.get("connection_reused")
            reuse_rank = 0 if reused is False else 1 if reused is None else 2
            candidates.append((reuse_rank, 0 if endpoint_match else 1, delta, -seen, req, endpoint_match, host_match))
        if not candidates:
            return None, ""
        candidates.sort(key=lambda item: item[:4])
        _reuse_rank, _endpoint_rank, delta, _neg_seen, req, endpoint_match, host_match = candidates[0]
        monitor_covered_open = bool(opened_at and audit_started_at and opened_at >= audit_started_at - 0.20)
        reused = req.get("connection_reused")
        if monitor_covered_open and delta <= 2.5:
            if reused is False and destination_host and host_match:
                return req, "Strong opener"
            if reused is False and endpoint_match:
                return req, "Probable opener"
            if reused is None and destination_host and host_match:
                return req, "Likely opener"
            if reused is None and endpoint_match:
                return req, "Probable opener"
        if reused is True:
            return req, "Reused connection"
        if endpoint_match:
            return req, "Endpoint activity"
        return req, "Host activity"

    def decorate(item, peer=None):
        pid = int(item.get("pid") or 0)
        process_info = processes.get(pid, {})
        exe = str(process_info.get("exe") or "")
        row = dict(item)
        if peer is not None:
            row["remote_address"] = _normalize_socket_address(peer.get("remote_address"))
            row["remote_port"] = int(peer.get("remote_port") or 0)
            row["state"] = "PEER"
            row["last_seen"] = float(peer.get("last_seen", 0.0) or 0.0)
            row["first_seen"] = float(peer.get("first_seen", 0.0) or 0.0)
            row["tx_packets"] = int(peer.get("tx_packets", 0) or 0)
            row["rx_packets"] = int(peer.get("rx_packets", 0) or 0)
            row["tx_bytes"] = int(peer.get("tx_bytes", 0) or 0)
            row["rx_bytes"] = int(peer.get("rx_bytes", 0) or 0)
            # If the owner table is bound to 0.0.0.0/::, show the concrete local
            # address used for this datagram peer in the event-enriched row.
            try:
                base_ip = ipaddress.ip_address(_normalize_socket_address(row.get("local_address")))
            except ValueError:
                base_ip = None
            if base_ip is None or base_ip.is_unspecified:
                concrete = _normalize_socket_address(peer.get("local_address"))
                if concrete:
                    row["local_address"] = concrete
        row["process"] = exe or (("TekziteBrowser.exe" if os.name == "nt" else "TekziteBrowser") if pid == int(os.getpid()) else "")
        row["role"] = _socket_role(
            pid, exe, network_pid, chromium_pid,
            network_pids=network_pids, chromium_pids=chromium_pids,
        )
        row["path"] = _socket_path_label(
            row, network_pid=network_pid, network_pids=network_pids,
            proxy_port=proxy_port, devtools_port=devtools_port,
        )
        local_address = _normalize_socket_address(row.get("local_address"))
        remote_address = _normalize_socket_address(row.get("remote_address"))
        row["local_address"] = local_address
        row["remote_address"] = remote_address
        host = ""
        upstream_detail = None
        if _pid_matches(pid, network_pids) and remote_address:
            upstream_key = (
                local_address, int(row.get("local_port") or 0),
                remote_address, int(row.get("remote_port") or 0),
            )
            host = upstream_names.get(upstream_key, "")
            upstream_detail = upstream_details.get(upstream_key)
            if upstream_detail is not None:
                row["socket_opened_at"] = float(upstream_detail.get("opened_at") or 0.0)
        if not host and _pid_matches(pid, chromium_pids) and remote_address:
            # A Chromium -> local proxy socket can be tied to the exact CONNECT
            # destination while the tunnel is active. The actual remote endpoint
            # is still 127.0.0.1; destination_host exposes where that tunnel goes.
            client_key = (
                local_address, int(row.get("local_port") or 0),
                remote_address, int(row.get("remote_port") or 0),
            )
            destination = proxy_clients.get(client_key, "")
            if destination:
                row["destination_host"] = destination
        if not host and remote_address:
            try:
                remote_ip = ipaddress.ip_address(remote_address)
            except ValueError:
                remote_ip = None
            if remote_ip is not None and remote_ip.is_loopback:
                if proxy_port and int(row.get("remote_port") or 0) == proxy_port:
                    host = "Tekzite Network"
                elif devtools_port and int(row.get("remote_port") or 0) == devtools_port:
                    host = "Chromium DevTools"
                else:
                    host = "localhost"
        row["hostname"] = host

        attribution = None
        exact_destination = str(row.get("destination_host") or host or "").strip().rstrip(".").lower()
        socket_request, match_quality = request_for_socket(
            exact_destination, remote_address, int(row.get("remote_port") or 0),
            row.get("socket_opened_at") or row.get("first_seen") or 0.0,
        )
        if exact_destination:
            attribution = request_hosts.get(exact_destination)
        if attribution is None and remote_address and int(row.get("remote_port") or 0):
            attribution = request_endpoints.get((remote_address, int(row.get("remote_port") or 0)))

        # Closed/recent upstreams can outlive Tekzite Network's active socket
        # map. A CDP response endpoint still gives us the requested hostname.
        if socket_request and not exact_destination and str(row.get("path") or "").startswith("Tekzite Network upstream"):
            recovered_host = str(socket_request.get("host") or "").strip().rstrip(".").lower()[:253]
            if recovered_host:
                row["destination_host"] = recovered_host
                row["hostname"] = recovered_host
                exact_destination = recovered_host
                attribution = request_hosts.get(recovered_host) or attribution

        if attribution or socket_request:
            source = socket_request or attribution or {}
            scopes = list((attribution or {}).get("scopes") or ([source.get("scope")] if source.get("scope") else []))
            resources = list((attribution or {}).get("resource_types") or ([source.get("resource_type")] if source.get("resource_type") else []))
            initiators = list((attribution or {}).get("initiators") or [])
            row["request_scope"] = " + ".join(str(v) for v in scopes[:3] if v) or str(source.get("scope") or (attribution or {}).get("latest_scope") or "")
            row["request_purpose"] = str(source.get("purpose") or (attribution or {}).get("purpose") or "")
            row["request_resource"] = ", ".join(str(v) for v in resources[:4] if v) or str(source.get("resource_type") or (attribution or {}).get("latest_resource_type") or "")
            row["request_initiator"] = str(source.get("initiator_label") or "") or (
                str(source.get("initiator_type") or "")
                + (f" @ {source.get('initiator_host')}" if source.get("initiator_host") else "")
            ) or (initiators[0] if initiators else (
                str((attribution or {}).get("latest_initiator_label") or "") or (
                    str((attribution or {}).get("latest_initiator_type") or "")
                    + (f" @ {(attribution or {}).get('latest_initiator_host')}" if (attribution or {}).get("latest_initiator_host") else "")
                )
            ))
            row["request_target_host"] = str(source.get("target_host") or (attribution or {}).get("latest_target_host") or "")
            row["request_count"] = int((attribution or {}).get("count") or (1 if socket_request else 0))
            row["request_attribution"] = "CDP"
            row["request_match_quality"] = match_quality or ("Endpoint activity" if socket_request else "Host activity")
            row["request_script"] = str(source.get("script_source") or (attribution or {}).get("latest_script_source") or "")
            row["request_script_host"] = str(source.get("script_host") or (attribution or {}).get("latest_script_host") or "")
            row["request_script_file"] = str(source.get("script_file") or (attribution or {}).get("latest_script_file") or "")
            row["request_script_function"] = str(source.get("script_function") or (attribution or {}).get("latest_script_function") or "")
            row["request_script_line"] = int(source.get("script_line") or (attribution or {}).get("latest_script_line") or 0)
            row["request_script_column"] = int(source.get("script_column") or (attribution or {}).get("latest_script_column") or 0)
            row["request_script_id"] = str(source.get("script_id") or (attribution or {}).get("latest_script_id") or "")[:128]
            row["request_target_id"] = str(source.get("target_id") or (attribution or {}).get("latest_target_id") or "")[:128]
            row["request_script_stack"] = [
                dict(frame) for frame in list(source.get("script_stack") or (attribution or {}).get("latest_script_stack") or [])[:8]
            ]
            row["request_connection_id"] = str(source.get("connection_id") or "")
            row["request_connection_reused"] = source.get("connection_reused")
            row["request_transport"] = str(source.get("response_protocol") or "")
            row["request_method"] = str(source.get("method") or (attribution or {}).get("latest_method") or "")
            row["request_domain_relation"] = str(source.get("domain_relation") or (attribution or {}).get("latest_domain_relation") or "")
            row["request_response_status"] = int(source.get("response_status") or (attribution or {}).get("latest_response_status") or 0)
            row["request_response_mime"] = str(source.get("response_mime_type") or (attribution or {}).get("latest_response_mime_type") or "")
            row["request_encoded_bytes"] = int(source.get("encoded_data_length") or (attribution or {}).get("latest_encoded_data_length") or 0)
            row["request_from_cache"] = bool(source.get("request_served_from_cache") or source.get("response_from_disk_cache") or source.get("response_from_prefetch_cache"))
            row["request_from_service_worker"] = bool(source.get("response_from_service_worker"))
            row["request_loading_failed"] = bool(source.get("loading_failed") or (attribution or {}).get("latest_loading_failed"))
            row["request_failure_text"] = str(source.get("failure_text") or "")
            row["request_blocked_reason"] = str(source.get("blocked_reason") or "")
            row["request_tls_protocol"] = str(source.get("tls_protocol") or "")
            row["request_tls_cipher"] = str(source.get("tls_cipher") or "")
            row["request_tls_issuer"] = str(source.get("tls_issuer") or "")
            row["request_security_state"] = str(source.get("security_state") or "")
            row["request_observed_cookie"] = bool(source.get("observed_cookie_header"))
            row["request_observed_authorization"] = bool(source.get("observed_authorization_header"))
            row["request_observed_origin"] = bool(source.get("observed_origin_header"))
            row["request_observed_referer"] = bool(source.get("observed_referer_header"))
            row["request_observed_set_cookie"] = bool(source.get("observed_set_cookie_header"))
            row["request_redirect_from_host"] = str(source.get("redirect_from_host") or "")
            row["request_redirect_to_host"] = str(source.get("redirect_to_host") or "")
        elif str(row.get("path") or "").startswith("Tekzite Network upstream") and exact_destination:
            internal_activity = _match_internal_network_activity(
                exact_destination, around=row.get("socket_opened_at") or row.get("first_seen") or 0.0
            )
            if internal_activity:
                row["request_scope"] = "Tekzite internal"
                row["request_purpose"] = str(internal_activity.get("purpose") or "Tekzite internal request")
                row["request_resource"] = str(internal_activity.get("resource") or "")
                row["request_initiator"] = "Tekzite Browser internal"
                row["request_script"] = ""
                row["request_script_id"] = ""
                row["request_target_id"] = ""
                row["request_script_stack"] = []
                row["request_match_quality"] = "Internal host activity"
                row["request_target_host"] = exact_destination
                row["request_count"] = 1
                row["request_attribution"] = "Tekzite"
            else:
                row["request_scope"] = "Unattributed"
                row["request_purpose"] = "No page/extension CDP request observed yet"
                row["request_resource"] = ""
                row["request_initiator"] = ""
                row["request_script"] = ""
                row["request_script_id"] = ""
                row["request_target_id"] = ""
                row["request_script_stack"] = []
                row["request_match_quality"] = "Unattributed"
                row["request_target_host"] = ""
                row["request_count"] = 0
                row["request_attribution"] = "none"

        row["key"] = "|".join([
            str(pid), str(row.get("protocol") or ""), str(row.get("family") or ""),
            local_address, str(int(row.get("local_port") or 0)), remote_address,
            str(int(row.get("remote_port") or 0)), str(row.get("state") or ""),
        ])
        return row

    rows = []
    current_tcp_keys = set()
    for item in _platform_socket_rows(owned):
        pid = int(item.get("pid") or 0)
        if pid not in owned:
            continue
        if str(item.get("protocol") or "") == "UDP":
            peers = _udp_peer_candidates(peer_rows, item)
            if peers:
                rows.extend(decorate(item, peer) for peer in peers)
                continue
        if str(item.get("protocol") or "") == "TCP":
            current_tcp_keys.add((
                pid, str(item.get("family") or ""),
                _normalize_socket_address(item.get("local_address")), int(item.get("local_port") or 0),
                _normalize_socket_address(item.get("remote_address")), int(item.get("remote_port") or 0),
            ))
        rows.append(decorate(item))

    # Event-observed TCP connects survive briefly after the Windows owner table
    # drops them. This closes the 250 ms polling blind spot without pretending a
    # recently closed flow is still established.
    for flow in tcp_event_rows:
        pid = int(flow.get("pid") or 0)
        if pid not in owned:
            continue
        key = (
            pid, str(flow.get("family") or ""),
            _normalize_socket_address(flow.get("local_address")), int(flow.get("local_port") or 0),
            _normalize_socket_address(flow.get("remote_address")), int(flow.get("remote_port") or 0),
        )
        if key in current_tcp_keys:
            continue
        item = {
            "pid": pid, "protocol": "TCP", "family": str(flow.get("family") or ""),
            "local_address": key[2], "local_port": key[3],
            "remote_address": key[4], "remote_port": key[5],
            "state": "RECENT", "first_seen": float(flow.get("first_seen") or 0.0),
            "last_seen": float(flow.get("last_seen") or 0.0),
            "event_count": int(flow.get("count") or 0),
            "event_kind": str(flow.get("event") or "connect"),
        }
        rows.append(decorate(item))

    rows.sort(key=lambda row: (
        0 if str(row.get("path") or "").startswith("Direct") else 1,
        0 if str(row.get("state")) in {"ESTABLISHED", "PEER"} else 1,
        str(row.get("role") or ""), int(row.get("pid") or 0),
        str(row.get("protocol") or ""), int(row.get("local_port") or 0),
        -float(row.get("last_seen", 0.0) or 0.0),
    ))
    return {
        "supported": True,
        "captured_at": time.time(),
        "sockets": rows,
        "owned_pids": sorted(int(pid) for pid in owned),
        "network_pid": network_pid,
        "network_pids": sorted(network_pids),
        "chromium_pid": chromium_pid,
        "chromium_pids": sorted(chromium_pids),
        "proxy_port": proxy_port,
        "devtools_port": devtools_port,
        "request_audit": {
            "status": str((request_audit or {}).get("status") or "unknown"),
            "reason": str((request_audit or {}).get("reason") or ""),
            "target_count": int((request_audit or {}).get("target_count") or 0),
            "request_count": int((request_audit or {}).get("request_count") or 0),
        },
        "udp_peer_monitor": {
            "status": str((udp_peer_state or {}).get("status") or "unknown"),
            "reason": str((udp_peer_state or {}).get("reason") or ""),
            "peer_count": len(peer_rows),
            "tcp_recent_count": len(tcp_event_rows),
        },
        "sampling_note": (
            "Current TCP sockets use owner-PID snapshots; recent TCP connect/accept events "
            "and UDP remote peers are enriched from live Microsoft-Windows-Kernel-Network ETW."
            if os.name == "nt" else
            "Linux Preview reads current TCP/UDP sockets from procfs and correlates socket inodes to Tekzite-owned PIDs. "
            "CDP/proxy attribution is live; very short-lived flows can still fall between snapshots until optional eBPF event capture is added."
        ),
    }


def stop_live_socket_peer_monitor():
    """Stop optional UDP ETW + CDP attribution monitors with the Live Socket View."""
    stop_udp_peer_monitor()
    stop_network_request_audit_monitor()

def reverse_dns_hostname(address: str) -> str:
    """Best-effort PTR lookup for one IP. Intended for background UI workers."""
    address = _normalize_socket_address(address)
    if not address:
        return ""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return ""
    if ip.is_loopback:
        return "localhost"
    try:
        name = socket.gethostbyaddr(address)[0]
        return str(name or "").strip().rstrip(".")[:253]
    except Exception:
        return ""

def loopback_debug():
    """Return the Python loopback allow-list and recent denied attempts."""
    return loopback_policy_snapshot()


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

    # Linux preview/CI can pin an exact Chromium-family executable without
    # changing the normal desktop discovery order. This is also useful on
    # distributions where `chromium` is a sandboxed launcher wrapper rather
    # than the real browser binary.
    override = str(os.environ.get("TEKZITE_CHROMIUM") or "").strip()
    if override:
        candidate = shutil.which(override) if os.path.basename(override) == override else os.path.expanduser(override)
        if candidate and os.path.isfile(candidate):
            key = os.path.normcase(os.path.realpath(candidate))
            seen.add(key)
            yield candidate

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
_EDGE_SESSION_LOCK = threading.RLock()
_CHROMIUM_LAUNCH_DEBUG = {
    "attempts": 0, "executable": None, "port": None, "profile": None,
    "recovered": False, "last_error": None, "errors": [],
}



def _persistent_edge_profile_dir():
    """Return Tekzite's dedicated Chromium compatibility profile.

    Private windows set ``TEKZITE_CHROMIUM_PROFILE`` to a process-unique
    temporary directory. Normal windows retain the long-lived Tekzite profile.

    The profile has a Tekzite/Chromium identity only.  On first v4.43 launch
    we migrate the older Edge-named bridge directory in place so cookies,
    storage and sign-ins survive the branding cleanup.
    """
    override = os.environ.get("TEKZITE_CHROMIUM_PROFILE", "").strip()
    if override:
        path = os.path.abspath(os.path.expanduser(override))
        os.makedirs(path, exist_ok=True)
        return path

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


def _profile_recovery_needed(profile_dir):
    """Cheaply detect whether cold-start recovery work is actually needed.

    A clean Tekzite shutdown removes its owner marker and Chromium singleton
    artifacts.  Full Win32_Process/CIM enumeration is comparatively expensive,
    so v9.5 only pays for it when those cheap on-disk signals indicate an
    unclean prior session. A failed first launch still falls back to the full
    recovery path on retry.
    """
    try:
        profile = Path(profile_dir)
        if Path(_edge_profile_owner_file(profile_dir)).exists():
            return True
        return any((profile / name).exists() for name in
                   ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"))
    except Exception:
        return True


def _terminate_stale_profile_owner(profile_dir):
    """Terminate a stale Chromium owner only after verifying its identity.

    Windows can reuse PIDs after a crash. The marker inside the Tekzite profile
    is therefore never sufficient authority to call taskkill by itself. Before
    terminating anything, require the recorded PID to be a Chromium-family
    process whose command line contains this exact Tekzite ``--user-data-dir``.
    If verification fails, only discard the stale marker.
    """
    owner = _edge_profile_owner_file(profile_dir)
    try:
        pid = int(Path(owner).read_text(encoding="ascii").strip())
    except Exception:
        try:
            os.remove(owner)
        except OSError:
            pass
        return False

    if pid <= 0 or pid == os.getpid():
        try:
            os.remove(owner)
        except OSError:
            pass
        return False

    verified = False
    if os.name == "nt":
        try:
            verified = pid in set(_profile_chromium_pids(profile_dir))
        except Exception:
            verified = False
        if verified:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass

    try:
        os.remove(owner)
    except OSError:
        pass
    return bool(verified)



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
        "$_.ProcessId -ne $selfPid -and $_.CommandLine -and $_.Name -and "
        "$_.Name.ToLower() -match '^(chrome|chromium|ungoogled-chromium)(\\.exe)?$' -and "
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
                _shutil.rmtree(path)
                removed.append(name)
        except Exception:
            pass
    return removed

def _pid_is_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                code = wintypes.DWORD()
                return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and int(code.value) == STILL_ACTIVE)
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def remove_profile_tree(path, retries=8, delay=0.08):
    """Remove a Tekzite-owned profile and verify that it is actually gone."""
    if not path:
        return True
    target = Path(path)
    try:
        if not target.exists():
            return True
    except OSError:
        pass

    def _onerror(func, failing_path, exc_info):
        try:
            os.chmod(failing_path, 0o700)
            func(failing_path)
        except Exception:
            pass

    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            shutil.rmtree(target, onerror=_onerror)
        except FileNotFoundError:
            return True
        except Exception:
            pass
        try:
            if not target.exists():
                return True
        except OSError:
            return True
        if attempt + 1 < attempts:
            time.sleep(max(0.0, float(delay)) * (attempt + 1))
    try:
        return not target.exists()
    except OSError:
        return False


def cleanup_abandoned_temporary_profiles(base_dir=None, minimum_orphan_age=3600):
    """Scavenge dead Tekzite private/lockdown temp profiles without races."""
    root = Path(base_dir or tempfile.gettempdir())
    removed, skipped_live = [], []
    now = time.time()
    try:
        children = list(root.iterdir())
    except Exception:
        return {"removed": removed, "skipped_live": skipped_live}
    for child in children:
        name = child.name
        if not child.is_dir() or not (
            name.startswith("Tekzite-Private-") or name.startswith("Tekzite-Privacy-")
        ):
            continue
        candidate_pids = set()
        marker_path = child / "tekzite-helper.pid"
        try:
            marker_pid = int(marker_path.read_text(encoding="ascii").strip())
            if marker_pid > 0:
                candidate_pids.add(marker_pid)
        except Exception:
            pass
        for prefix in ("Tekzite-Private-", "Tekzite-Privacy-"):
            if name.startswith(prefix):
                token = name[len(prefix):].split("-", 1)[0]
                if token.isdigit() and int(token) > 0:
                    candidate_pids.add(int(token))
                break
        if any(_pid_is_alive(pid) for pid in candidate_pids):
            skipped_live.append(str(child))
            continue
        if not candidate_pids:
            try:
                age = max(0.0, now - child.stat().st_mtime)
            except OSError:
                age = 0.0
            if age < max(300.0, float(minimum_orphan_age)):
                continue
        if remove_profile_tree(child):
            removed.append(str(child))
    return {"removed": removed, "skipped_live": skipped_live}


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


def _devtools_active_port_file(profile_dir):
    return Path(profile_dir) / "DevToolsActivePort"


def _clear_devtools_active_port(profile_dir):
    path = _devtools_active_port_file(profile_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError as exc:
        raise RuntimeError(f"Could not clear stale DevToolsActivePort: {exc}") from exc
    return True


def _read_devtools_active_port(profile_dir):
    path = _devtools_active_port_file(profile_dir)
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (FileNotFoundError, PermissionError, UnicodeError, OSError):
        return None
    if not lines:
        return None
    try:
        port = int(lines[0].strip())
    except (TypeError, ValueError):
        return None
    if not (1 <= port <= 65535):
        return None
    browser_path = str(lines[1].strip()) if len(lines) > 1 else ""
    if browser_path and not browser_path.startswith("/devtools/browser/"):
        return None
    return port, browser_path


def _validate_devtools_ws_url(ws_url, expected_port=None):
    """Accept only a loopback Chromium DevTools WebSocket on the expected port."""
    parsed = urlsplit(str(ws_url or ""))
    if parsed.scheme != "ws":
        raise RuntimeError("DevTools WebSocket must use ws:// on loopback")
    host = str(parsed.hostname or "").strip().strip("[]").lower()
    if host == "localhost":
        loopback = True
    else:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise RuntimeError("Rejected non-loopback DevTools WebSocket URL")
    try:
        port = int(parsed.port or 0)
    except ValueError as exc:
        raise RuntimeError("DevTools WebSocket has invalid port") from exc
    if not (1 <= port <= 65535):
        raise RuntimeError("DevTools WebSocket has missing/invalid port")
    if expected_port is not None and port != int(expected_port):
        raise RuntimeError("DevTools WebSocket port does not match DevToolsActivePort")
    if not str(parsed.path or "").startswith("/devtools/"):
        raise RuntimeError("DevTools WebSocket has unexpected path")
    return str(ws_url)


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
    if os.name != "nt":
        try:
            os.killpg(os.getpgid(int(process.pid)), signal.SIGTERM)
            try:
                process.wait(timeout=2.0)
            except Exception:
                os.killpg(os.getpgid(int(process.pid)), signal.SIGKILL)
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
            local_host = local.rsplit(":", 1)[0].strip("[]").lower()
            if local_host not in {"127.0.0.1", "::1"}:
                continue
            try:
                return int(pid)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def _network_helper_pid_matches_state(pid, state):
    """Verify a discovered Windows listener is this exact Tekzite helper.

    PID and port alone are not identities: both can be reused after a crash.
    Each helper launch receives a 128-bit random command-line token. A listener
    found through netstat is eligible for taskkill only when CIM confirms the
    same token, port and expected helper executable/script.
    """
    if os.name != "nt" or not state:
        return False
    try:
        pid = int(pid)
        port = int(state.get("port"))
    except (TypeError, ValueError):
        return False
    token = str(state.get("instance_token") or "").strip()
    if pid <= 0 or pid == os.getpid() or len(token) < 16:
        return False
    script = (
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
        "if ($p -and $p.CommandLine -and $p.Name) { "
        "Write-Output $p.Name; Write-Output $p.CommandLine }"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=4, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    lines = (result.stdout or "").splitlines()
    if len(lines) < 2:
        return False
    name = lines[0].strip().lower()
    command_line = " ".join(lines[1:]).strip()
    lower = command_line.lower()
    if token not in command_line:
        return False
    if not (f"--port {port}" in lower or f"--port={port}" in lower):
        return False
    mode = str(state.get("mode") or "")
    if mode == "exe":
        return name == "tekzite-network.exe" or "tekzite-network.exe" in lower
    if mode == "python":
        return name.startswith("python") and "tekzite_network.py" in lower
    return False


def _wait_for_devtools(profile_dir, process, timeout=10.0):
    """Wait for Chromium's OS-assigned loopback DevTools endpoint.

    Chromium is launched with ``--remote-debugging-port=0``. It writes the
    selected port into ``DevToolsActivePort`` inside Tekzite's dedicated profile.
    Tekzite validates that the listener belongs to Chromium using this exact
    profile before registering the port with the process-local loopback policy.
    """
    deadline = time.monotonic() + timeout
    last_error = None
    clean_exit_seen = False
    exit_code = None
    registered_port = None
    try:
        _hide_process_windows(process.pid)
    except Exception:
        pass
    while time.monotonic() < deadline:
        rc = process.poll()
        if rc is not None:
            exit_code = int(rc)
            if exit_code != 0:
                if registered_port:
                    revoke_loopback_port(registered_port)
                raise RuntimeError(f"Chromium bridge exited early with code {exit_code}")
            clean_exit_seen = True

        active = _read_devtools_active_port(profile_dir)
        if not active:
            time.sleep(0.01)
            continue
        port, browser_path = active
        try:
            if os.name == "nt":
                listener_pid = _listener_pid_for_port(port)
                if not listener_pid:
                    raise RuntimeError("DevToolsActivePort has no loopback listener yet")
                # Normal launch: the browser process itself owns the listener,
                # avoiding an expensive CIM scan on the startup fast path.
                if int(listener_pid) != int(getattr(process, "pid", 0) or 0):
                    profile_pids = set(_profile_chromium_pids(profile_dir))
                    if listener_pid not in profile_pids:
                        raise RuntimeError(
                            "DevToolsActivePort listener is not Chromium using Tekzite's profile"
                        )
            if registered_port != port:
                if registered_port:
                    revoke_loopback_port(registered_port)
                if not allow_loopback_port(port, "Chromium DevTools/CDP (tab control, input, zoom and diagnostics)", owner="chromium"):
                    raise RuntimeError("Could not register Chromium DevTools loopback port")
                registered_port = int(port)

            version_info = _devtools_json(port, "/json/version", timeout=0.20)
            if not isinstance(version_info, dict):
                raise RuntimeError("Chromium DevTools version endpoint returned invalid JSON")
            ws_url = str(version_info.get("webSocketDebuggerUrl") or "")
            if not ws_url and browser_path:
                ws_url = f"ws://127.0.0.1:{int(port)}{browser_path}"
            version_info["webSocketDebuggerUrl"] = _validate_devtools_ws_url(
                ws_url, expected_port=port
            )
            if not clean_exit_seen:
                try:
                    _hide_process_windows(process.pid)
                except Exception:
                    pass
            adopted_pid = _listener_pid_for_port(port) if clean_exit_seen else None
            return {
                "handoff": bool(clean_exit_seen),
                "exit_code": exit_code,
                "adopted_pid": adopted_pid,
                "port": int(port),
                "version": version_info,
            }
        except Exception as exc:
            last_error = exc
            time.sleep(0.01)

    if registered_port:
        revoke_loopback_port(registered_port)
    if clean_exit_seen:
        raise RuntimeError(
            "Chromium launcher exited cleanly with code 0, but no verified DevTools "
            "endpoint appeared after handoff"
        ) from last_error
    raise RuntimeError("Timed out waiting for verified Chromium DevTools") from last_error


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

        parsed = urlparse(_validate_devtools_ws_url(str(ws_url)))
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        sock = socket.create_connection((host, port), timeout=timeout)
        # v8.9: CDP is latency-sensitive tiny-message traffic on loopback.
        # Disable Nagle so clicks/keys/activation commands are written
        # immediately instead of being candidates for TCP packet coalescing.
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
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
            if opcode >= 0x8 and (not fin or length > 125):
                self.close()
                raise ConnectionError("Invalid oversized/fragmented DevTools control frame")
            if length > MAX_CDP_WEBSOCKET_FRAME_BYTES:
                self.close()
                raise ConnectionError("DevTools WebSocket frame exceeded Tekzite safety limit")
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
                if not fragments:
                    self.close()
                    raise ConnectionError("Unexpected DevTools continuation frame")
                fragments.extend(payload)
            else:
                continue
            if len(fragments) > MAX_CDP_WEBSOCKET_MESSAGE_BYTES:
                self.close()
                raise ConnectionError("DevTools WebSocket message exceeded Tekzite safety limit")

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
        outbound_params = params or {}
        if str(method or "") == "Runtime.evaluate":
            outbound_params = _tag_runtime_evaluate_params(outbound_params, "runtime/evaluate")
        ws.send(json.dumps({
            "id": next_id,
            "method": method,
            "params": outbound_params,
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


# ---- Live request attribution + socket forensics (v10.5.76) ---------------

def _script_source_excerpt(source, line=0, column=0, *, context_lines=3, max_line_chars=1600, max_total_chars=12000):
    """Return a bounded, display-only excerpt around one JavaScript caller.

    Source text is never stored by this helper.  Long/minified lines are clipped
    around the caller column so the details window stays responsive even for
    multi-megabyte bundles.  Caller line/column values are one-based.
    """
    source = str(source or "")
    try:
        line = max(0, int(line or 0))
    except Exception:
        line = 0
    try:
        column = max(0, int(column or 0))
    except Exception:
        column = 0
    try:
        context_lines = max(0, min(12, int(context_lines)))
    except Exception:
        context_lines = 3
    lines = source.splitlines() or ([source] if source else [])
    if not lines:
        return {"ok": False, "reason": "Chromium returned an empty script source.", "text": ""}

    target_index = min(max(0, line - 1 if line else 0), len(lines) - 1)
    start = max(0, target_index - context_lines)
    end = min(len(lines), target_index + context_lines + 1)
    rendered = []
    truncated = False
    caret_column = 0

    for idx in range(start, end):
        raw_line = lines[idx]
        display_line = raw_line
        left_cut = 0
        if len(display_line) > max_line_chars:
            truncated = True
            if idx == target_index and column:
                zero_col = max(0, column - 1)
                before = min(480, max_line_chars // 2)
                left_cut = max(0, zero_col - before)
                right = min(len(display_line), left_cut + max_line_chars)
                if right - left_cut < max_line_chars and left_cut:
                    left_cut = max(0, right - max_line_chars)
                display_line = display_line[left_cut:right]
                if left_cut:
                    display_line = "…" + display_line
                if right < len(raw_line):
                    display_line += "…"
            else:
                display_line = display_line[:max_line_chars] + "…"
        marker = ">>" if idx == target_index else "  "
        rendered.append(f"{marker} {idx + 1:>6} | {display_line}")
        if idx == target_index and column:
            visual_offset = max(0, column - 1 - left_cut) + (1 if left_cut else 0)
            caret_column = visual_offset
            rendered.append(" " * 12 + " " * visual_offset + "^")

    text = "\n".join(rendered)
    if len(text) > max_total_chars:
        text = text[:max_total_chars] + "\n… excerpt clipped …"
        truncated = True
    return {
        "ok": True, "text": text, "line": target_index + 1, "column": column,
        "line_count": len(lines), "source_chars": len(source), "truncated": truncated,
        "caret_column": caret_column,
    }


_TEKZITE_INTERNAL_SOURCE_SCHEME = "tekzite-internal"


def _sanitize_internal_source_tag(value):
    """Return a bounded path-safe tag for a Tekzite-injected Runtime script."""
    tag = str(value or "runtime/evaluate").strip().replace("\\", "/").strip("/")
    tag = re.sub(r"[^A-Za-z0-9._/-]+", "-", tag)
    tag = re.sub(r"/{2,}", "/", tag).strip("/")[:180]
    return tag or "runtime/evaluate"


def _tag_runtime_evaluate_params(params, internal_source="runtime/evaluate"):
    """Stamp Tekzite-authored Runtime.evaluate code with CDP-visible provenance.

    Chromium's ``//# sourceURL=`` marker becomes the call-frame URL for network
    initiators created by evaluated JavaScript.  This lets the live audit tell
    Tekzite's own helpers apart from website JavaScript without inspecting or
    pattern-matching source contents.
    """
    params = dict(params or {})
    expression = params.get("expression")
    if not isinstance(expression, str) or not expression:
        return params
    if re.search(r"(?m)^\s*//[#@]\s*sourceURL\s*=", expression):
        return params
    tag = _sanitize_internal_source_tag(internal_source)
    params["expression"] = expression + f"\n//# sourceURL={_TEKZITE_INTERNAL_SOURCE_SCHEME}://{tag}"
    return params


def _audit_internal_source_id(value):
    """Return a sanitized Tekzite internal source id from one CDP script URL."""
    try:
        parts = urlsplit(str(value or ""))
    except Exception:
        return ""
    if str(parts.scheme or "").lower() != _TEKZITE_INTERNAL_SOURCE_SCHEME:
        return ""
    pieces = [str(parts.netloc or "").strip("/")] + [part for part in str(parts.path or "").split("/") if part]
    return _sanitize_internal_source_tag("/".join(part for part in pieces if part))


def _audit_url_parts(value):
    """Return (scheme, hostname, port) without retaining a full URL."""
    try:
        parts = urlsplit(str(value or ""))
        scheme = str(parts.scheme or "").lower()
        host = str(parts.hostname or "").strip().rstrip(".").lower()[:253]
        port = int(parts.port or (443 if scheme in {"https", "wss"} else 80 if scheme in {"http", "ws"} else 0))
        return scheme, host, port
    except Exception:
        return "", "", 0


def _audit_target_scope(target):
    """Classify a DevTools target without exposing its complete URL."""
    target_type = str((target or {}).get("type") or "").strip().lower()
    scheme, host, _port = _audit_url_parts((target or {}).get("url"))
    if scheme == "chrome-extension":
        return "Extension", target_type or "extension", host
    if scheme in {"chrome", "devtools"} or target_type == "browser":
        return "Browser internal", target_type or "browser", host
    if target_type == "page":
        return "Page", "page", host
    if target_type == "service_worker":
        return "Service worker", target_type, host
    if target_type in {"worker", "shared_worker"}:
        return "Page worker", target_type, host
    if target_type == "background_page":
        return "Extension" if scheme == "chrome-extension" else "Background target", target_type, host
    return "Other Chromium target", target_type or "other", host


# ---- On-demand JavaScript source analysis (v10.5.78) -----------------------

_JS_NETWORK_PATTERNS = (
    ("fetch", re.compile(r"(?<![\w$])fetch\s*\(")),
    ("XMLHttpRequest", re.compile(r"(?<![\w$])(?:new\s+)?XMLHttpRequest\s*\(")),
    ("WebSocket", re.compile(r"(?<![\w$])new\s+WebSocket\s*\(")),
    ("EventSource", re.compile(r"(?<![\w$])new\s+EventSource\s*\(")),
    ("sendBeacon", re.compile(r"navigator\s*\.\s*sendBeacon\s*\(")),
    ("WebTransport", re.compile(r"(?<![\w$])new\s+WebTransport\s*\(")),
)
_SOURCE_MAP_DIRECTIVE_RE = re.compile(
    r"(?://[#@]\s*sourceMappingURL\s*=\s*([^\s]+)|/\*[#@]\s*sourceMappingURL\s*=\s*([^*]+?)\s*\*/)",
    re.IGNORECASE,
)
_SOURCE_MAP_B64 = {ch: i for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}


def _source_line_column_to_offset(source, line=0, column=0):
    """Translate one-based caller coordinates to a bounded Python offset."""
    source = str(source or "")
    if not source:
        return 0
    try:
        line = max(1, int(line or 1))
    except Exception:
        line = 1
    try:
        column = max(1, int(column or 1))
    except Exception:
        column = 1
    starts = [0]
    for match in re.finditer(r"\n", source):
        starts.append(match.end())
    line_index = min(line - 1, len(starts) - 1)
    start = starts[line_index]
    end = starts[line_index + 1] - 1 if line_index + 1 < len(starts) else len(source)
    return min(end, start + max(0, column - 1))


def _offset_to_line_column(source, offset):
    source = str(source or "")
    offset = max(0, min(len(source), int(offset or 0)))
    line = source.count("\n", 0, offset) + 1
    last_nl = source.rfind("\n", 0, offset)
    column = offset + 1 if last_nl < 0 else offset - last_nl
    return line, column


def _js_regex_can_start(source, slash_index):
    """Conservative lexical hint for distinguishing /regex/ from division."""
    source = str(source or "")
    j = int(slash_index) - 1
    while j >= 0 and source[j].isspace():
        j -= 1
    if j < 0:
        return True
    if source[j] in "([{=:;,!?&|+-*%^~<>":
        return True
    end = j + 1
    while j >= 0 and (source[j].isalnum() or source[j] in "_$"):
        j -= 1
    word = source[j + 1:end]
    return word in {
        "return", "case", "throw", "typeof", "delete", "void", "new",
        "yield", "await", "else", "do", "instanceof", "in", "of",
    }


def _js_code_mask(source):
    """Return same-length code with strings/comments/regex literals blanked."""
    source = str(source or "")
    chars = list(source)
    state = "normal"
    escaped = False
    regex_class = False
    i = 0
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state in {"single", "double", "template"}:
            if ch not in "\r\n":
                chars[i] = " "
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif (state == "single" and ch == "'") or (state == "double" and ch == '"') or (state == "template" and ch == "`"):
                state = "normal"
            i += 1
            continue
        if state == "line_comment":
            if ch in "\r\n":
                state = "normal"
            else:
                chars[i] = " "
            i += 1
            continue
        if state == "block_comment":
            if ch not in "\r\n":
                chars[i] = " "
            if ch == "*" and nxt == "/":
                chars[i + 1] = " "
                i += 2
                state = "normal"
                continue
            i += 1
            continue
        if state == "regex":
            if ch not in "\r\n":
                chars[i] = " "
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "[":
                regex_class = True
            elif ch == "]" and regex_class:
                regex_class = False
            elif ch == "/" and not regex_class:
                state = "normal"
            i += 1
            continue
        if ch == "/" and nxt == "/":
            chars[i] = chars[i + 1] = " "
            state = "line_comment"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            chars[i] = chars[i + 1] = " "
            state = "block_comment"
            i += 2
            continue
        if ch == "/" and _js_regex_can_start(source, i):
            chars[i] = " "
            state = "regex"
            regex_class = False
            i += 1
            continue
        if ch == "'":
            chars[i] = " "
            state = "single"
        elif ch == '"':
            chars[i] = " "
            state = "double"
        elif ch == "`":
            chars[i] = " "
            state = "template"
        i += 1
    return "".join(chars)


def _js_pretty_print(source, caller_offset=0, *, max_chars=2_500_000):
    """Pretty-print generated JavaScript for display without evaluating it.

    This is deliberately a formatter, not an interpreter. Quoted strings and
    comments are preserved verbatim; structural whitespace is added around
    braces and semicolons. The requested source offset is mapped into the
    formatted output so the caller caret can follow a one-line minified bundle.
    """
    source = str(source or "")
    if not source:
        return {"ok": False, "text": "", "reason": "Empty JavaScript source."}
    if len(source) > int(max_chars):
        return {
            "ok": False, "text": "", "reason": "Script is too large for safe local pretty-printing.",
            "source_chars": len(source),
        }
    caller_offset = max(0, min(len(source), int(caller_offset or 0)))
    out = []
    indent = 0
    at_line_start = True
    out_line = 1
    out_col = 1
    mapped = {"line": 0, "column": 0}
    pending_space = False

    def emit(text, src_index=None):
        nonlocal at_line_start, out_line, out_col, pending_space
        if not text:
            return
        if at_line_start:
            prefix = "  " * max(0, indent)
            if prefix:
                out.append(prefix)
                out_col += len(prefix)
            at_line_start = False
        if src_index is not None and src_index == caller_offset and not mapped["line"]:
            mapped["line"], mapped["column"] = out_line, out_col
        out.append(text)
        if "\n" in text:
            parts = text.split("\n")
            out_line += len(parts) - 1
            out_col = len(parts[-1]) + 1
            at_line_start = parts[-1] == ""
        else:
            out_col += len(text)
        pending_space = False

    def newline():
        nonlocal at_line_start, out_line, out_col, pending_space
        if not out or out[-1] != "\n":
            out.append("\n")
            out_line += 1
        out_col = 1
        at_line_start = True
        pending_space = False

    def queue_space():
        nonlocal pending_space
        pending_space = True

    def flush_space(next_char=""):
        nonlocal pending_space
        if not pending_space or at_line_start:
            pending_space = False
            return
        prev = out[-1][-1] if out and out[-1] else ""
        if prev and prev not in "([{.,:;" and next_char not in ")]},.:;":
            emit(" ")
        pending_space = False

    state = "normal"
    escaped = False
    regex_class = False
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state in {"single", "double", "template"}:
            emit(ch, i)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif (state == "single" and ch == "'") or (state == "double" and ch == '"') or (state == "template" and ch == "`"):
                state = "normal"
            i += 1
            continue
        if state == "regex":
            emit(ch, i)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "[":
                regex_class = True
            elif ch == "]" and regex_class:
                regex_class = False
            elif ch == "/" and not regex_class:
                state = "normal"
            i += 1
            continue
        if state == "line_comment":
            if ch in "\r\n":
                newline()
                state = "normal"
                if ch == "\r" and nxt == "\n":
                    i += 1
            else:
                emit(ch, i)
            i += 1
            continue
        if state == "block_comment":
            emit(ch, i)
            if ch == "*" and nxt == "/":
                emit(nxt, i + 1)
                i += 2
                state = "normal"
                newline()
                continue
            i += 1
            continue

        if ch.isspace():
            if i == caller_offset and not mapped["line"]:
                mapped["line"], mapped["column"] = out_line, out_col
            queue_space()
            i += 1
            continue
        if ch == "/" and nxt == "/":
            flush_space("/")
            emit("//", i)
            i += 2
            state = "line_comment"
            continue
        if ch == "/" and nxt == "*":
            flush_space("/")
            emit("/*", i)
            i += 2
            state = "block_comment"
            continue
        if ch == "/" and _js_regex_can_start(source, i):
            flush_space("/")
            emit(ch, i)
            state = "regex"
            regex_class = False
            i += 1
            continue
        if ch in "'\"`":
            flush_space(ch)
            emit(ch, i)
            state = {"'": "single", '"': "double", "`": "template"}[ch]
            i += 1
            continue
        if ch == "{":
            flush_space(ch)
            emit(ch, i)
            indent += 1
            newline()
            i += 1
            continue
        if ch == "}":
            indent = max(0, indent - 1)
            if not at_line_start:
                newline()
            emit(ch, i)
            tail = source[i + 1:i + 10].lstrip()
            if nxt not in ";,)]" and not tail.startswith(("else", "catch", "finally", "while")):
                newline()
            i += 1
            continue
        if ch == ";":
            flush_space(ch)
            emit(ch, i)
            newline()
            i += 1
            continue
        if ch == ",":
            flush_space(ch)
            emit(ch, i)
            queue_space()
            i += 1
            continue
        if ch == ":":
            flush_space(ch)
            emit(ch, i)
            queue_space()
            i += 1
            continue
        flush_space(ch)
        emit(ch, i)
        i += 1

    if caller_offset == len(source) and not mapped["line"]:
        mapped["line"], mapped["column"] = out_line, out_col
    return {
        "ok": True,
        "text": "".join(out).strip("\n"),
        "line": int(mapped["line"] or 1),
        "column": int(mapped["column"] or 1),
        "source_chars": len(source),
    }


def _js_lexical_brace_spans(source):
    """Return matched brace spans while ignoring strings and comments."""
    source = str(source or "")
    stack = []
    spans = []
    state = "normal"
    escaped = False
    regex_class = False
    i = 0
    while i < len(source):
        ch = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state in {"single", "double", "template"}:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif (state == "single" and ch == "'") or (state == "double" and ch == '"') or (state == "template" and ch == "`"):
                state = "normal"
            i += 1
            continue
        if state == "regex":
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "[":
                regex_class = True
            elif ch == "]" and regex_class:
                regex_class = False
            elif ch == "/" and not regex_class:
                state = "normal"
            i += 1
            continue
        if state == "line_comment":
            if ch in "\r\n":
                state = "normal"
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "normal"
                i += 2
                continue
            i += 1
            continue
        if ch == "/" and nxt == "/":
            state = "line_comment"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            state = "block_comment"
            i += 2
            continue
        if ch == "/" and _js_regex_can_start(source, i):
            state = "regex"
            regex_class = False
            i += 1
            continue
        if ch == "'":
            state = "single"
            i += 1
            continue
        if ch == '"':
            state = "double"
            i += 1
            continue
        if ch == "`":
            state = "template"
            i += 1
            continue
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            spans.append((start, i + 1))
        i += 1
    return spans


def _js_enclosing_function(source, caller_offset):
    """Best-effort containing function span/signature for generated JS."""
    source = str(source or "")
    caller_offset = max(0, min(len(source), int(caller_offset or 0)))
    candidates = []
    patterns = (
        re.compile(r"(?:async\s+)?function(?:\s*\*)?\s*([A-Za-z_$][\w$]*)?\s*\([^{};]*\)\s*$"),
        re.compile(r"(?:async\s*)?\([^{};]*\)\s*=>\s*$"),
        re.compile(r"(?:async\s+)?[A-Za-z_$][\w$]*\s*=>\s*$"),
        re.compile(r"(?:async\s+)?(?:get\s+|set\s+)?[A-Za-z_$][\w$]*\s*\([^{};]*\)\s*$"),
    )
    for start, end in _js_lexical_brace_spans(source):
        if not (start <= caller_offset < end):
            continue
        look_start = max(0, start - 520)
        tail = source[look_start:start]
        match = None
        for pattern in patterns:
            match = pattern.search(tail)
            if match:
                break
        if match:
            sig_start = look_start + match.start()
            signature = re.sub(r"\s+", " ", source[sig_start:start].strip())[:360]
            keyword = signature.split("(", 1)[0].strip().split()[-1] if "(" in signature and signature.split("(", 1)[0].strip() else ""
            if keyword in {"if", "for", "while", "switch", "catch", "with"}:
                continue
            candidates.append((end - start, sig_start, start, end, signature))
    if not candidates:
        return {"found": False}
    _, sig_start, brace_start, end, signature = min(candidates, key=lambda item: item[0])
    return {
        "found": True,
        "start": sig_start,
        "brace_start": brace_start,
        "end": end,
        "signature": signature or "(anonymous function)",
    }


def _js_network_primitive_trace(source, caller_offset, function_info=None, *, limit=8):
    """Find visible browser network primitives in/near the caller function."""
    source = str(source or "")
    caller_offset = max(0, min(len(source), int(caller_offset or 0)))
    if function_info and function_info.get("found"):
        start = int(function_info.get("start") or 0)
        end = int(function_info.get("end") or len(source))
    else:
        start = max(0, caller_offset - 1800)
        end = min(len(source), caller_offset + 5000)
    segment = source[start:end]
    code_segment = _js_code_mask(segment)
    found = []
    for name, pattern in _JS_NETWORK_PATTERNS:
        for match in pattern.finditer(code_segment):
            absolute = start + match.start()
            line, column = _offset_to_line_column(source, absolute)
            found.append({
                "name": name,
                "offset": absolute,
                "line": line,
                "column": column,
                "direction": "at/after caller" if absolute >= caller_offset else "before caller",
                "distance": absolute - caller_offset,
            })
    found.sort(key=lambda item: (0 if item["offset"] >= caller_offset else 1, abs(item["distance"])))
    return found[:max(1, int(limit))]


def _source_map_url_from_source(source):
    matches = list(_SOURCE_MAP_DIRECTIVE_RE.finditer(str(source or "")))
    if not matches:
        return ""
    match = matches[-1]
    return str(match.group(1) or match.group(2) or "").strip().strip("\"'")[:16384]


def _decode_source_map_vlq(segment):
    values = []
    value = 0
    shift = 0
    for ch in str(segment or ""):
        digit = _SOURCE_MAP_B64.get(ch)
        if digit is None:
            raise ValueError("invalid base64 VLQ digit")
        continuation = bool(digit & 32)
        digit &= 31
        value += digit << shift
        if continuation:
            shift += 5
            if shift > 35:
                raise ValueError("base64 VLQ value too large")
            continue
        negative = bool(value & 1)
        decoded = value >> 1
        values.append(-decoded if negative else decoded)
        value = 0
        shift = 0
    if shift:
        raise ValueError("truncated base64 VLQ value")
    return values


def _source_map_lookup(map_data, generated_line, generated_column):
    """Map a zero-based generated position through a simple Source Map v3."""
    if not isinstance(map_data, dict) or int(map_data.get("version") or 0) != 3:
        return None
    if isinstance(map_data.get("sections"), list):
        return None
    mappings = str(map_data.get("mappings") or "")
    sources = map_data.get("sources") if isinstance(map_data.get("sources"), list) else []
    names = map_data.get("names") if isinstance(map_data.get("names"), list) else []
    source_index = 0
    original_line = 0
    original_column = 0
    name_index = 0
    best = None
    for line_no, encoded_line in enumerate(mappings.split(";")):
        generated_col = 0
        for encoded_segment in encoded_line.split(",") if encoded_line else []:
            if not encoded_segment:
                continue
            try:
                values = _decode_source_map_vlq(encoded_segment)
            except ValueError:
                continue
            if not values:
                continue
            generated_col += values[0]
            if len(values) >= 4:
                source_index += values[1]
                original_line += values[2]
                original_column += values[3]
                if len(values) >= 5:
                    name_index += values[4]
                if line_no == int(generated_line) and generated_col <= int(generated_column):
                    best = (
                        generated_col,
                        source_index,
                        original_line,
                        original_column,
                        name_index if len(values) >= 5 else None,
                    )
        if line_no >= int(generated_line):
            break
    if best is None:
        return None
    _generated_col, src_i, orig_line, orig_col, name_i = best
    source_name = str(sources[src_i]) if 0 <= src_i < len(sources) else ""
    source_file = source_name.replace("\\", "/").rsplit("/", 1)[-1][:220] or "(original source)"
    name = str(names[name_i])[:180] if name_i is not None and 0 <= name_i < len(names) else ""
    return {
        "source_index": src_i,
        "source_file": source_file,
        "line": int(orig_line) + 1,
        "column": int(orig_col) + 1,
        "name": name,
    }


def _decode_inline_source_map(source_map_url, generated_line, generated_column):
    raw = str(source_map_url or "")
    if not raw.lower().startswith("data:"):
        return None
    try:
        header, payload = raw.split(",", 1)
    except ValueError:
        return None
    try:
        if ";base64" in header.lower():
            data = base64.b64decode(payload, validate=False)
        else:
            data = unquote_to_bytes(payload)
        if len(data) > 6 * 1024 * 1024:
            return {
                "available": True,
                "kind": "inline",
                "reason": "Inline source map is larger than the 6 MB inspection limit.",
            }
        parsed = json.loads(data.decode("utf-8", "replace"))
    except Exception:
        return {
            "available": True,
            "kind": "inline",
            "reason": "Inline source map could not be decoded safely.",
        }
    mapped = _source_map_lookup(parsed, max(0, int(generated_line)), max(0, int(generated_column)))
    info = {"available": True, "kind": "inline", "mapped": mapped}
    if mapped:
        contents = parsed.get("sourcesContent") if isinstance(parsed.get("sourcesContent"), list) else []
        idx = int(mapped.get("source_index") or 0)
        if 0 <= idx < len(contents) and isinstance(contents[idx], str):
            excerpt = _script_source_excerpt(
                contents[idx], mapped["line"], mapped["column"],
                context_lines=4, max_line_chars=1800,
            )
            if excerpt.get("ok"):
                info["original_excerpt"] = excerpt.get("text") or ""
    return info


def _sanitize_source_map_advertisement(script_url, source_map_url):
    source_map_url = str(source_map_url or "").strip()
    if not source_map_url:
        return {"available": False, "kind": "none", "label": "No source map advertised"}
    if source_map_url.lower().startswith("data:"):
        return {"available": True, "kind": "inline", "label": "Inline Source Map v3 data"}
    try:
        absolute = urljoin(str(script_url or ""), source_map_url)
    except Exception:
        absolute = source_map_url
    try:
        parsed = urlsplit(absolute)
        host = str(parsed.hostname or "")[:253]
        filename = str(parsed.path or "").replace("\\", "/").rsplit("/", 1)[-1][:220]
    except Exception:
        host, filename = "", ""
    label = f"{host}/{filename}" if host and filename else (filename or host or "External source map")
    return {"available": True, "kind": "external", "label": label}


def _sanitize_source_map_directive_for_display(text):
    """Hide source-map payloads/paths from displayed generated-source excerpts."""
    text = str(text or "")
    return re.sub(
        r"(sourceMappingURL\s*=\s*)([^\s*]+)",
        r"\1[source-map-metadata-omitted]",
        text, flags=re.IGNORECASE,
    )


def _script_analysis_report(source, line=0, column=0, *, script_url="", source_map_url="", context_lines=7):
    """Build a bounded human-readable analysis of one live caller script."""
    source = str(source or "")
    if not source:
        return {"ok": False, "reason": "Chromium returned an empty script source.", "text": ""}
    caller_offset = _source_line_column_to_offset(source, line, column)
    raw_excerpt = _script_source_excerpt(
        source, line=line, column=column,
        context_lines=min(5, int(context_lines)), max_line_chars=1800,
    )
    pretty = _js_pretty_print(source, caller_offset)
    function_info = _js_enclosing_function(source, caller_offset)
    primitives = _js_network_primitive_trace(source, caller_offset, function_info)
    map_url = str(source_map_url or "") or _source_map_url_from_source(source)
    map_info = _sanitize_source_map_advertisement(script_url, map_url)
    if map_info.get("kind") == "inline":
        decoded = _decode_inline_source_map(
            map_url,
            max(0, int(line or 1) - 1),
            max(0, int(column or 1) - 1),
        )
        if decoded:
            map_info.update(decoded)

    pretty_excerpt = None
    if pretty.get("ok"):
        pretty_excerpt = _script_source_excerpt(
            pretty.get("text") or "",
            pretty.get("line") or 1,
            pretty.get("column") or 1,
            context_lines=int(context_lines),
            max_line_chars=1800,
            max_total_chars=18000,
        )

    function_excerpt = ""
    if function_info.get("found"):
        fn_text = source[int(function_info["start"]):int(function_info["end"])]
        if len(fn_text) <= 120_000:
            fn_pretty = _js_pretty_print(
                fn_text,
                max(0, caller_offset - int(function_info["start"])),
                max_chars=120_000,
            )
            if fn_pretty.get("ok"):
                fn_excerpt = _script_source_excerpt(
                    fn_pretty.get("text") or "",
                    fn_pretty.get("line") or 1,
                    fn_pretty.get("column") or 1,
                    context_lines=10,
                    max_line_chars=1800,
                    max_total_chars=24000,
                )
                if fn_excerpt.get("ok"):
                    function_excerpt = fn_excerpt.get("text") or ""

    return {
        "ok": True,
        "source_chars": len(source),
        "line_count": max(1, source.count("\n") + 1),
        "raw_text": _sanitize_source_map_directive_for_display(raw_excerpt.get("text")) if raw_excerpt.get("ok") else "",
        "pretty_text": _sanitize_source_map_directive_for_display(pretty_excerpt.get("text")) if pretty_excerpt and pretty_excerpt.get("ok") else "",
        "pretty_line": int(pretty.get("line") or 0),
        "pretty_column": int(pretty.get("column") or 0),
        "pretty_ok": bool(pretty.get("ok")),
        "pretty_reason": str(pretty.get("reason") or ""),
        "function_found": bool(function_info.get("found")),
        "function_signature": str(function_info.get("signature") or "")[:360],
        "function_text": function_excerpt,
        "network_primitives": primitives,
        "source_map": map_info,
    }


def _cdp_call_capture_matching_events(
    ws, method, params=None, *, event_method="", event_predicate=None,
    message_id=1, timeout=3.0,
):
    """CDP call that retains only matching transient events until response."""
    lock = getattr(ws, "_cdp_lock", None)
    if lock is None:
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
        except Exception:
            pass
        ws.settimeout(timeout)
        ws.send(json.dumps({"id": next_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        matches = []
        result = None
        while time.monotonic() < deadline:
            raw = ws.recv()
            payload = json.loads(raw)
            if payload.get("id") == next_id:
                if "error" in payload:
                    raise RuntimeError(f"CDP {method} failed: {payload['error']}")
                result = payload.get("result", {})
                break
            if event_method and payload.get("method") == event_method:
                event_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                if event_predicate is None or event_predicate(event_params):
                    matches.append(event_params)
        if result is None:
            raise RuntimeError(f"Timed out waiting for CDP {method}")
        try:
            ws.settimeout(0.03)
            for _ in range(24):
                try:
                    payload = json.loads(ws.recv())
                except (socket.timeout, TimeoutError):
                    break
                except Exception:
                    break
                if event_method and payload.get("method") == event_method:
                    event_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                    if event_predicate is None or event_predicate(event_params):
                        matches.append(event_params)
        finally:
            try:
                ws.settimeout(timeout)
            except Exception:
                pass
        return result, matches


def _audit_source_name(value, *, document_url=""):
    """Return a privacy-bounded source label for one CDP script URL.

    Only origin hostname + final filename are retained. Query strings, fragments
    and the rest of the path are intentionally discarded. When a call frame
    points at the current document, label it as inline/document code instead of
    leaking the document path into the socket audit.
    """
    raw = str(value or "")
    try:
        parts = urlsplit(raw)
    except Exception:
        return {"host": "", "file": "", "kind": "unknown"}
    scheme = str(parts.scheme or "").lower()
    internal_id = _audit_internal_source_id(raw)
    if internal_id:
        return {
            "host": "", "file": f"internal:{internal_id}"[:180],
            "kind": "tekzite-internal", "internal_id": internal_id,
        }
    host = str(parts.hostname or "").strip().rstrip(".").lower()[:253]
    try:
        doc = urlsplit(str(document_url or ""))
        same_document = bool(
            document_url and scheme == str(doc.scheme or "").lower()
            and host == str(doc.hostname or "").strip().rstrip(".").lower()
            and (parts.path or "/") == (doc.path or "/")
        )
    except Exception:
        same_document = False
    if same_document:
        return {"host": host, "file": "(inline/document)", "kind": "inline"}
    path = str(parts.path or "")
    try:
        filename = unquote(path.rsplit("/", 1)[-1])
    except Exception:
        filename = path.rsplit("/", 1)[-1]
    filename = filename.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()[:180]
    if scheme == "chrome-extension":
        return {"host": host, "file": filename or "(extension script)", "kind": "extension"}
    if scheme in {"http", "https"}:
        return {"host": host, "file": filename or "(document)", "kind": "web"}
    if scheme == "blob":
        return {"host": host, "file": "(blob script)", "kind": "blob"}
    if raw:
        return {"host": host, "file": "(anonymous script)", "kind": scheme or "other"}
    return {"host": "", "file": "(anonymous script)", "kind": "anonymous"}


def _audit_stack_frames(initiator, *, document_url="", limit=8):
    """Extract a sanitized JavaScript call chain from a CDP Initiator.

    CDP line/column numbers are zero-based; user-facing values are converted to
    one-based coordinates. No full source URL is retained.
    """
    initiator = initiator if isinstance(initiator, dict) else {}
    out = []
    seen = set()

    def visit(stack, depth=0):
        if len(out) >= int(limit) or depth > 6 or not isinstance(stack, dict):
            return
        description = str(stack.get("description") or "").replace("\r", " ").replace("\n", " ").strip()[:160]
        if depth and description and len(out) < int(limit):
            label = f"[async] {description}"
            out.append({
                "host": "", "file": "", "kind": "async", "function": description,
                "line": 0, "column": 0, "label": label[:520], "script_id": "",
            })
        frames = stack.get("callFrames") if isinstance(stack.get("callFrames"), list) else []
        for frame in frames:
            if len(out) >= int(limit) or not isinstance(frame, dict):
                break
            source = _audit_source_name(frame.get("url"), document_url=document_url)
            function_name = str(frame.get("functionName") or "(anonymous)").replace("\r", " ").replace("\n", " ").strip()[:160]
            try:
                line = max(0, int(frame.get("lineNumber"))) + 1 if frame.get("lineNumber") is not None else 0
            except Exception:
                line = 0
            try:
                column = max(0, int(frame.get("columnNumber"))) + 1 if frame.get("columnNumber") is not None else 0
            except Exception:
                column = 0
            key = (source.get("host"), source.get("file"), function_name, line, column)
            if key in seen:
                continue
            seen.add(key)
            host = str(source.get("host") or "")
            filename = str(source.get("file") or "")
            internal_id = str(source.get("internal_id") or "")
            if internal_id:
                source_label = f"Tekzite Browser internal: {internal_id}"
            else:
                source_label = f"{host}/{filename}" if host and filename else (filename or host or "(anonymous script)")
            location = source_label
            if line:
                location += f":{line}"
                if column:
                    location += f":{column}"
            label = f"{function_name} @ {location}" if function_name else location
            out.append({
                "host": host[:253], "file": filename[:180], "kind": str(source.get("kind") or "")[:32],
                "function": function_name, "line": line, "column": column, "label": label[:520],
                # Keep only the opaque target-local CDP script id.  It lets the
                # details panel request a source excerpt on demand without
                # retaining the full script URL or source in the audit ledger.
                "script_id": str(frame.get("scriptId") or "")[:128],
                "internal_id": internal_id[:180],
            })
        parent = stack.get("parent")
        if isinstance(parent, dict):
            visit(parent, depth + 1)

    stack = initiator.get("stack") if isinstance(initiator.get("stack"), dict) else None
    if stack is None and isinstance(initiator.get("stackTrace"), dict):
        stack = initiator.get("stackTrace")
    visit(stack or {})

    # Parser initiators do not have a JavaScript call frame. Preserve the
    # source line honestly so the UI says parser/document rather than inventing
    # a script caller.
    if not out and str(initiator.get("type") or "").lower() == "parser":
        source = _audit_source_name(initiator.get("url") or document_url, document_url=document_url)
        try:
            line = max(0, int(initiator.get("lineNumber"))) + 1 if initiator.get("lineNumber") is not None else 0
        except Exception:
            line = 0
        try:
            column = max(0, int(initiator.get("columnNumber"))) + 1 if initiator.get("columnNumber") is not None else 0
        except Exception:
            column = 0
        host = str(source.get("host") or "")
        location = f"{host}/(document)" if host else "(document)"
        if line:
            location += f":{line}"
            if column:
                location += f":{column}"
        out.append({
            "host": host[:253], "file": "(document)", "kind": "parser",
            "function": "parser", "line": line, "column": column,
            "label": f"parser @ {location}"[:520],
        })
    return out


def _audit_initiator_host(initiator, fallback=""):
    """Extract only the hostname from an initiator URL/stack."""
    initiator = initiator if isinstance(initiator, dict) else {}
    _scheme, host, _port = _audit_url_parts(initiator.get("url"))
    if host and _scheme in {"http", "https", "ws", "wss", "chrome-extension"}:
        return host
    stack = initiator.get("stack") if isinstance(initiator.get("stack"), dict) else {}
    frames = stack.get("callFrames") if isinstance(stack.get("callFrames"), list) else []
    for frame in frames[:12]:
        if not isinstance(frame, dict):
            continue
        _scheme, host, _port = _audit_url_parts(frame.get("url"))
        if host and _scheme in {"http", "https", "ws", "wss", "chrome-extension"}:
            return host
    parent = stack.get("parent") if isinstance(stack.get("parent"), dict) else {}
    frames = parent.get("callFrames") if isinstance(parent.get("callFrames"), list) else []
    for frame in frames[:8]:
        if not isinstance(frame, dict):
            continue
        _scheme, host, _port = _audit_url_parts(frame.get("url"))
        if host and _scheme in {"http", "https", "ws", "wss", "chrome-extension"}:
            return host
    return str(fallback or "")[:253]



def _audit_site_key(host):
    """Return a conservative registrable-site heuristic for display only.

    Tekzite intentionally does not ship or remotely fetch a public-suffix list
    just for the live audit.  Common second-level country suffixes are handled
    locally; ambiguous cases are labelled heuristic in the UI rather than being
    treated as a security boundary.
    """
    host = str(host or "").strip().rstrip(".").lower()
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return host
    common_sld = {
        "ac", "co", "com", "edu", "gov", "net", "org",
        "asn", "id", "ne", "or", "go", "lg",
    }
    if len(labels[-1]) == 2 and labels[-2] in common_sld and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _audit_domain_relation(host, target_host):
    """Describe destination-vs-page hostname relation without overclaiming."""
    host = str(host or "").strip().rstrip(".").lower()
    target_host = str(target_host or "").strip().rstrip(".").lower()
    if not host or not target_host:
        return "Unknown"
    if host == target_host:
        return "Same host"
    if host.endswith("." + target_host) or target_host.endswith("." + host):
        return "Parent/subdomain"
    a = _audit_site_key(host)
    b = _audit_site_key(target_host)
    if a and b and a == b:
        return "Same site (heuristic)"
    return "Cross-site"

def _audit_purpose(scope, initiator_type, resource_type, internal_source_id=""):
    internal_source_id = str(internal_source_id or "").strip("/")
    if internal_source_id:
        known = {
            "page-state/favicon": "Tekzite favicon fetch",
        }
        return known.get(internal_source_id, f"Tekzite internal ({internal_source_id})")
    scope = str(scope or "Other Chromium target")
    initiator_type = str(initiator_type or "other").strip().lower()
    resource_type = str(resource_type or "Other")
    resource_key = resource_type.strip().lower()
    if scope == "Page":
        if resource_key == "document":
            return "Page navigation"
        if resource_key == "websocket":
            return "Page WebSocket"
        if resource_key == "eventsource":
            return "Page EventSource"
        if resource_key == "xhr":
            return "Page XHR"
        if resource_key == "fetch":
            return "Page fetch"
        if resource_key in {"ping", "beacon"}:
            return "Page beacon/ping"
        if initiator_type == "parser":
            return "Page parser"
        if initiator_type == "script":
            return "Page script"
        if initiator_type == "preload":
            return "Page preload"
        if initiator_type == "preflight":
            return "CORS preflight"
        return "Page request"
    if scope == "Extension":
        return "Extension request"
    if scope == "Service worker":
        return "Service-worker request"
    if scope == "Page worker":
        return "Worker request"
    if scope == "Browser internal":
        return "Browser-internal request"
    return f"{scope} request"


class _NetworkRequestAuditMonitor:
    """RAM-only CDP Network observer for live socket attribution.

    Each target gets a dedicated DevTools websocket so request events cannot
    interfere with Tekzite's input/control lanes. Only host-level metadata is
    retained: destination host/port, resource type, target scope, initiator
    type/hostname and a sanitized JavaScript call chain (origin host, final
    filename, function, line/column). Full URLs, query strings, headers,
    cookies, script contents and request/response bodies are discarded
    immediately.
    """

    TARGET_TYPES = {
        "page", "service_worker", "worker", "shared_worker", "background_page", "webview"
    }

    def __init__(self, port):
        self.port = int(port or 0)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._manager = None
        self._watchers = {}
        self._records = []
        self._by_request = {}
        self._status = "starting"
        self._reason = ""
        self._started_at = time.time()
        self._last_target_scan = 0.0

    def start(self):
        if self._manager and self._manager.is_alive():
            return
        self._manager = threading.Thread(
            target=self._manager_loop, name="TekziteRequestAudit", daemon=True,
        )
        self._manager.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            watchers = list(self._watchers.values())
        for watcher in watchers:
            watcher.get("stop") and watcher["stop"].set()
            ws = watcher.get("ws")
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
        thread = self._manager
        if thread and thread.is_alive():
            thread.join(timeout=0.35)
        with self._lock:
            self._watchers.clear()
            self._status = "stopped"

    def _manager_loop(self):
        self._status = "running"
        while not self._stop.is_set():
            try:
                targets = _devtools_json(self.port, "/json/list", timeout=0.35)
                self._last_target_scan = time.time()
                current = {}
                for target in list(targets or []):
                    target_id = str(target.get("id") or "")
                    ws_url = str(target.get("webSocketDebuggerUrl") or "")
                    target_type = str(target.get("type") or "").lower()
                    if not target_id or not ws_url or target_type not in self.TARGET_TYPES:
                        continue
                    current[target_id] = target
                    with self._lock:
                        existing = self._watchers.get(target_id)
                    if existing and existing.get("thread") and existing["thread"].is_alive() and existing.get("ws_url") == ws_url:
                        continue
                    if existing:
                        existing.get("stop") and existing["stop"].set()
                    stop_event = threading.Event()
                    scope, sanitized_type, target_host = _audit_target_scope(target)
                    watcher = {
                        "target_id": target_id, "ws_url": ws_url, "stop": stop_event,
                        # Retain only host-level target metadata. The /json/list
                        # target URL is parsed during this scan and then discarded.
                        "target": {
                            "id": target_id, "type": sanitized_type, "scope": scope,
                            "target_host": target_host,
                        },
                        "ws": None,
                    }
                    thread = threading.Thread(
                        target=self._watch_target, args=(watcher,),
                        name=f"TekziteRequestAudit-{target_id[:8]}", daemon=True,
                    )
                    watcher["thread"] = thread
                    with self._lock:
                        self._watchers[target_id] = watcher
                    thread.start()
                with self._lock:
                    stale = [tid for tid in self._watchers if tid not in current]
                    for tid in stale:
                        watcher = self._watchers.pop(tid, None)
                        if watcher:
                            watcher.get("stop") and watcher["stop"].set()
                            ws = watcher.get("ws")
                            if ws is not None:
                                try:
                                    ws.close()
                                except Exception:
                                    pass
                self._reason = ""
            except Exception as exc:
                self._reason = f"CDP request attribution temporarily unavailable: {type(exc).__name__}"
            self._purge()
            self._stop.wait(0.75)

    def _watch_target(self, watcher):
        target = watcher.get("target") or {}
        stop_event = watcher["stop"]
        ws = None
        try:
            ws = _open_devtools_websocket(watcher["ws_url"], timeout=1.0)
            watcher["ws"] = ws
            _cdp_call(ws, "Network.enable", {}, message_id=1, timeout=1.5)
            ws.settimeout(0.75)
            while not self._stop.is_set() and not stop_event.is_set():
                try:
                    raw = ws.recv()
                except (socket.timeout, TimeoutError):
                    continue
                except Exception:
                    break
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                method = str(payload.get("method") or "")
                params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                if method == "Network.requestWillBeSent":
                    self._record_request(target, params)
                elif method == "Network.responseReceived":
                    self._record_response(target, params)
                elif method == "Network.loadingFinished":
                    self._record_loading_finished(target, params)
                elif method == "Network.loadingFailed":
                    self._record_loading_failed(target, params)
                elif method == "Network.requestServedFromCache":
                    self._record_served_from_cache(target, params)
                elif method == "Network.webSocketCreated":
                    self._record_websocket_created(target, params)
                elif method == "Network.webSocketClosed":
                    self._record_websocket_closed(target, params)
        except Exception:
            pass
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            watcher["ws"] = None

    def _record_request(self, target, params):
        request = params.get("request") if isinstance(params.get("request"), dict) else {}
        scheme, host, port = _audit_url_parts(request.get("url"))
        if scheme not in {"http", "https", "ws", "wss"} or not host:
            return
        if target.get("scope"):
            scope = str(target.get("scope") or "Other Chromium target")
            target_type = str(target.get("type") or "other")
            target_host = str(target.get("target_host") or "")[:253]
        else:
            scope, target_type, target_host = _audit_target_scope(target)
        document_host = _audit_url_parts(params.get("documentURL"))[1]
        if document_host:
            target_host = document_host
        initiator = params.get("initiator") if isinstance(params.get("initiator"), dict) else {}
        initiator_type = str(initiator.get("type") or "other").strip().lower()[:32]
        initiator_host = _audit_initiator_host(initiator, fallback=target_host)
        script_frames = _audit_stack_frames(initiator, document_url=params.get("documentURL"), limit=8)
        resource_type = str(params.get("type") or "Other")[:48]
        now = time.time()
        target_id = str(target.get("id") or "")
        request_id = str(params.get("requestId") or "")

        # CORS preflight often points at the request that caused it instead of
        # carrying a fresh JS stack. Inherit the already-sanitized caller chain
        # so the audit can still answer which script caused the network action.
        parent_request_id = str(initiator.get("requestId") or "")
        if not script_frames and parent_request_id:
            with self._lock:
                parent = self._by_request.get((target_id, parent_request_id))
                if parent is not None:
                    script_frames = [dict(frame) for frame in list(parent.get("script_stack") or [])[:8]]
                    if not initiator_host:
                        initiator_host = str(parent.get("initiator_host") or "")[:253]

        top_script = dict(script_frames[0]) if script_frames else {}
        internal_source_id = str(top_script.get("internal_id") or "")[:180]
        initiator_label = ""
        if internal_source_id:
            initiator_type = "tekzite-internal"
            initiator_host = ""
            initiator_label = "Tekzite Browser injected script"
        request_headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
        request_header_names = {str(name or "").strip().lower() for name in request_headers}
        redirect_response = params.get("redirectResponse") if isinstance(params.get("redirectResponse"), dict) else {}
        redirect_from_host = _audit_url_parts(redirect_response.get("url"))[1] if redirect_response else ""
        try:
            redirect_status = int(redirect_response.get("status") or 0)
        except Exception:
            redirect_status = 0
        try:
            wall_time = float(params.get("wallTime") or now)
        except Exception:
            wall_time = now
        try:
            cdp_timestamp = float(params.get("timestamp") or 0.0)
        except Exception:
            cdp_timestamp = 0.0
        record = {
            "host": host,
            "port": int(port or 0),
            "scheme": scheme,
            "method": str(request.get("method") or "GET")[:16],
            "resource_type": resource_type,
            "has_post_data": bool(request.get("hasPostData")),
            "initial_priority": str(request.get("initialPriority") or "")[:32],
            "observed_cookie_header": "cookie" in request_header_names,
            "observed_authorization_header": "authorization" in request_header_names,
            "observed_origin_header": "origin" in request_header_names,
            "observed_referer_header": "referer" in request_header_names or "referrer" in request_header_names,
            "scope": scope,
            "target_type": target_type,
            "target_host": str(target_host or "")[:253],
            "initiator_type": initiator_type,
            "initiator_host": str(initiator_host or "")[:253],
            "initiator_label": initiator_label[:160],
            "internal_source_id": internal_source_id,
            "script_source": str(top_script.get("label") or "")[:520],
            "script_host": str(top_script.get("host") or "")[:253],
            "script_file": str(top_script.get("file") or "")[:180],
            "script_function": str(top_script.get("function") or "")[:160],
            "script_line": int(top_script.get("line") or 0),
            "script_column": int(top_script.get("column") or 0),
            "script_id": str(top_script.get("script_id") or "")[:128],
            "script_stack": [dict(frame) for frame in script_frames[:8]],
            "purpose": _audit_purpose(scope, initiator_type, resource_type, internal_source_id),
            "domain_relation": _audit_domain_relation(host, target_host),
            "target_id": target_id[:128],
            "request_id": request_id[:128],
            "frame_id": str(params.get("frameId") or "")[:128],
            "loader_id": str(params.get("loaderId") or "")[:128],
            "first_seen": now,
            "last_seen": now,
            "wall_time": wall_time,
            "cdp_timestamp": cdp_timestamp,
            "redirect_from_host": str(redirect_from_host or "")[:253],
            "redirect_status": redirect_status,
            "redirect_to_host": "",
            "response_status": 0,
            "response_mime_type": "",
            "response_from_disk_cache": False,
            "response_from_service_worker": False,
            "response_from_prefetch_cache": False,
            "observed_set_cookie_header": False,
            "security_state": "",
            "request_served_from_cache": False,
            "encoded_data_length": 0,
            "loading_failed": False,
            "failure_text": "",
            "blocked_reason": "",
            "cors_error": "",
            "canceled": False,
            "tls_protocol": "",
            "tls_cipher": "",
            "tls_issuer": "",
            "websocket_closed": False,
            "remote_address": "",
            "remote_port": 0,
            "connection_id": "",
            "connection_reused": None,
            "response_protocol": "",
        }
        with self._lock:
            if request_id and redirect_from_host:
                previous = self._by_request.get((target_id, request_id))
                if previous is not None:
                    previous["redirect_to_host"] = host[:253]
                    previous["last_seen"] = now
            self._records.append(record)
            if request_id:
                self._by_request[(target_id, request_id)] = record
            if len(self._records) > _REQUEST_AUDIT_MAX_RECORDS:
                removed = self._records[:-_REQUEST_AUDIT_MAX_RECORDS]
                self._records = self._records[-_REQUEST_AUDIT_MAX_RECORDS:]
                removed_ids = {id(row) for row in removed}
                for key, row in list(self._by_request.items()):
                    if id(row) in removed_ids:
                        self._by_request.pop(key, None)

    def _record_websocket_created(self, target, params):
        """Record a WebSocket opener using only sanitized CDP metadata.

        Network.webSocketCreated carries the URL and initiator stack but does
        not expose ordinary HTTP response connection-reuse metadata. Feed it
        through the same request ledger so script callers are visible without
        retaining the full WebSocket URL.
        """
        url = str(params.get("url") or "")
        if not url:
            return
        synthetic = {
            "requestId": params.get("requestId"),
            "timestamp": params.get("timestamp"),
            "type": "WebSocket",
            "initiator": params.get("initiator") if isinstance(params.get("initiator"), dict) else {},
            "request": {"url": url, "method": "GET"},
        }
        self._record_request(target, synthetic)

    def _record_response(self, target, params):
        target_id = str(target.get("id") or "")
        request_id = str(params.get("requestId") or "")
        if not request_id:
            return
        response = params.get("response") if isinstance(params.get("response"), dict) else {}
        remote = _normalize_socket_address(response.get("remoteIPAddress"))
        try:
            remote_port = int(response.get("remotePort") or 0)
        except Exception:
            remote_port = 0
        with self._lock:
            row = self._by_request.get((target_id, request_id))
            if row is not None:
                row["last_seen"] = time.time()
                if remote:
                    row["remote_address"] = remote[:128]
                if remote_port:
                    row["remote_port"] = remote_port
                if response.get("connectionId") is not None:
                    row["connection_id"] = str(response.get("connectionId"))[:96]
                if "connectionReused" in response:
                    row["connection_reused"] = bool(response.get("connectionReused"))
                row["response_protocol"] = str(response.get("protocol") or "")[:32]
                try:
                    row["response_status"] = int(response.get("status") or 0)
                except Exception:
                    row["response_status"] = 0
                row["response_mime_type"] = str(response.get("mimeType") or "")[:160]
                row["response_from_disk_cache"] = bool(response.get("fromDiskCache"))
                row["response_from_service_worker"] = bool(response.get("fromServiceWorker"))
                row["response_from_prefetch_cache"] = bool(response.get("fromPrefetchCache"))
                response_headers = response.get("headers") if isinstance(response.get("headers"), dict) else {}
                response_header_names = {str(name or "").strip().lower() for name in response_headers}
                row["observed_set_cookie_header"] = "set-cookie" in response_header_names or "set-cookie2" in response_header_names
                row["security_state"] = str(response.get("securityState") or "")[:32]
                security = response.get("securityDetails") if isinstance(response.get("securityDetails"), dict) else {}
                row["tls_protocol"] = str(security.get("protocol") or "")[:48]
                row["tls_cipher"] = str(security.get("cipher") or "")[:96]
                row["tls_issuer"] = str(security.get("issuer") or "")[:180]

    def _request_row(self, target, params):
        target_id = str(target.get("id") or "")
        request_id = str(params.get("requestId") or "")
        if not request_id:
            return None
        with self._lock:
            return self._by_request.get((target_id, request_id))

    def _record_loading_finished(self, target, params):
        row = self._request_row(target, params)
        if row is None:
            return
        try:
            encoded = max(0, int(float(params.get("encodedDataLength") or 0)))
        except Exception:
            encoded = 0
        with self._lock:
            row["last_seen"] = time.time()
            row["encoded_data_length"] = encoded

    def _record_loading_failed(self, target, params):
        row = self._request_row(target, params)
        if row is None:
            return
        cors = params.get("corsErrorStatus") if isinstance(params.get("corsErrorStatus"), dict) else {}
        with self._lock:
            row["last_seen"] = time.time()
            row["loading_failed"] = True
            row["failure_text"] = str(params.get("errorText") or "")[:240]
            row["blocked_reason"] = str(params.get("blockedReason") or "")[:96]
            row["cors_error"] = str(cors.get("corsError") or "")[:128]
            row["canceled"] = bool(params.get("canceled"))

    def _record_served_from_cache(self, target, params):
        row = self._request_row(target, params)
        if row is None:
            return
        with self._lock:
            row["last_seen"] = time.time()
            row["request_served_from_cache"] = True

    def _record_websocket_closed(self, target, params):
        row = self._request_row(target, params)
        if row is None:
            return
        with self._lock:
            row["last_seen"] = time.time()
            row["websocket_closed"] = True

    def script_source_analysis(self, target_id, script_id, line=0, column=0, context_lines=7):
        """Fetch and locally analyze one caller script on demand.

        The complete generated source and any inline source map live only inside
        this call. The returned object contains bounded excerpts/metadata only.
        External source maps are advertised but never fetched automatically, so
        the act of inspecting a connection cannot create a hidden extra request.
        """
        target_id = str(target_id or "")[:128]
        script_id = str(script_id or "")[:128]
        if not target_id or not script_id:
            return {"ok": False, "reason": "No live CDP script identifier is available for this caller.", "text": ""}
        with self._lock:
            watcher = self._watchers.get(target_id)
            ws_url = str((watcher or {}).get("ws_url") or "")
        if not ws_url:
            return {"ok": False, "reason": "The Chromium target that owned this script is no longer live.", "text": ""}
        ws = None
        try:
            ws = _open_devtools_websocket(ws_url, timeout=2.0)
            _result, events = _cdp_call_capture_matching_events(
                ws, "Debugger.enable", {},
                event_method="Debugger.scriptParsed",
                event_predicate=lambda params: str(params.get("scriptId") or "") == script_id,
                message_id=1, timeout=3.0,
            )
            metadata = dict(events[-1]) if events else {}
            result = _cdp_call(
                ws, "Debugger.getScriptSource", {"scriptId": script_id},
                message_id=2, timeout=4.0,
            )
            source = str((result or {}).get("scriptSource") or "")
            analysis = _script_analysis_report(
                source, line=line, column=column, context_lines=context_lines,
                script_url=str(metadata.get("url") or ""),
                source_map_url=str(metadata.get("sourceMapURL") or ""),
            )
            analysis["target_id"] = target_id
            analysis["script_id"] = script_id
            analysis["script_metadata_seen"] = bool(metadata)
            return analysis
        except Exception as exc:
            return {
                "ok": False,
                "reason": f"Could not analyze the live Chromium script source: {type(exc).__name__}",
                "text": "", "target_id": target_id, "script_id": script_id,
            }
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def script_source_excerpt(self, target_id, script_id, line=0, column=0, context_lines=3):
        """Fetch one caller's source from Chromium on demand.

        A fresh DevTools websocket is used so source retrieval cannot consume or
        reorder Network events on the long-lived audit channel.  The complete
        source exists only in this local call and is reduced immediately to the
        bounded excerpt returned to the UI.
        """
        target_id = str(target_id or "")[:128]
        script_id = str(script_id or "")[:128]
        if not target_id or not script_id:
            return {"ok": False, "reason": "No live CDP script identifier is available for this caller.", "text": ""}
        with self._lock:
            watcher = self._watchers.get(target_id)
            ws_url = str((watcher or {}).get("ws_url") or "")
        if not ws_url:
            return {"ok": False, "reason": "The Chromium target that owned this script is no longer live.", "text": ""}
        ws = None
        try:
            ws = _open_devtools_websocket(ws_url, timeout=2.0)
            _cdp_call(ws, "Debugger.enable", {}, message_id=1, timeout=2.5)
            result = _cdp_call(
                ws, "Debugger.getScriptSource", {"scriptId": script_id},
                message_id=2, timeout=3.5,
            )
            source = str((result or {}).get("scriptSource") or "")
            excerpt = _script_source_excerpt(
                source, line=line, column=column, context_lines=context_lines,
            )
            excerpt["target_id"] = target_id
            excerpt["script_id"] = script_id
            return excerpt
        except Exception as exc:
            return {
                "ok": False,
                "reason": f"Could not read the live Chromium script source: {type(exc).__name__}",
                "text": "", "target_id": target_id, "script_id": script_id,
            }
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    def _purge(self):
        cutoff = time.time() - _REQUEST_AUDIT_MAX_AGE
        with self._lock:
            if not self._records:
                return
            self._records = [row for row in self._records if float(row.get("last_seen", 0.0) or 0.0) >= cutoff]
            live_ids = {id(row) for row in self._records}
            for key, row in list(self._by_request.items()):
                if id(row) not in live_ids:
                    self._by_request.pop(key, None)

    def snapshot(self):
        self._purge()
        with self._lock:
            rows = [dict(row) for row in self._records]
            target_count = sum(1 for watcher in self._watchers.values() if watcher.get("thread") and watcher["thread"].is_alive())
            status = self._status
            reason = self._reason
        hosts = {}
        endpoints = {}
        for row in rows:
            host = str(row.get("host") or "")
            if not host:
                continue
            entry = hosts.setdefault(host, {
                "host": host, "count": 0, "last_seen": 0.0,
                "scopes": {}, "resource_types": {}, "initiators": {}, "target_hosts": {},
                "scripts": {}, "latest": None,
            })
            entry["count"] += 1
            seen = float(row.get("last_seen", 0.0) or 0.0)
            entry["last_seen"] = max(float(entry.get("last_seen", 0.0) or 0.0), seen)
            for field, bucket in (("scope", "scopes"), ("resource_type", "resource_types"), ("target_host", "target_hosts")):
                value = str(row.get(field) or "")
                if value:
                    entry[bucket][value] = int(entry[bucket].get(value, 0) or 0) + 1
            init_type = str(row.get("initiator_type") or "")
            init_host = str(row.get("initiator_host") or "")
            init_label = str(row.get("initiator_label") or "") or (init_type + (f" @ {init_host}" if init_host else ""))
            if init_label:
                entry["initiators"][init_label] = int(entry["initiators"].get(init_label, 0) or 0) + 1
            script_label = str(row.get("script_source") or "")
            if script_label:
                entry["scripts"][script_label] = int(entry["scripts"].get(script_label, 0) or 0) + 1
            if entry["latest"] is None or seen >= float(entry["latest"].get("last_seen", 0.0) or 0.0):
                entry["latest"] = row
            remote = _normalize_socket_address(row.get("remote_address"))
            remote_port = int(row.get("remote_port") or 0)
            if remote and remote_port:
                key = (remote, remote_port)
                previous = endpoints.get(key)
                if previous is None or seen >= float(previous.get("last_seen", 0.0) or 0.0):
                    endpoints[key] = row

        host_rows = []
        for entry in hosts.values():
            latest = dict(entry.pop("latest") or {})
            scopes = sorted(entry["scopes"], key=lambda value: (-entry["scopes"][value], value))
            resources = sorted(entry["resource_types"], key=lambda value: (-entry["resource_types"][value], value))
            initiators = sorted(entry["initiators"], key=lambda value: (-entry["initiators"][value], value))
            target_hosts = sorted(entry["target_hosts"], key=lambda value: (-entry["target_hosts"][value], value))
            scripts = sorted(entry["scripts"], key=lambda value: (-entry["scripts"][value], value))
            host_rows.append({
                "host": entry["host"], "count": entry["count"], "last_seen": entry["last_seen"],
                "scopes": scopes[:4], "resource_types": resources[:6], "initiators": initiators[:4],
                "target_hosts": target_hosts[:4], "scripts": scripts[:6],
                "purpose": str(latest.get("purpose") or ""),
                "latest_scope": str(latest.get("scope") or ""),
                "latest_resource_type": str(latest.get("resource_type") or ""),
                "latest_initiator_type": str(latest.get("initiator_type") or ""),
                "latest_initiator_host": str(latest.get("initiator_host") or ""),
                "latest_initiator_label": str(latest.get("initiator_label") or ""),
                "latest_target_host": str(latest.get("target_host") or ""),
                "latest_script_source": str(latest.get("script_source") or ""),
                "latest_script_host": str(latest.get("script_host") or ""),
                "latest_script_file": str(latest.get("script_file") or ""),
                "latest_script_function": str(latest.get("script_function") or ""),
                "latest_script_line": int(latest.get("script_line") or 0),
                "latest_script_column": int(latest.get("script_column") or 0),
                "latest_script_id": str(latest.get("script_id") or "")[:128],
                "latest_target_id": str(latest.get("target_id") or "")[:128],
                "latest_script_stack": [dict(frame) for frame in list(latest.get("script_stack") or [])[:8]],
                "latest_domain_relation": str(latest.get("domain_relation") or ""),
                "latest_method": str(latest.get("method") or ""),
                "latest_response_status": int(latest.get("response_status") or 0),
                "latest_response_mime_type": str(latest.get("response_mime_type") or ""),
                "latest_encoded_data_length": int(latest.get("encoded_data_length") or 0),
                "latest_loading_failed": bool(latest.get("loading_failed")),
            })
        host_rows.sort(key=lambda row: float(row.get("last_seen", 0.0) or 0.0), reverse=True)
        endpoint_rows = []
        for (address, port), row in endpoints.items():
            endpoint_rows.append({
                "remote_address": address, "remote_port": port,
                "host": row.get("host") or "", "purpose": row.get("purpose") or "",
                "scope": row.get("scope") or "", "resource_type": row.get("resource_type") or "",
                "initiator_type": row.get("initiator_type") or "", "initiator_host": row.get("initiator_host") or "",
                "initiator_label": row.get("initiator_label") or "", "internal_source_id": row.get("internal_source_id") or "",
                "target_host": row.get("target_host") or "", "last_seen": row.get("last_seen") or 0.0,
                "script_source": row.get("script_source") or "",
                "script_host": row.get("script_host") or "", "script_file": row.get("script_file") or "",
                "script_function": row.get("script_function") or "",
                "script_line": int(row.get("script_line") or 0), "script_column": int(row.get("script_column") or 0),
                "script_id": str(row.get("script_id") or "")[:128],
                "target_id": str(row.get("target_id") or "")[:128],
                "script_stack": [dict(frame) for frame in list(row.get("script_stack") or [])[:8]],
                "method": row.get("method") or "GET",
                "domain_relation": row.get("domain_relation") or "Unknown",
                "response_status": int(row.get("response_status") or 0),
                "response_mime_type": row.get("response_mime_type") or "",
                "encoded_data_length": int(row.get("encoded_data_length") or 0),
                "loading_failed": bool(row.get("loading_failed")),
                "connection_id": row.get("connection_id") or "",
                "connection_reused": row.get("connection_reused"),
                "response_protocol": row.get("response_protocol") or "",
            })
        request_rows = []
        for row in rows[-512:]:
            request_rows.append({
                "host": row.get("host") or "", "port": int(row.get("port") or 0),
                "first_seen": float(row.get("first_seen") or 0.0), "last_seen": float(row.get("last_seen") or 0.0),
                "wall_time": float(row.get("wall_time") or 0.0),
                "purpose": row.get("purpose") or "", "scope": row.get("scope") or "",
                "resource_type": row.get("resource_type") or "",
                "method": row.get("method") or "GET", "has_post_data": bool(row.get("has_post_data")),
                "initial_priority": row.get("initial_priority") or "",
                "observed_cookie_header": bool(row.get("observed_cookie_header")),
                "observed_authorization_header": bool(row.get("observed_authorization_header")),
                "observed_origin_header": bool(row.get("observed_origin_header")),
                "observed_referer_header": bool(row.get("observed_referer_header")),
                "observed_set_cookie_header": bool(row.get("observed_set_cookie_header")),
                "security_state": row.get("security_state") or "",
                "domain_relation": row.get("domain_relation") or "Unknown",
                "initiator_type": row.get("initiator_type") or "", "initiator_host": row.get("initiator_host") or "",
                "initiator_label": row.get("initiator_label") or "", "internal_source_id": row.get("internal_source_id") or "",
                "target_host": row.get("target_host") or "",
                "frame_id": row.get("frame_id") or "", "loader_id": row.get("loader_id") or "",
                "remote_address": row.get("remote_address") or "", "remote_port": int(row.get("remote_port") or 0),
                "script_source": row.get("script_source") or "", "script_host": row.get("script_host") or "",
                "script_file": row.get("script_file") or "", "script_function": row.get("script_function") or "",
                "script_line": int(row.get("script_line") or 0), "script_column": int(row.get("script_column") or 0),
                "script_id": str(row.get("script_id") or "")[:128],
                "target_id": str(row.get("target_id") or "")[:128],
                "script_stack": [dict(frame) for frame in list(row.get("script_stack") or [])[:8]],
                "redirect_from_host": row.get("redirect_from_host") or "",
                "redirect_status": int(row.get("redirect_status") or 0),
                "redirect_to_host": row.get("redirect_to_host") or "",
                "response_status": int(row.get("response_status") or 0),
                "response_mime_type": row.get("response_mime_type") or "",
                "response_from_disk_cache": bool(row.get("response_from_disk_cache")),
                "response_from_service_worker": bool(row.get("response_from_service_worker")),
                "response_from_prefetch_cache": bool(row.get("response_from_prefetch_cache")),
                "request_served_from_cache": bool(row.get("request_served_from_cache")),
                "encoded_data_length": int(row.get("encoded_data_length") or 0),
                "loading_failed": bool(row.get("loading_failed")),
                "failure_text": row.get("failure_text") or "",
                "blocked_reason": row.get("blocked_reason") or "",
                "cors_error": row.get("cors_error") or "",
                "canceled": bool(row.get("canceled")),
                "tls_protocol": row.get("tls_protocol") or "", "tls_cipher": row.get("tls_cipher") or "",
                "tls_issuer": row.get("tls_issuer") or "",
                "websocket_closed": bool(row.get("websocket_closed")),
                "connection_id": row.get("connection_id") or "",
                "connection_reused": row.get("connection_reused"),
                "response_protocol": row.get("response_protocol") or "",
            })
        return {
            "status": status, "reason": reason, "started_at": self._started_at,
            "target_count": target_count, "request_count": len(rows),
            "hosts": host_rows, "endpoints": endpoint_rows, "requests": request_rows,
        }


def ensure_network_request_audit_monitor(port):
    """Start/reuse the Live Socket View CDP request-attribution monitor."""
    global _REQUEST_AUDIT_MONITOR
    try:
        port = int(port or 0)
    except Exception:
        port = 0
    if not port:
        return {"status": "idle", "reason": "Chromium DevTools is not active.", "hosts": [], "endpoints": []}
    with _REQUEST_AUDIT_LOCK:
        monitor = _REQUEST_AUDIT_MONITOR
        if monitor is None or int(getattr(monitor, "port", 0) or 0) != port or getattr(monitor, "_stop", None).is_set():
            if monitor is not None:
                try:
                    monitor.stop()
                except Exception:
                    pass
            monitor = _NetworkRequestAuditMonitor(port)
            _REQUEST_AUDIT_MONITOR = monitor
            monitor.start()
        return monitor.snapshot()


def get_network_request_script_analysis(target_id, script_id, line=0, column=0, context_lines=7):
    """Return bounded pretty/source-map/network-call analysis for one caller."""
    with _REQUEST_AUDIT_LOCK:
        monitor = _REQUEST_AUDIT_MONITOR
    if monitor is None or getattr(monitor, "_stop", None).is_set():
        return {"ok": False, "reason": "The request-attribution monitor is not running.", "text": ""}
    return monitor.script_source_analysis(
        target_id, script_id, line=line, column=column, context_lines=context_lines,
    )


def get_network_request_script_excerpt(target_id, script_id, line=0, column=0, context_lines=3):
    """Return a RAM-only source excerpt for one Live Socket View caller."""
    with _REQUEST_AUDIT_LOCK:
        monitor = _REQUEST_AUDIT_MONITOR
    if monitor is None or getattr(monitor, "_stop", None).is_set():
        return {"ok": False, "reason": "The request-attribution monitor is not running.", "text": ""}
    return monitor.script_source_excerpt(
        target_id, script_id, line=line, column=column, context_lines=context_lines,
    )



def network_request_audit_snapshot():
    """Return the current RAM-only causal request timeline for the live view."""
    with _REQUEST_AUDIT_LOCK:
        monitor = _REQUEST_AUDIT_MONITOR
    if monitor is None or getattr(monitor, "_stop", None).is_set():
        return {"status": "idle", "reason": "The request-attribution monitor is not running.", "requests": []}
    return monitor.snapshot()

def stop_network_request_audit_monitor():
    global _REQUEST_AUDIT_MONITOR
    with _REQUEST_AUDIT_LOCK:
        monitor = _REQUEST_AUDIT_MONITOR
        _REQUEST_AUDIT_MONITOR = None
    if monitor is not None:
        try:
            monitor.stop()
        except Exception:
            pass


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
    # v9.3: latency-only lanes do not need Network domain setup. Sending
    # Network.enable + setExtraHTTPHeaders on the critical input socket added
    # two CDP round trips before the first click could be proven. Keep network
    # configuration on general/control channels and make input/scroll/hover/
    # cursor sockets immediately usable after the websocket handshake.
    latency_only_purposes = {"input", "scroll", "hover", "cursor"}
    if purpose in latency_only_purposes:
        channel["privacy_headers"] = False
        channel["network_setup_skipped_for_latency"] = True
    else:
        try:
            _cdp_call(ws, "Network.enable", {}, message_id=901, timeout=timeout)
            privacy_headers = {"DNT": "1", "Sec-GPC": "1"}
            strip_referrer = str(os.environ.get("TEKZITE_STRIP_REFERRER", "1")).strip().lower() not in {"0", "false", "no", "off"}
            if strip_referrer:
                privacy_headers["Referer"] = ""
            try:
                _cdp_call(
                    ws, "Network.setExtraHTTPHeaders",
                    {"headers": privacy_headers},
                    message_id=902, timeout=timeout,
                )
            except Exception:
                # Some Chromium builds may reject an empty Referer override.
                # Keep GPC/DNT active and let the bundled DNR rules strip it.
                _cdp_call(
                    ws, "Network.setExtraHTTPHeaders",
                    {"headers": {"DNT": "1", "Sec-GPC": "1"}},
                    message_id=903, timeout=timeout,
                )
            channel["enabled_domains"].add("Network")
            channel["privacy_headers"] = True
            channel["next_message_id"] = max(channel["next_message_id"], 1000)
        except Exception:
            channel["privacy_headers"] = False
    return channel


def _persistent_page_cdp_call(session, method, params=None, *, target_id=None,
                              timeout=5.0, purpose="default", internal_source=None):

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
                call_params = params or {}
                if str(method or "") == "Runtime.evaluate":
                    call_params = _tag_runtime_evaluate_params(
                        call_params, internal_source or f"{purpose}/evaluate",
                    )
                result = _cdp_call(
                    channel["ws"], method, call_params,
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



def warm_embedded_chromium_io_channels(target_id: str = None, timeout: float = 2.0,
                                      purposes=("input", "scroll", "hover")):
    """Pre-open latency-sensitive CDP lanes before the user needs them.

    v8.7 keeps clicks/typing, wheel scrolling, and cosmetic hover/cursor work on
    independent persistent WebSockets.  Chromium serializes calls within one
    page socket, so merely using separate Python workers is not enough. Warming
    all three lanes removes both lock contention and the first-gesture connect
    penalty while the page is still hidden or otherwise idle.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(float(timeout), 8.0))
    if not session or not session.get("port"):
        return False
    warmed = []
    try:
        for purpose in tuple(purposes or ("input",)):
            purpose = str(purpose or "input")
            _get_persistent_page_cdp_channel(
                session, target_id=target_id, timeout=float(timeout), purpose=purpose
            )
            warmed.append(purpose)
        tid = str(target_id or session.get("target_id") or "")
        session["io_channels_warmed_target"] = tid
        session["io_channels_warmed_purposes"] = list(warmed)
        session["io_channels_warmed_at"] = time.monotonic()
        # Retain the v8.6 diagnostics for compatibility with existing tests.
        if "input" in warmed:
            session["input_channel_warmed_target"] = tid
            session["input_channel_warmed_at"] = session["io_channels_warmed_at"]
        return True
    except Exception as exc:
        session["io_channel_warm_error"] = type(exc).__name__
        if "input" not in warmed:
            session["input_channel_warm_error"] = type(exc).__name__
        return False


def _wait_for_embedded_chromium_input_ready(session, target_id: str = None, timeout: float = 1.2):
    """Keep the DWM surface hidden until the renderer consumes real input.

    A paintable compositor frame can arrive a little before Chromium's renderer
    is ready to service CDP input.  v8.8 closes that visible-but-dead gap by
    proving the exact critical input lane before the UI is allowed to reveal the
    DWM thumbnail.  The probe is deliberately harmless: wait for a usable DOM,
    then send one mouseMoved event at (0, 0).
    """
    if not session or not session.get("port"):
        return False
    target_id = str(target_id or session.get("target_id") or "")
    if not target_id:
        return False
    # If the attached-frame gate already proved a semantic laid-out frame for
    # this navigation, skip a duplicate Runtime.evaluate and immediately prove
    # the exact input command path.
    if (session.get("first_frame_probe") == "attached-semantic-geometry"
            and int(session.get("first_frame_generation") or -1) == int(session.get("navigation_generation") or 0)):
        try:
            _persistent_page_cdp_call(
                session, "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": 0.0, "y": 0.0, "button": "none"},
                target_id=target_id, timeout=min(0.30, max(0.08, float(timeout))),
                purpose="input",
            )
            session["input_ready_verified"] = True
            session["input_ready_target"] = target_id
            session["input_ready_ready_state"] = str(session.get("first_frame_ready_state") or "")
            session["input_ready_attempts"] = 1
            session["input_ready_at"] = time.monotonic()
            session["input_ready_reused_frame_proof"] = True
            return True
        except Exception as exc:
            session["input_ready_last_error"] = type(exc).__name__

    deadline = time.monotonic() + max(0.05, float(timeout))
    last_ready = ""
    last_dom = False
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        try:
            state = _persistent_page_cdp_call(
                session, "Runtime.evaluate",
                {
                    "expression": "(() => { const d=document; const b=d.body; const de=d.documentElement; return {ready:String(d.readyState||''), dom:!!(de&&b&&de.clientWidth>0&&de.clientHeight>0), interactive:!!(b&&b.querySelector&&b.querySelector('input,textarea,button,a[href],[contenteditable=\"true\"]'))}; })()",
                    "returnByValue": True,
                },
                target_id=target_id, timeout=min(0.35, max(0.08, deadline-time.monotonic())),
                purpose="input",
            )
            value = (((state or {}).get("result") or {}).get("value") or {})
            last_ready = str(value.get("ready") or "")
            last_dom = bool(value.get("dom"))
            # Do not require load/DOMContentLoaded: ordinary Chromium is clickable
            # while a page is still loading.  We only need a real laid-out DOM.
            if last_dom:
                _persistent_page_cdp_call(
                    session, "Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": 0.0, "y": 0.0, "button": "none"},
                    target_id=target_id, timeout=min(0.35, max(0.08, deadline-time.monotonic())),
                    purpose="input",
                )
                session["input_ready_verified"] = True
                session["input_ready_target"] = target_id
                session["input_ready_ready_state"] = last_ready
                session["input_ready_attempts"] = attempts
                session["input_ready_at"] = time.monotonic()
                return True
        except Exception as exc:
            session["input_ready_last_error"] = type(exc).__name__
        time.sleep(0.008)
    session["input_ready_verified"] = False
    session["input_ready_target"] = target_id
    session["input_ready_ready_state"] = last_ready
    session["input_ready_dom"] = last_dom
    session["input_ready_attempts"] = attempts
    session["input_ready_timeout"] = True
    return False



def _focus_embedded_chromium_startup_input(session, target_id: str = None, timeout: float = 0.8):
    """Focus a sensible editable control before the first DWM reveal.

    This is intentionally conservative and startup-only. Prefer explicit
    autofocus, then search fields, then common query/text inputs. If the page
    already owns focus inside an editable control, leave it alone.
    """
    if not session or not session.get("port"):
        return False
    target_id = str(target_id or session.get("target_id") or "")
    if not target_id:
        return False
    expr = r'''(() => {
      const d = document;
      const ae = d.activeElement;
      const editable = (el) => !!el && (
        el.isContentEditable ||
        el.tagName === 'TEXTAREA' ||
        (el.tagName === 'INPUT' && !/^(?:button|checkbox|color|file|hidden|image|radio|range|reset|submit)$/i.test(el.type || 'text'))
      );
      if (editable(ae)) return {focused:true, existing:true, tag:ae.tagName, type:ae.type || ''};
      const selectors = [
        '[autofocus]',
        'input[type="search"]',
        'input[name="q"]',
        'input[name="query"]',
        'input[role="searchbox"]',
        'textarea[role="searchbox"]',
        'input[type="text"]',
        'textarea',
        '[contenteditable="true"]'
      ];
      let el = null;
      for (const sel of selectors) {
        for (const candidate of d.querySelectorAll(sel)) {
          const r = candidate.getBoundingClientRect();
          const cs = getComputedStyle(candidate);
          if (!candidate.disabled && r.width > 1 && r.height > 1 && cs.visibility !== 'hidden' && cs.display !== 'none') {
            el = candidate; break;
          }
        }
        if (el) break;
      }
      if (!el) return {focused:false};
      try { el.focus({preventScroll:true}); } catch (_) { try { el.focus(); } catch (_) {} }
      return {focused:d.activeElement === el, existing:false, tag:el.tagName, type:el.type || ''};
    })()'''
    try:
        result = _persistent_page_cdp_call(
            session, "Runtime.evaluate",
            {"expression": expr, "returnByValue": True},
            target_id=target_id, timeout=max(0.1, float(timeout)), purpose="input",
        )
        value = (((result or {}).get("result") or {}).get("value") or {})
        ok = bool(value.get("focused"))
        session["startup_editable_focus_ready"] = ok
        session["startup_editable_focus_target"] = target_id
        session["startup_editable_focus_existing"] = bool(value.get("existing"))
        session["startup_editable_focus_tag"] = str(value.get("tag") or "")
        session["startup_editable_focus_type"] = str(value.get("type") or "")
        return ok
    except Exception as exc:
        session["startup_editable_focus_ready"] = False
        session["startup_editable_focus_error"] = type(exc).__name__
        return False

def warm_embedded_chromium_input_channel(target_id: str = None, timeout: float = 2.0):
    """Backward-compatible v8.6 helper for warming only the critical input lane."""
    return warm_embedded_chromium_io_channels(
        target_id=target_id, timeout=timeout, purposes=("input",)
    )

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
            "midi_sysex": 2,
            "bluetooth_guard": 2,
            "usb_guard": 2,
            "serial_guard": 2,
            "hid_guard": 2,
            "idle_detection": 2,
            "window_placement": 2,
            "automatic_downloads": 2,
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
            "topics_enabled": False,
            "fledge_enabled": False,
            "ad_measurement_enabled": False,
            "m1": {"topics_enabled": False, "fledge_enabled": False, "ad_measurement_enabled": False},
        })
        prefs.setdefault("privacy_guide", {})["viewed"] = True
        prefs.setdefault("privacy", {})["sandbox_enabled"] = False
        prefs.setdefault("browser", {})["enable_spellchecking"] = False
        prefs.setdefault("alternate_error_pages", {})["enabled"] = False
        tmp = pref_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(prefs, separators=(",", ":")), encoding="utf-8")
        tmp.replace(pref_path)
    except Exception:
        # Privacy prefs are defense-in-depth; browser startup must still work.
        pass


def _start_persistent_chromium_session(timeout=12, launch_geometry=None, launch_url=None):
    """Serialize Chromium bootstrap/recovery so only one helper can win."""
    with _EDGE_SESSION_LOCK:
        return _start_persistent_chromium_session_unlocked(
            timeout=timeout, launch_geometry=launch_geometry, launch_url=launch_url
        )


def _start_persistent_chromium_session_unlocked(timeout=12, launch_geometry=None, launch_url=None):
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
            # A busy renderer can miss one short DevTools probe. Require two
            # misses before declaring the persistent browser session broken.
            for probe_timeout in (0.35, 0.75):
                try:
                    _devtools_json(_EDGE_SESSION["port"], "/json/version", timeout=probe_timeout)
                    return _EDGE_SESSION
                except Exception:
                    if process.poll() is not None:
                        break
                    time.sleep(0.04)
        stale_session = _EDGE_SESSION
        try:
            close_embedded_chromium(clear_profile=False)
        except Exception:
            _EDGE_SESSION = None
            try:
                _close_persistent_page_cdp_channels(stale_session)
                _close_persistent_browser_cdp_channel(stale_session)
            except Exception:
                pass

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
            # Let Chromium choose an ephemeral debugging port. This removes the
            # bind-close-rebind TOCTOU window from Tekzite's old free-port probe.
            port = 0
            _CHROMIUM_LAUNCH_DEBUG.update({
                "attempts": int(_CHROMIUM_LAUNCH_DEBUG.get("attempts", 0)) + 1,
                "executable": executable, "port": None, "profile": profile,
            })
            process = None
            try:
                # v9.5: do not enumerate every Windows process on every clean
                # startup. CIM/Win32_Process discovery was a major chunk of the
                # user-visible "Preparing Chromium frame" period even before
                # Chromium itself had launched. Only run the expensive recovery
                # path when cheap profile markers suggest an unclean prior exit,
                # or on the deliberate second attempt after a failed launch.
                recovery_needed = bool(attempt > 1 or _profile_recovery_needed(profile))
                _CHROMIUM_LAUNCH_DEBUG["profile_recovery_scan_needed"] = recovery_needed
                if recovery_needed:
                    recovery_started = time.monotonic()
                    _terminate_stale_profile_owner(profile)
                    found, terminated = _terminate_profile_chromium_processes(profile)
                    if found:
                        _CHROMIUM_LAUNCH_DEBUG["profile_processes_found"] = list(found)
                    if terminated:
                        _CHROMIUM_LAUNCH_DEBUG["profile_processes_terminated"] = list(terminated)
                    # Once no live process owns Tekzite's private profile,
                    # singleton crumbs are stale by definition.
                    if not _profile_chromium_pids(profile):
                        _clear_chromium_profile_locks(profile)
                    _CHROMIUM_LAUNCH_DEBUG["profile_recovery_ms"] = round(
                        (time.monotonic() - recovery_started) * 1000.0, 2
                    )
                else:
                    _CHROMIUM_LAUNCH_DEBUG["profile_recovery_ms"] = 0.0
                    _CHROMIUM_LAUNCH_DEBUG["clean_profile_fast_path"] = True
                if attempt == 2:
                    # Give Windows a beat to release file/process handles from
                    # the failed first helper before relaunching the same profile.
                    time.sleep(0.15)
                _clear_devtools_active_port(profile)
                _apply_privacy_profile_preferences(profile)
                launch_x, launch_y, launch_w, launch_h = (-32000, -32000, 800, 600)
                if launch_geometry:
                    try:
                        launch_x, launch_y, launch_w, launch_h = map(int, launch_geometry)
                        launch_w, launch_h = max(320, launch_w), max(240, launch_h)
                    except Exception:
                        launch_x, launch_y, launch_w, launch_h = (-32000, -32000, 800, 600)
                extension_dirs = _chromium_extension_dirs()
                extension_arg = ",".join(str(path) for path in extension_dirs)
                _CHROMIUM_LAUNCH_DEBUG["extension_dirs"] = [str(path) for path in extension_dirs]
                _CHROMIUM_LAUNCH_DEBUG["private_profile"] = bool(os.environ.get("TEKZITE_PRIVATE_MODE") == "1")
                command = [
                    executable,
                    "--remote-debugging-port=0",
                    "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={profile}",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-save-password-bubble", "--disable-translate",
                    "--disable-search-engine-choice-screen",
                    "--disable-sync",
                    "--disable-background-networking", "--disable-breakpad",
                    "--disable-crash-reporter", "--disable-domain-reliability",
                    "--disable-default-apps",
                    "--disable-logging", "--metrics-recording-only", "--no-pings",
                    "--disable-hyperlink-auditing", "--disable-preconnect",
                    "--disable-features=EdgeFirstRunExperience,msEdgeSidebarV2,AsyncDns,DnsOverHttps,UseDnsHttpsSvcb,NetworkErrorLogging,Reporting,OptimizationHints,AutofillServerCommunication,InterestFeedContentSuggestions,PrivacySandboxSettings4,MediaRouter,CalculateNativeWinOcclusion,BrowsingTopics,InterestCohortAPI,SharedStorageAPI,FencedFrames,AttributionReporting,PrivateAggregationApi,FedCm,WebBluetooth,WebUSB,WebSerial,WebHID,IdleDetection,WebNFC,Prerender2,SpeculationRulesPrefetchProxy",
                    "--disable-session-crashed-bubble", "--disable-background-mode",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                    f"--disable-extensions-except={extension_arg}",
                    f"--load-extension={extension_arg}",
                    f"--proxy-server={ensure_network_engine()['proxy_url']}",
                    "--proxy-bypass-list=<-loopback>", "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    f"--window-position={launch_x},{launch_y}",
                    f"--window-size={launch_w},{launch_h}",
                    f"--app={str(launch_url or 'about:blank')}",
                ]
                if os.name != "nt":
                    # Linux Preview presents Chromium through Tekzite's existing
                    # CDP software compositor. Modern headless Chromium needs no
                    # X11/XWayland child-window reparenting and therefore works
                    # under native Wayland as well as X11. Keep Chromium's sandbox
                    # for normal desktop users. Root-only CI/container smoke tests
                    # cannot start Chromium's sandbox, so opt out only in that
                    # exceptional execution context.
                    command.extend(["--headless=new", "--disable-gpu-vsync"])
                    geteuid = getattr(os, "geteuid", None)
                    if callable(geteuid) and int(geteuid()) == 0:
                        command.append("--no-sandbox")
                        _CHROMIUM_LAUNCH_DEBUG["linux_root_no_sandbox"] = True
                    _CHROMIUM_LAUNCH_DEBUG["linux_headless_software_backend"] = True
                if os.environ.get("TEKZITE_DOWNLOAD_PROMPT") == "1":
                    command.append("--download-prompt-for-download")
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
                launch_started = time.monotonic()
                process = subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=creationflags, startupinfo=None,
                    start_new_session=(os.name != "nt"),
                )
                _CHROMIUM_LAUNCH_DEBUG["process_spawn_ms"] = round(
                    (time.monotonic() - launch_started) * 1000.0, 2
                )
                original_pid = int(process.pid)
                devtools_started = time.monotonic()
                wait_info = _wait_for_devtools(profile, process, timeout=timeout) or {}
                port = int(wait_info.get("port") or 0)
                if not (1 <= port <= 65535):
                    raise RuntimeError("Chromium did not publish a valid DevToolsActivePort")
                _CHROMIUM_LAUNCH_DEBUG["port"] = port
                _CHROMIUM_LAUNCH_DEBUG["devtools_ready_ms"] = round(
                    (time.monotonic() - devtools_started) * 1000.0, 2
                )
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
                    "browser_ws_url": str((wait_info.get("version") or {}).get("webSocketDebuggerUrl") or ""),
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
                        window_find_started = time.monotonic()
                        helper_hwnd = _find_chromium_window(_EDGE_SESSION, timeout=1.5)
                        _CHROMIUM_LAUNCH_DEBUG["window_discovery_ms"] = round(
                            (time.monotonic() - window_find_started) * 1000.0, 2
                        )
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
                if port:
                    revoke_loopback_port(port)
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


_GOOGLE_AUTH_COOKIE_NAMES = frozenset({
    "SID", "HSID", "SSID", "APISID", "SAPISID", "LSID", "SIDCC",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "__Secure-OSID", "__Host-1PLSID", "__Host-3PLSID",
    "LOGIN_INFO", "__Host-GAPS",
})


def _google_cookie_db_candidates(profile):
    root = Path(str(profile or ""))
    return (
        root / "Default" / "Network" / "Cookies",
        root / "Default" / "Cookies",
        root / "Network" / "Cookies",
        root / "Cookies",
    )


def _live_sqlite_snapshot(db_path):
    """Create a consistent local snapshot of a live SQLite database.

    Chromium keeps its Cookies database in WAL mode. Copying only ``Cookies``
    therefore misses freshly committed sign-in cookies while the browser is
    still open. Prefer SQLite's online backup API, which includes live WAL
    state, and fall back to copying the DB/WAL/SHM bundle when Windows sharing
    rules prevent a direct read.
    """
    db_path = Path(db_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="tekzite-live-sqlite-"))
    snapshot_path = temp_dir / db_path.name
    source = dest = None
    try:
        try:
            uri = db_path.resolve().as_uri() + "?mode=ro"
            source = sqlite3.connect(uri, uri=True, timeout=0.35)
            dest = sqlite3.connect(str(snapshot_path), timeout=0.35)
            source.backup(dest, pages=128, sleep=0.01)
            dest.close(); dest = None
            source.close(); source = None
            return temp_dir, snapshot_path
        except Exception:
            try:
                if dest is not None:
                    dest.close()
            except Exception:
                pass
            try:
                if source is not None:
                    source.close()
            except Exception:
                pass
            dest = source = None

        copied_main = False
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db_path) + suffix)
            if not src.is_file():
                continue
            dst = temp_dir / (db_path.name + suffix)
            shutil.copy2(src, dst)
            copied_main = copied_main or suffix == ""
        if copied_main:
            return temp_dir, snapshot_path
    except Exception:
        pass
    shutil.rmtree(temp_dir, ignore_errors=True)
    return None, None


def _chromium_profile_dirs(profile):
    """Return Chromium profile directories that can contain per-profile state."""
    root = Path(profile)
    result = []
    for candidate in [root / "Default", *sorted(root.glob("Profile *"))]:
        try:
            if candidate.is_dir() and candidate not in result:
                result.append(candidate)
        except Exception:
            pass
    return result


def _mark_chromium_profile_exited_cleanly(profile):
    """Heal stale Chromium crash markers while the profile is fully offline.

    Older Tekzite auth handoffs could force-terminate Chromium, leaving
    ``profile.exit_type`` set to ``Crashed``. Chromium then keeps showing the
    restore-pages bubble even after the handoff code itself has been fixed.
    Only touch Preferences while no Chromium process owns this dedicated
    Tekzite profile.
    """
    profile = str(profile or "")
    if not profile:
        return False
    try:
        if _profile_chromium_pids(profile):
            return False
    except Exception:
        return False

    changed = False
    for profile_dir in _chromium_profile_dirs(profile):
        pref_path = profile_dir / "Preferences"
        if not pref_path.is_file():
            continue
        try:
            prefs = json.loads(pref_path.read_text(encoding="utf-8"))
            if not isinstance(prefs, dict):
                continue
            profile_prefs = prefs.setdefault("profile", {})
            if not isinstance(profile_prefs, dict):
                continue
            needs_write = (
                profile_prefs.get("exit_type") != "Normal"
                or profile_prefs.get("exited_cleanly") is not True
            )
            if not needs_write:
                continue
            profile_prefs["exit_type"] = "Normal"
            profile_prefs["exited_cleanly"] = True
            temp_path = pref_path.with_name(pref_path.name + ".tekzite-clean")
            temp_path.write_text(
                json.dumps(prefs, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temp_path, pref_path)
            changed = True
        except Exception:
            try:
                temp_path.unlink()
            except Exception:
                pass
    return changed


def _chromium_history_db_candidates(profile):
    for profile_dir in _chromium_profile_dirs(profile):
        yield profile_dir / "History"


def _snapshot_chromium_latest_visit(profile):
    """Return the newest (url, visit_time, visit_id) from Chromium History.

    The snapshot helper includes SQLite WAL state, which matters while the
    standalone auth browser is still running. ``None`` means no readable
    History database was available.
    """
    best = None
    for db_path in _chromium_history_db_candidates(profile):
        if not db_path.is_file():
            continue
        temp_dir = None
        try:
            temp_dir, temp_path = _live_sqlite_snapshot(db_path)
            if temp_path is None or not temp_path.is_file():
                continue
            con = sqlite3.connect(str(temp_path), timeout=0.5)
            try:
                row = con.execute(
                    "SELECT urls.url, visits.visit_time, visits.id "
                    "FROM visits JOIN urls ON urls.id = visits.url "
                    "ORDER BY visits.visit_time DESC, visits.id DESC LIMIT 1"
                ).fetchone()
            finally:
                con.close()
            if row:
                candidate = (str(row[0] or ""), int(row[1] or 0), int(row[2] or 0))
                if best is None or candidate[1:] > best[1:]:
                    best = candidate
        except Exception:
            continue
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
    return best


def _auth_navigation_has_returned(handle):
    """Detect a fresh standalone-browser navigation back to Tekzite's site.

    This covers the important already-signed-in case where Google simply
    redirects back to YouTube and no authentication cookie changes at all.
    """
    if not isinstance(handle, dict):
        return False
    profile = str(handle.get("profile") or "")
    return_url = str(handle.get("return_url") or "")
    if not profile or not return_url:
        return False

    latest = _snapshot_chromium_latest_visit(profile)
    if not latest:
        return False
    baseline = handle.get("history_visit_baseline")
    if baseline and tuple(latest) == tuple(baseline):
        return False

    current_url = str(latest[0] or "")
    launch_url = str(handle.get("url") or "")
    try:
        current = urlsplit(current_url)
        expected = urlsplit(return_url)
        launch = urlsplit(launch_url)
        current_host = (current.hostname or "").lower().removeprefix("www.")
        expected_host = (expected.hostname or "").lower().removeprefix("www.")
        if not current_host or current_host != expected_host:
            return False
        if current_url == launch_url:
            return False
        # Never treat an auth-flow endpoint itself as the completed return.
        path_parts = {part for part in (current.path or "").lower().split("/") if part}
        if (current.hostname or "").lower() == "accounts.google.com":
            return False
        if path_parts.intersection({"signin", "login", "servicelogin", "oauth", "o", "accountchooser"}):
            return False
        # If launch and return are on the same host (YouTube commonly is),
        # require an actual fresh visit rather than merely seeing the launch URL.
        if launch.hostname and current_url == launch.geturl():
            return False
    except Exception:
        return False

    handle["google_auth_return_visit"] = tuple(latest)
    return True



def _standalone_auth_window_snapshot(handle):
    """Return visible top-level Chromium windows owned by this auth launch.

    The on-disk History/Cookies databases can lag behind the actual UI.  For
    Google auth we therefore keep a live Win32 view of the exact Chromium
    window Tekzite launched.  This is deliberately read-only: no CDP or
    automation switch is added to the auth browser, preserving Google's normal
    browser compatibility path.
    """
    if os.name != "nt" or not isinstance(handle, dict):
        return []
    try:
        import ctypes
        from ctypes import wintypes

        pids = {
            int(pid) for pid in (handle.get("browser_pids") or [])
            if int(pid or 0) > 0
        }
        launch_pid = int(handle.get("launch_pid") or 0)
        if launch_pid > 0:
            pids.add(launch_pid)
            try:
                pids.update(int(pid) for pid in (_windows_descendant_pids(launch_pid) or []))
            except Exception:
                pass
        profile = str(handle.get("profile") or "")
        if profile:
            try:
                pids.update(int(pid) for pid in _profile_chromium_pids(profile))
            except Exception:
                pass
        pids = {pid for pid in pids if pid > 0}
        if not pids:
            return []

        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        GW_OWNER = 4
        windows = []

        @EnumWindowsProc
        def callback(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids:
                return True
            if not user32.IsWindowVisible(hwnd):
                return True
            if user32.GetWindow(hwnd, GW_OWNER):
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, len(cls))
            if not cls.value.startswith("Chrome_WidgetWin"):
                return True
            length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
            title_buf = ctypes.create_unicode_buffer(length + 1)
            if length:
                user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
            windows.append({
                "hwnd": int(hwnd),
                "pid": int(pid.value),
                "class": cls.value,
                "title": str(title_buf.value or ""),
            })
            return True

        user32.EnumWindows(callback, 0)
        if windows:
            handle["auth_hwnds"] = [row["hwnd"] for row in windows]
            handle["auth_window_titles"] = [row["title"] for row in windows]
        return windows
    except Exception:
        return []


def _auth_window_title_has_returned(handle):
    """Use the live auth-window title as an immediate YouTube return signal.

    Chromium can postpone History/WAL writes for seconds even though the visible
    tab has already reached YouTube.  The Google account page itself does not
    carry a YouTube window title, so for youtube.com returns the live HWND title
    is a safe, zero-disk-lag completion signal.  Other sites continue using the
    cookie/history fallbacks.
    """
    if not isinstance(handle, dict):
        return False
    return_url = str(handle.get("return_url") or "")
    try:
        host = (urlsplit(return_url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return False
    if host not in {"youtube.com", "music.youtube.com"}:
        return False
    launched_at = float(handle.get("launched_monotonic") or 0.0)
    # v10.5.69: the live HWND belongs to the dedicated auth launch, so once its
    # title has actually become YouTube there is no benefit in holding the
    # authenticated window on screen for nearly half a second. Keep only a
    # tiny startup guard against a transient title inherited during window
    # creation.
    if launched_at and (time.monotonic() - launched_at) < 0.12:
        return False
    windows = _standalone_auth_window_snapshot(handle)
    for row in windows:
        title = str(row.get("title") or "").strip().casefold()
        if "youtube" in title:
            handle["google_auth_return_hwnd"] = int(row.get("hwnd") or 0)
            handle["google_auth_return_title"] = str(row.get("title") or "")
            return True
    return False


def _request_windows_hwnd_close(hwnds, *, synchronous=False, system_close=False):
    """Close specific HWNDs cooperatively, without depending on PID discovery."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        WM_SYSCOMMAND = 0x0112
        SC_CLOSE = 0xF060
        SMTO_ABORTIFHUNG = 0x0002
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ]
        user32.SendMessageTimeoutW.restype = ctypes.c_size_t
        requested = []
        for value in hwnds or []:
            try:
                hwnd = wintypes.HWND(int(value))
            except Exception:
                continue
            if not user32.IsWindow(hwnd):
                continue
            sent = False
            if synchronous:
                result = ctypes.c_size_t()
                if system_close:
                    try:
                        sent = bool(user32.SendMessageTimeoutW(
                            hwnd, WM_SYSCOMMAND, SC_CLOSE, 0,
                            SMTO_ABORTIFHUNG, 900, ctypes.byref(result),
                        ))
                    except Exception:
                        sent = False
                if not sent:
                    try:
                        sent = bool(user32.SendMessageTimeoutW(
                            hwnd, WM_CLOSE, 0, 0,
                            SMTO_ABORTIFHUNG, 900, ctypes.byref(result),
                        ))
                    except Exception:
                        sent = False
            else:
                try:
                    sent = bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
                except Exception:
                    sent = False
            if sent:
                requested.append(int(value))
        return requested
    except Exception:
        return []

def _snapshot_google_auth_cookie_state(profile):
    """Return a stable fingerprint of Google auth cookies in a Chromium profile.

    ``None`` means the live Cookies database could not be read at all. An empty
    dict is a successful read with no recognized authenticated Google cookies.
    Keeping those states separate prevents a transient Windows file-sharing
    failure from repeatedly resetting the sign-in settle timer.
    """
    saw_readable_db = False
    for db_path in _google_cookie_db_candidates(profile):
        if not db_path.is_file():
            continue
        temp_dir = None
        try:
            temp_dir, temp_path = _live_sqlite_snapshot(db_path)
            if temp_path is None or not temp_path.is_file():
                continue
            con = sqlite3.connect(str(temp_path), timeout=0.5)
            try:
                rows = con.execute(
                    "SELECT host_key, name, value, encrypted_value, expires_utc "
                    "FROM cookies "
                    "WHERE (host_key LIKE '%.google.com' OR host_key = '.google.com' "
                    "OR host_key = 'accounts.google.com' OR host_key LIKE '%.youtube.com' "
                    "OR host_key = '.youtube.com' OR host_key = 'youtube.com')"
                ).fetchall()
            finally:
                con.close()
            saw_readable_db = True

            snapshot = {}
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
            return snapshot
        except Exception:
            continue
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
    return {} if saw_readable_db else None


def standalone_google_auth_succeeded(handle, settle_seconds: float = 1.35):
    """Detect settled auth completion from the live HWND, then disk fallbacks.

    The visible auth window is authoritative for YouTube: once its real Win32
    title has returned to YouTube there is no reason to wait for Chromium to
    flush History or Cookies. Cookie and History signals remain useful fallback
    paths for other/older auth transitions.
    """
    if not isinstance(handle, dict):
        return False
    profile = str(handle.get("profile") or "")
    if not profile:
        return False

    window_signal = None
    if _auth_window_title_has_returned(handle):
        window_signal = (
            "window",
            int(handle.get("google_auth_return_hwnd") or 0),
            str(handle.get("google_auth_return_title") or ""),
        )

    # v10.5.69: the live returned HWND is already the strongest completion
    # signal we have. It is the exact standalone auth window, it has left the
    # Google account UI, and its visible title is now YouTube. Close on the
    # first observation instead of forcing a second 0.55 s settle cycle. Disk
    # based cookie/history signals keep their conservative settling below.
    if window_signal is not None:
        handle["google_auth_success_signal"] = window_signal
        handle["google_auth_cookie_change_at"] = time.monotonic()
        return True

    current = None
    signal = None
    if signal is None:
        baseline = handle.get("google_auth_cookie_baseline") or {}
        current = _snapshot_google_auth_cookie_state(profile)
        cookie_signal = None
        if current is not None and current:
            changed = any(
                baseline.get(key) != value
                for key, value in current.items()
                if key[1] in _GOOGLE_AUTH_COOKIE_NAMES
            )
            if changed:
                cookie_signal = ("cookie", tuple(sorted(current.items())))

        return_signal = None
        if _auth_navigation_has_returned(handle):
            return_signal = ("return", tuple(handle.get("google_auth_return_visit") or ()))
        signal = return_signal or cookie_signal

        # The title can flip to YouTube while a slower SQLite fallback is in
        # progress. Re-sample the live HWND before yielding so that transition
        # is closed in this same detector cycle rather than one poll later.
        if signal is None and _auth_window_title_has_returned(handle):
            live_signal = (
                "window",
                int(handle.get("google_auth_return_hwnd") or 0),
                str(handle.get("google_auth_return_title") or ""),
            )
            handle["google_auth_success_signal"] = live_signal
            handle["google_auth_cookie_change_at"] = time.monotonic()
            return True

    if signal is None:
        handle["google_auth_success_signal"] = None
        handle["google_auth_cookie_change_at"] = None
        return False

    now = time.monotonic()
    if handle.get("google_auth_success_signal") != signal:
        handle["google_auth_success_signal"] = signal
        handle["google_auth_cookie_change_at"] = now
        if current is not None:
            handle["google_auth_cookie_last_snapshot"] = dict(current)
        return False

    changed_at = handle.get("google_auth_cookie_change_at")
    if changed_at is None:
        handle["google_auth_cookie_change_at"] = now
        return False
    required_settle = max(0.8, float(settle_seconds))
    return (now - float(changed_at)) >= required_settle


def _request_windows_window_close(pids, *, synchronous: bool = False, system_close: bool = False):
    """Ask every top-level window owned by *pids* to close normally.

    ``WM_CLOSE`` is the same cooperative shutdown path used by a window's X
    button.  The synchronous mode uses ``SendMessageTimeout`` so Chromium gets
    a bounded chance to process the close before Tekzite continues.  No process
    termination happens here; preserving Chromium's clean-exit bookkeeping is
    essential because this profile is reopened immediately after Google auth.
    """
    if os.name != "nt":
        return []
    pid_set = {int(pid) for pid in (pids or []) if int(pid or 0) > 0}
    if not pid_set:
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        WM_CLOSE = 0x0010
        WM_SYSCOMMAND = 0x0112
        SC_CLOSE = 0xF060
        SMTO_ABORTIFHUNG = 0x0002
        requested = []

        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ]
        user32.SendMessageTimeoutW.restype = ctypes.c_size_t

        @EnumWindowsProc
        def callback(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pid_set:
                return True

            sent = False
            if synchronous:
                result = ctypes.c_size_t()
                if system_close:
                    try:
                        sent = bool(user32.SendMessageTimeoutW(
                            hwnd, WM_SYSCOMMAND, SC_CLOSE, 0,
                            SMTO_ABORTIFHUNG, 700, ctypes.byref(result),
                        ))
                    except Exception:
                        sent = False
                if not sent:
                    try:
                        sent = bool(user32.SendMessageTimeoutW(
                            hwnd, WM_CLOSE, 0, 0,
                            SMTO_ABORTIFHUNG, 700, ctypes.byref(result),
                        ))
                    except Exception:
                        sent = False
            else:
                try:
                    sent = bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
                except Exception:
                    sent = False

            if sent:
                requested.append(int(hwnd))
            return True

        user32.EnumWindows(callback, 0)
        return requested
    except Exception:
        return []


def close_standalone_auth_chromium(handle, force: bool = False):
    """Close the standalone auth browser without dirtying Chromium's profile.

    ``force`` now means a stronger *cooperative* close (SC_CLOSE/WM_CLOSE with a
    timeout), not ``taskkill /F``.  A forced process termination was the reason
    Chromium later displayed "wasn't shut down correctly" and offered to
    restore pages after a successful Google login.
    """
    if not isinstance(handle, dict) or os.name != "nt":
        return False
    pids = {
        int(pid) for pid in (handle.get("browser_pids") or [])
        if int(pid or 0) > 0
    }
    profile = str(handle.get("profile") or "")
    if profile:
        try:
            pids.update(int(pid) for pid in _profile_chromium_pids(profile))
        except Exception:
            pass
    launch_pid = int(handle.get("launch_pid") or 0)
    if launch_pid:
        pids.add(launch_pid)

    handle["browser_pids"] = sorted(pids)

    # Prefer the exact visible HWND captured for this auth launch. This avoids
    # depending on Chromium's process model after account redirects and makes
    # the close target identical to the window the user sees on screen.
    windows = _standalone_auth_window_snapshot(handle)
    hwnds = [
        int(row.get("hwnd") or 0) for row in windows
        if int(row.get("hwnd") or 0) > 0
    ]
    if not hwnds:
        hwnds = [
            int(hwnd) for hwnd in (handle.get("auth_hwnds") or [])
            if int(hwnd or 0) > 0
        ]
    closed = _request_windows_hwnd_close(
        hwnds, synchronous=bool(force), system_close=bool(force)
    ) if hwnds else []
    if not closed and pids:
        closed = _request_windows_window_close(
            pids, synchronous=bool(force), system_close=bool(force)
        )
    if not closed:
        return False

    handle["auto_close_requested"] = True
    handle.setdefault("auto_close_requested_at", time.monotonic())
    if force:
        handle["auto_close_cooperative_escalated"] = True
        # Give Chromium a short bounded interval to flush cookies/preferences
        # and release the profile after the synchronous close request.
        deadline = time.monotonic() + 2.4
        while time.monotonic() < deadline:
            try:
                if profile and not _profile_chromium_pids(profile):
                    break
            except Exception:
                break
            time.sleep(0.06)
    return True



def _close_embedded_chromium_cleanly_for_auth_unlocked(timeout: float = 6.0):
    """Release Tekzite's shared Chromium profile through Browser.close.

    Google auth temporarily reopens the same profile in a normal Chromium
    window.  Killing the hidden DWM source process with taskkill made Chromium
    record a crash, which surfaced as a "restore pages" bubble in the auth
    window.  This handoff path therefore refuses to force-kill the profile.
    """
    session = _EDGE_SESSION
    if not session:
        return True

    profile = str(session.get("profile") or "")
    process = session.get("process")
    close_requested = False

    # Browser.close is Chromium's own graceful browser-shutdown primitive.  It
    # flushes preferences/cookies and marks the profile as exited cleanly.
    try:
        _browser_cdp_call(session, "Browser.close", {}, timeout=1.4)
        close_requested = True
    except Exception:
        # Browser.close can tear down the websocket before a reply arrives, so
        # check whether the browser is already on its way out before falling
        # back to the native close path.
        try:
            close_requested = not bool(profile and _profile_chromium_pids(profile))
        except Exception:
            close_requested = False

    if not close_requested and os.name == "nt":
        pids = []
        try:
            if profile:
                pids.extend(_profile_chromium_pids(profile))
        except Exception:
            pass
        try:
            if process is not None and getattr(process, "pid", None):
                pids.append(int(process.pid))
        except Exception:
            pass
        close_requested = bool(_request_windows_window_close(
            pids, synchronous=True, system_close=True
        ))

    deadline = time.monotonic() + max(2.0, float(timeout))
    native_retry_at = time.monotonic() + 1.6
    while time.monotonic() < deadline:
        try:
            live_profile_pids = list(_profile_chromium_pids(profile)) if profile else []
        except Exception:
            live_profile_pids = []
        try:
            process_alive = bool(process is not None and process.poll() is None)
        except Exception:
            process_alive = False
        if not live_profile_pids and not process_alive:
            # Reuse the normal bookkeeping cleanup now that the process is gone;
            # its termination branch cannot fire once poll() reports exit.
            _close_embedded_chromium_unlocked(clear_profile=False)
            return True

        if os.name == "nt" and time.monotonic() >= native_retry_at:
            retry_pids = list(live_profile_pids)
            try:
                if process_alive and getattr(process, "pid", None):
                    retry_pids.append(int(process.pid))
            except Exception:
                pass
            _request_windows_window_close(
                retry_pids, synchronous=True, system_close=True
            )
            native_retry_at = time.monotonic() + 1.8
        time.sleep(0.07)

    # Deliberately do not taskkill here. A dirty shutdown is worse than failing
    # the auth handoff because it guarantees Chromium's crash-recovery prompt on
    # the next launch and risks losing the just-written sign-in state.
    return False


def _standalone_auth_window_geometry():
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


def start_standalone_auth_chromium(url: str, return_url: str = ""):
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

        # Authentication reuses Tekzite's web profile, so hand it over only
        # after Chromium has performed a clean Browser.close. Force-killing the
        # DWM source here sets Chromium's crash bit and causes the restore-pages
        # prompt visible after login.
        if not _close_embedded_chromium_cleanly_for_auth_unlocked(timeout=6.0):
            raise RuntimeError(
                "Chromium did not release the Tekzite profile cleanly for sign-in"
            )

        if _profile_chromium_pids(profile):
            raise RuntimeError(
                "Chromium still owns the Tekzite profile after graceful sign-in handoff"
            )

        _clear_devtools_active_port(profile)
        _clear_chromium_profile_locks(profile)
        # Heal crash metadata left by older force-kill auth handoffs before the
        # standalone browser ever reads the profile. This removes the persistent
        # "restore pages" bubble even for users upgrading from v10.5.63.
        _mark_chromium_profile_exited_cleanly(profile)
        google_auth_cookie_baseline = _snapshot_google_auth_cookie_state(profile) or {}
        history_visit_baseline = _snapshot_chromium_latest_visit(profile)

        x, y, width, height = _standalone_auth_window_geometry()
        command = [
            executable,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-mode",
            # Belt-and-suspenders protection for a profile that still carries
            # crash state Chromium keeps somewhere outside Preferences.
            "--disable-session-crashed-bubble",
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

        launch_handle = {
            "process": process,
            "launch_pid": int(process.pid),
            "browser_pids": list(browser_pids),
            "profile": profile,
            "executable": executable,
            "url": target_url,
            "return_url": str(return_url or ""),
            "window_geometry": (x, y, width, height),
            "google_auth_cookie_baseline": dict(google_auth_cookie_baseline),
            "history_visit_baseline": tuple(history_visit_baseline) if history_visit_baseline else None,
            "google_auth_cookie_last_snapshot": dict(google_auth_cookie_baseline),
            "google_auth_cookie_change_at": None,
            "auto_close_requested": False,
            "command_flags": [arg for arg in command[1:] if str(arg).startswith("--")],
            "remote_debugging": False,
            "cdp_control": False,
            "launched_monotonic": time.monotonic(),
            "auth_hwnds": [],
            "auth_window_titles": [],
        }
        # Capture the actual top-level HWND immediately. Subsequent auth
        # completion and close requests can then target the exact window the
        # user is looking at instead of rediscovering it from process state.
        _standalone_auth_window_snapshot(launch_handle)
        return launch_handle


def standalone_auth_chromium_running(handle):
    """Return True while the real auth browser, not merely its launcher, exists."""
    if not isinstance(handle, dict):
        return False

    profile = str(handle.get("profile") or "")
    if profile:
        try:
            live_profile_pids = sorted(set(int(pid) for pid in _profile_chromium_pids(profile)))
            if live_profile_pids:
                handle["browser_pids"] = live_profile_pids
        except Exception:
            pass

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
        and not str(page.get("url", "")).startswith("chrome-extension://")
    ]
    if not candidates:
        raise RuntimeError("Chromium bridge exposed no debuggable page")
    # App-mode startup should expose exactly one page. Prefer about:blank if
    # Edge also created an internal/background page for its own UI.
    page = next((p for p in candidates if p.get("url") == "about:blank"), candidates[0])
    if session is not None:
        session["target_id"] = page.get("id")
    return page



def _close_persistent_browser_cdp_channel(session):
    """Close the cached browser-level DevTools channel, if any."""
    channel = (session or {}).pop("browser_cdp_channel", None)
    if not channel:
        return
    try:
        channel.get("ws") and channel["ws"].close()
    except Exception:
        pass
    channel["closed"] = True


def _get_persistent_browser_cdp_channel(session, timeout=5.0):
    """Return one long-lived browser-level CDP WebSocket.

    v9.4 removes the /json/version + websocket-handshake tax from every tab
    activation/creation/close operation.  Browser-level Target.* commands are
    tiny and sequential, so one locked persistent loopback socket is ideal.
    """
    channel = (session or {}).get("browser_cdp_channel")
    if channel and channel.get("ws") is not None and not channel.get("closed"):
        return channel
    ws_url = str((session or {}).get("browser_ws_url") or "")
    if not ws_url:
        version = _devtools_json(session["port"], "/json/version", timeout=min(0.5, float(timeout)))
        ws_url = str(version.get("webSocketDebuggerUrl") or "")
        if ws_url:
            session["browser_ws_url"] = ws_url
    if not ws_url:
        raise RuntimeError("Chromium browser DevTools websocket unavailable")
    ws = _open_devtools_websocket(ws_url, timeout=timeout)
    channel = {
        "ws": ws, "ws_url": ws_url, "lock": threading.RLock(),
        "next_message_id": 2000, "closed": False, "calls": 0,
        "created_at": time.monotonic(),
    }
    session["browser_cdp_channel"] = channel
    return channel


def _browser_cdp_call(session, method, params=None, *, message_id=None, timeout=5.0):
    """Call browser-level CDP over a persistent low-latency socket.

    One reconnect is allowed if Chromium replaces/closes the DevTools endpoint.
    """
    last_error = None
    for attempt in range(2):
        channel = _get_persistent_browser_cdp_channel(session, timeout=timeout)
        try:
            with channel["lock"]:
                mid = int(message_id) if message_id is not None else int(channel.get("next_message_id", 2000))
                if message_id is None:
                    channel["next_message_id"] = mid + 1
                result = _cdp_call(channel["ws"], method, params or {}, message_id=mid, timeout=timeout)
                channel["calls"] = int(channel.get("calls", 0)) + 1
                return result
        except Exception as exc:
            last_error = exc
            _close_persistent_browser_cdp_channel(session)
            if attempt == 0:
                continue
            raise
    raise RuntimeError(f"Persistent browser CDP call failed: {method}") from last_error


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

    # Claim the launch app target exactly once. Reusing the bootstrap target is
    # important: creating a second target at startup can cause Chromium to
    # manufacture another Chrome_WidgetWin_0 presenter, which defeats app-mode.
    #
    # v10.5.0: cold startup always launches Chromium at about:blank, then claims
    # that neutral app target before navigating to the user's real URL. DevTools
    # can become reachable a few milliseconds before /json/list contains the app
    # page, so poll briefly instead of treating one empty/mismatched list as a
    # fatal bootstrap failure. A sole page target is a safe final fallback: the
    # dedicated Tekzite Chromium profile has only one app page at this point.
    if not target_id and not session.get("app_bootstrap_target_claimed"):
        try:
            expected_launch_url = str(session.get("launch_url") or "about:blank")
            expected_lower = expected_launch_url.strip().lower()
            neutral_urls = {"about:blank", "chrome://newtab", "chrome://newtab/"}
            deadline = time.monotonic() + (1.5 if require_bootstrap else 0.35)
            bootstrap = None
            claim_reason = None
            last_pages = []
            last_list_error = None
            while True:
                try:
                    pages = _devtools_json(session["port"], "/json/list", timeout=0.5)
                    last_pages = list(pages or [])
                    page_candidates = [
                        p for p in last_pages
                        if p.get("type") == "page" and p.get("webSocketDebuggerUrl")
                    ]
                    bootstrap = next(
                        (p for p in page_candidates
                         if str(p.get("url") or "").strip().lower() == expected_lower),
                        None,
                    )
                    if bootstrap is not None:
                        claim_reason = "expected-url"
                    if bootstrap is None:
                        bootstrap = next(
                            (p for p in page_candidates
                             if str(p.get("url") or "").strip().lower() in neutral_urls),
                            None,
                        )
                        if bootstrap is not None:
                            claim_reason = "neutral-url"
                    if bootstrap is None and len(page_candidates) == 1:
                        bootstrap = page_candidates[0]
                        claim_reason = "sole-page-fallback"
                    if bootstrap is not None:
                        break
                    last_list_error = None
                except Exception as exc:
                    last_list_error = exc
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.03)

            session["bootstrap_page_urls"] = [str(p.get("url") or "") for p in last_pages if p.get("type") == "page"]
            session["bootstrap_claim_reason"] = claim_reason
            if bootstrap and bootstrap.get("id"):
                target_id = bootstrap.get("id")
                actual_url = str(bootstrap.get("url") or "")
                actual_lower = actual_url.strip().lower()
                session["app_bootstrap_target_claimed"] = True
                session["native_app_target_reused"] = True
                session["native_app_target_id"] = target_id
                session["native_direct_app_url"] = expected_launch_url if expected_lower not in neutral_urls else None
                session["native_direct_app_target_match"] = (actual_lower == expected_lower)
                _browser_cdp_call(
                    session, "Target.activateTarget", {"targetId": target_id}, message_id=102
                )
                requested_url = str(url or "about:blank")
                requested_lower = requested_url.strip().lower()
                neutral_equivalent = requested_lower in neutral_urls and actual_lower in neutral_urls
                if requested_url != actual_url and not neutral_equivalent:
                    _persistent_page_cdp_call(
                        session, "Page.navigate", {"url": requested_url},
                        target_id=target_id, timeout=5.0, purpose="control",
                    )
                    session["bootstrap_navigation_required"] = True
                else:
                    session["bootstrap_navigation_required"] = False
                    session["bootstrap_socket_skipped"] = True
            elif last_list_error is not None:
                raise last_list_error
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
    # v9.4: 100% is Chromium's native zoom. Calling the extension for the
    # default value on every newly claimed target adds synchronous CDP/extension
    # work before first paint for no visual benefit. Non-default preferences are
    # still applied immediately; 100% is verified asynchronously by the UI.
    try:
        inherited_zoom = int(session.get("default_page_zoom_percent", 100))
        if inherited_zoom != 100:
            set_embedded_chromium_zoom(inherited_zoom, target_id=target_id, timeout=3)
            session["target_zoom_bootstrap_applied"] = True
        else:
            session["target_zoom_bootstrap_applied"] = False
            session["target_zoom_bootstrap_skipped_default"] = True
    except Exception:
        pass
    return target_id


def _devtools_target_http_command(session, command: str, target_id: str, timeout: float = 0.45):
    """Run a DevTools /json target command without browser WebSocket locks.

    Chromium exposes activate/close as loopback HTTP endpoints. Using them for
    tab lifecycle changes keeps the hot close/switch path away from Tekzite's
    shared browser-level CDP socket, its Python lock, and any queued protocol
    events. The call is designed for a worker thread and has a short hard timeout.
    """
    if not session or not target_id:
        return False
    try:
        port = int(session.get("port") or 0)
    except Exception:
        return False
    if not (1 <= port <= 65535):
        return False
    command = str(command or "").strip().lower()
    if command not in {"activate", "close"}:
        return False
    encoded = quote(str(target_id), safe="")
    url = f"http://127.0.0.1:{port}/json/{command}/{encoded}"
    try:
        with _stdlib_urlopen(url, timeout=max(0.10, float(timeout))) as response:
            # Consume only a tiny response body. Chromium normally returns a
            # short plain-text acknowledgement for these endpoints.
            response.read(4096)
        return True
    except Exception:
        return False


def activate_embedded_chromium_target(target_id: str):
    """Activate an already-loaded Chromium target without touching shared CDP.

    v10.5.32 uses Chromium's loopback /json/activate endpoint as the primary
    path. The previous browser-WebSocket Target.activateTarget call could sit
    behind protocol traffic/locks while an active tab was being closed. Even in
    a Python worker that contention could make the entire app *feel* frozen.
    This path is independent, bounded, and never acquires _EDGE_SESSION_LOCK in
    the normal running-browser case.
    """
    if not target_id:
        return False

    session = _EDGE_SESSION
    if not session:
        # Cold/recovery fallback only. Normal tab switching always has a live
        # session by the time a Chromium target exists.
        try:
            session = _start_persistent_chromium_session(timeout=3.0)
        except Exception:
            return False

    process = session.get("process") if isinstance(session, dict) else None
    try:
        if process is not None and process.poll() is not None:
            return False
    except Exception:
        pass

    activated = _devtools_target_http_command(session, "activate", target_id, timeout=0.35)
    if not activated:
        # One lock-free existence probe + retry handles the rare moment where
        # DevTools is responsive but the target list has just changed.
        try:
            pages = _devtools_json(session["port"], "/json/list", timeout=0.30)
            if not any(str(p.get("id") or "") == str(target_id) for p in pages):
                return False
        except Exception:
            return False
        activated = _devtools_target_http_command(session, "activate", target_id, timeout=0.45)
    if not activated:
        return False

    session["target_id"] = target_id
    session["tab_switch_http_activate"] = True
    session["tab_switch_fast_path_count"] = int(session.get("tab_switch_fast_path_count", 0)) + 1

    # Keep repaint asynchronous. No DwmFlush/UpdateWindow/RDW_UPDATENOW.
    if os.name == "nt" and session.get("presentation_mode") != "software":
        try:
            user32 = _typed_user32()
            render = _as_hwnd(session.get("render_hwnd") or 0)
            owner = _as_hwnd(session.get("embedded_hwnd") or 0)
            RDW_INVALIDATE = 0x0001
            RDW_ALLCHILDREN = 0x0080
            flags = RDW_INVALIDATE | RDW_ALLCHILDREN
            for hwnd in (render, owner):
                if hwnd and user32.IsWindow(hwnd):
                    user32.RedrawWindow(hwnd, None, None, flags)
            session["tab_switch_repaint_async"] = True
            session["tab_switch_dwm_flush"] = False
        except Exception as exc:
            session["tab_switch_present_error"] = str(exc)
    return True


def close_embedded_chromium_target(target_id: str):
    """Close one Chromium target without using Tekzite's shared CDP socket."""
    if not target_id:
        return False
    session = _EDGE_SESSION
    if not session:
        return False

    # Close Tekzite's cached page sockets first. This is local bookkeeping and
    # prevents stale per-target lanes from being reused after Chromium closes it.
    try:
        _close_persistent_page_cdp_channels(session, target_id=target_id)
    except Exception:
        pass

    ok = _devtools_target_http_command(session, "close", target_id, timeout=0.50)
    if ok:
        if session.get("target_id") == target_id:
            session.pop("target_id", None)
        session["tab_close_http"] = True
    return bool(ok)

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
    target_url = str(session.get("last_url") or page.get("url") or "").strip().lower()
    # A blank new tab is a valid software-compositor frame even though it has
    # no text/nodes and produces a deliberately uniform screenshot. Without
    # this exception Linux Preview would wait for the full first-frame timeout
    # every time about:blank is used as a tab/bootstrap surface.
    blank_document_allowed = target_url in {"about:blank", "chrome://newtab/"}
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

            has_document = bool(
                ready in {"interactive", "complete"}
                and (
                    blank_document_allowed
                    or ((text_len >= 8 or nodes >= 2) and width > 0 and height > 0)
                )
            )
            if has_document:
                if ready_since is None:
                    ready_since = time.monotonic()
                if blank_document_allowed:
                    # No visual proof is meaningful for an intentionally empty
                    # tab. Return as soon as Chromium exposes the complete blank
                    # document; the normal software-frame loop will capture the
                    # viewport immediately after the UI maps it.
                    session["first_frame_ready"] = True
                    session["first_frame_ready_state"] = ready
                    session["first_frame_text_len"] = text_len
                    session["first_frame_nodes"] = nodes
                    session["first_frame_png_chars"] = 0
                    session["first_frame_probe"] = "blank-document"
                    session["first_frame_empty_shell_rejected"] = False
                    return True

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
                blank_frame_ready = bool(blank_document_allowed and stable_ready)
                session["first_frame_visual_black_ratio"] = frame_metrics.get("black_ratio")
                session["first_frame_visual_white_ratio"] = frame_metrics.get("white_ratio")
                session["first_frame_visual_span"] = frame_metrics.get("channel_span")
                session["first_frame_blank_png_rejected"] = bool(screenshot_exists and not screenshot_ready)
                if screenshot_ready or semantic_frame_ready or blank_frame_ready:
                    session["first_frame_ready"] = True
                    session["first_frame_ready_state"] = ready
                    session["first_frame_text_len"] = text_len
                    session["first_frame_nodes"] = nodes
                    session["first_frame_png_chars"] = screenshot_chars
                    session["first_frame_probe"] = (
                        "visual-screenshot" if screenshot_ready
                        else "blank-document" if blank_frame_ready
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
        # v9.6: do not wait for a compositor tick between the 1px nudge and
        # restore. The final flush below is sufficient and the readiness loop
        # verifies the resulting RenderWidgetHost geometry.
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


def _wait_for_attached_first_frame(session, timeout: float = 2.0):
    """Verify the first hidden native frame using the already-hot input lane.

    v9.3 removes another cold-start tax: the frame gate no longer creates a
    temporary DevTools websocket or enables Page/Runtime domains just for
    readiness probing.  It reuses Tekzite's persistent critical input channel,
    which remains alive for the user's first click/keystroke.  PNG capture is a
    late fallback only, so normal pages stay on the cheap DOM+native-geometry
    path from navigation through reveal.
    """
    frame_generation = int(session.get("navigation_generation") or 0)
    session["attached_frame_generation"] = frame_generation
    target_id = str(session.get("target_id") or "")
    deadline = time.monotonic() + max(0.25, float(timeout))
    started = time.monotonic()
    last_ready = ""
    last_text = 0
    last_nodes = 0
    attempts = 0
    # Open the exact socket that will later carry real input.  This folds input
    # prewarming into frame readiness instead of paying for a second handshake.
    try:
        _get_persistent_page_cdp_channel(
            session, target_id=target_id, timeout=min(0.8, max(0.2, float(timeout))),
            purpose="input",
        )
        session["input_channel_warmed_target"] = target_id
        session["input_channel_warmed_at"] = time.monotonic()
    except Exception:
        pass

    while time.monotonic() < deadline:
        attempts += 1
        remaining = max(0.04, deadline - time.monotonic())
        try:
            state = _persistent_page_cdp_call(
                session,
                "Runtime.evaluate",
                {
                    "expression": "({ready:document.readyState,text:(document.body&&document.body.innerText||'').trim().length,nodes:document.body?document.body.childElementCount:0,w:document.documentElement?document.documentElement.scrollWidth:0,h:document.documentElement?document.documentElement.scrollHeight:0})",
                    "returnByValue": True,
                },
                target_id=target_id,
                timeout=min(0.30, max(0.04, remaining)),
                purpose="input",
            )
            value = state.get("result", {}).get("value", {}) if isinstance(state, dict) else {}
            ready = str(value.get("ready") or "")
            text_len = int(value.get("text") or 0)
            nodes = int(value.get("nodes") or 0)
            width = int(value.get("w") or 0)
            height = int(value.get("h") or 0)
            last_ready, last_text, last_nodes = ready, text_len, nodes

            elapsed = time.monotonic() - started
            cold_start = frame_generation <= 1
            expected_size = session.get("embedded_size") or session.get("embedded_parent_client_size") or (0, 0)
            expected_w, expected_h = int(expected_size[0] or 0), int(expected_size[1] or 0)
            live_size = _current_render_host_size(session)
            geometry_ready = False
            if live_size and expected_w > 0 and expected_h > 0:
                rw, rh = live_size
                geometry_ready = (rw >= int(expected_w * 0.94) and rh >= int(expected_h * 0.94))

            semantic_ready = text_len >= 8 and nodes >= 2 and width > 0 and height > 0
            if cold_start:
                semantic_ready = semantic_ready and geometry_ready
                if (not geometry_ready and elapsed >= 0.030
                        and not session.get("cold_start_resize_kick_attempted")):
                    _kick_cold_start_native_resize(session)

            session["cold_start_geometry_wait"] = bool(cold_start and not geometry_ready)
            session["cold_start_render_size"] = live_size
            session["cold_start_expected_size"] = (expected_w, expected_h)
            session["attached_frame_ready_state"] = ready
            session["attached_frame_text_len"] = text_len
            session["attached_frame_nodes"] = nodes

            screenshot_chars = 0
            metrics = {}
            screenshot_ready = False
            # v9.3: screenshot encoding is expensive. Give semantic/geometry
            # readiness a short head start and only use the visual fallback for
            # sparse/non-text pages or when the normal proof is genuinely late.
            if not semantic_ready and (elapsed >= 0.10 or remaining <= 0.18):
                try:
                    shot = _persistent_page_cdp_call(
                        session, "Page.captureScreenshot",
                        {"format":"png", "fromSurface":True, "captureBeyondViewport":False, "optimizeForSpeed":True},
                        target_id=target_id,
                        timeout=min(0.40, max(0.04, remaining)),
                        purpose="input",
                    )
                    data = shot.get("data", "") if isinstance(shot, dict) else ""
                    if isinstance(data, str):
                        screenshot_chars = len(data)
                        metrics = _analyze_embedded_frame_png(data)
                        screenshot_ready = screenshot_chars >= 128 and bool(metrics.get("visual"))
                except Exception:
                    pass

            session["attached_frame_png_chars"] = screenshot_chars
            session["attached_frame_visual"] = bool(metrics.get("visual"))
            if screenshot_ready or semantic_ready:
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
                session["first_frame_probe"] = "attached-semantic-geometry" if semantic_ready else "attached-visual-screenshot"
                session["attached_frame_timeout"] = False
                session["attached_frame_stale_generation"] = False
                session["attached_frame_attempts"] = attempts
                return True
        except Exception as exc:
            session["attached_frame_last_error"] = type(exc).__name__

        # Do not DwmFlush inside the polling loop: DwmFlush deliberately waits
        # for compositor cadence and can add a whole refresh interval per miss.
        try:
            _show_embedded_render_host(
                session,
                int((session.get("embedded_size") or (1,1))[0]),
                int((session.get("embedded_size") or (1,1))[1]),
            )
        except Exception:
            pass
        time.sleep(0.006)

    session["attached_frame_timeout"] = True
    session["attached_frame_ready_state"] = last_ready
    session["attached_frame_text_len"] = last_text
    session["attached_frame_nodes"] = last_nodes
    session["attached_frame_attempts"] = attempts
    return False

def stop_embedded_chromium_loading(target_id: str = None, timeout: float = 2.0):
    """Stop the active network/document load for one Tekzite Chromium tab."""
    session = _start_persistent_chromium_session(timeout=min(float(timeout), 2.0))
    target_id = str(target_id or session.get("target_id") or "")
    if not target_id:
        return False
    _persistent_page_cdp_call(
        session, "Page.stopLoading", {}, target_id=target_id,
        timeout=max(0.5, min(float(timeout), 2.0)), purpose="control",
    )
    return True


def navigate_embedded_chromium(url: str, timeout: int = 20, wait_for_first_frame: bool = False, target_id: str = None, create_new_target: bool = False):
    """Navigate Chromium with a persistent hot-path control channel.

    v9.4 avoids /json/list, a fresh page WebSocket handshake and Page.enable on
    ordinary navigation when Tekzite already knows the target id.  Cold/bootstrap
    discovery still uses the target list once, while steady-state Page.navigate
    becomes one command on the tab's persistent control socket.
    """
    session = _start_persistent_chromium_session(timeout=min(timeout, 12))
    if create_new_target:
        target_id = create_embedded_chromium_target("about:blank")

    known_target = str(target_id or "")
    direct_app_target = bool(
        known_target
        and session.get("native_direct_app_launch")
        and session.get("native_direct_app_target_match")
        and known_target == str(session.get("native_app_target_id") or "")
        and str(session.get("native_direct_app_url") or "").lower() == str(url or "").lower()
    )

    if known_target:
        # Target ids belong to one Chromium process. If Chromium restarted after
        # a crash, Tekzite tabs still carry the old ids. Detect that here and
        # transparently claim/create a replacement target for the requested tab.
        target_valid = True
        if str(session.get("target_id") or "") != known_target:
            target_valid = bool(activate_embedded_chromium_target(known_target))
        if not target_valid:
            stale_target = known_target
            known_target = str(create_embedded_chromium_target("about:blank") or "")
            if not known_target:
                raise RuntimeError("Chromium could not recover the stale tab target")
            session["recovered_stale_target_id"] = stale_target
            session["recovered_target_id"] = known_target
            session["target_recovery_count"] = int(session.get("target_recovery_count", 0)) + 1
            direct_app_target = False
        if direct_app_target:
            session["native_direct_app_navigation_skipped"] = True
        else:
            _persistent_page_cdp_call(
                session, "Page.navigate", {"url": str(url)},
                target_id=known_target, timeout=min(5.0, float(timeout)), purpose="control",
            )
            session["native_direct_app_navigation_skipped"] = False
        resolved_target = known_target
    else:
        # Bootstrap discovery is necessarily one-time target enumeration.
        page = _pick_devtools_page(session["port"], session, target_id=None)
        resolved_target = str(page.get("id") or "")
        direct_app_target = bool(
            session.get("native_direct_app_launch")
            and session.get("native_direct_app_target_match")
            and resolved_target == str(session.get("native_app_target_id") or "")
            and str(page.get("url") or "").lower() not in {"about:blank", "chrome://newtab/"}
        )
        if direct_app_target:
            session["native_direct_app_navigation_skipped"] = True
        else:
            _persistent_page_cdp_call(
                session, "Page.navigate", {"url": str(url)},
                target_id=resolved_target, timeout=min(5.0, float(timeout)), purpose="control",
            )
            session["native_direct_app_navigation_skipped"] = False

    session["target_id"] = resolved_target
    session["last_url"] = str(url)
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
    session["hot_navigation_persistent_control"] = bool(known_target)
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
    """Find Chromium's main top-level HWND with a cheap-first startup path.

    v9.6 avoids rebuilding the full descendant process tree every 10 ms. Most
    Chromium app windows belong to the launched browser PID, so each poll first
    does only EnumWindows against that PID. Descendants are refreshed at a much
    lower cadence and are used only as a fallback for launcher/process layouts
    where the real app window lives below the original browser process.
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
    root_pid = int(process.pid)
    descendant_pids = {root_pid}
    next_descendant_refresh = 0.0

    def collect(allowed_pids):
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @WNDENUMPROC
        def enum_proc(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in allowed_pids or not user32.IsWindow(hwnd):
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
        return found

    while time.monotonic() < deadline:
        # Cheap common case: the app window belongs directly to the process
        # Tekzite launched. No process snapshot is needed here.
        found = collect({root_pid})
        now = time.monotonic()
        if not found:
            if now >= next_descendant_refresh:
                try:
                    descendant_pids = _windows_descendant_pids(root_pid) or {root_pid}
                except Exception:
                    descendant_pids = {root_pid}
                next_descendant_refresh = now + 0.05
            if len(descendant_pids) > 1:
                found = collect(descendant_pids)
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
        time.sleep(0.005)
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
    lines.append(f"native_blank_bootstrap_launch: {session.get('native_blank_bootstrap_launch')}")
    lines.append(f"native_requested_initial_url: {session.get('native_requested_initial_url')}")
    lines.append(f"bootstrap_claim_reason: {session.get('bootstrap_claim_reason')}")
    lines.append(f"bootstrap_page_urls: {session.get('bootstrap_page_urls')}")
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
    lines.append(f"dwm_last_resize_path: {session.get('dwm_last_resize_path')}")
    lines.append(f"dwm_fast_resize_count: {session.get('dwm_fast_resize_count')}")
    lines.append(f"dwm_fast_resize_noop_count: {session.get('dwm_fast_resize_noop_count')}")
    lines.append(f"dwm_fast_source_resize_count: {session.get('dwm_fast_source_resize_count')}")
    lines.append(f"dwm_full_reflow_count: {session.get('dwm_full_reflow_count')}")
    lines.append(f"dwm_cold_register_flush_count: {session.get('dwm_cold_register_flush_count')}")
    lines.append(f"dwm_presenter_park_thread_running: {session.get('dwm_presenter_park_thread_running')}")
    lines.append(f"dwm_input_offset: {session.get('dwm_input_offset')}")
    lines.append(f"dwm_input_render_offset: {session.get('dwm_input_render_offset')}")
    lines.append(f"dwm_input_page_owner_rect: {session.get('dwm_input_page_owner_rect')}")
    lines.append(f"dwm_input_render_rect: {session.get('dwm_input_render_rect')}")
    lines.append(f"dwm_input_transform_error: {session.get('dwm_input_transform_error')}")
    lines.append(f"dwm_input_zoom_factor: {session.get('dwm_input_zoom_factor')}")
    lines.append(f"dwm_input_zoom_active: {session.get('dwm_input_zoom_active')}")
    lines.append(f"dwm_input_css_scale_x: {session.get('dwm_input_css_scale_x')}")
    lines.append(f"dwm_input_css_scale_y: {session.get('dwm_input_css_scale_y')}")
    lines.append(f"dwm_input_device_pixel_ratio: {session.get('dwm_input_device_pixel_ratio')}")
    lines.append(f"dwm_input_viewport_css: {session.get('dwm_input_viewport_css')}")
    lines.append(f"dwm_input_render_pixels: {session.get('dwm_input_render_pixels')}")
    lines.append(f"dwm_input_scale_source: {session.get('dwm_input_scale_source')}")
    lines.append(f"dwm_input_metrics_error: {session.get('dwm_input_metrics_error')}")
    lines.append(f"dwm_zoom_percent: {session.get('dwm_zoom_percent')}")
    lines.append(f"preferences_zoom_percent: {session.get('preferences_zoom_percent')}")
    lines.append(f"page_zoom_strategy: {session.get('page_zoom_strategy')}")
    lines.append(f"zoom_watchdog_strategy: {session.get('zoom_watchdog_strategy')}")
    lines.append(f"embed_owner_wait_attempts: {session.get('embed_owner_wait_attempts')}")
    lines.append(f"embed_owner_activation_error: {session.get('embed_owner_activation_error')}")
    lines.append(f"feature_services_ready: {session.get('feature_services_ready')}")
    lines.append(f"feature_services_error: {session.get('feature_services_error')}")
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
                # v9.9: never hide a top-level Chrome_WidgetWin_1 presenter.
                # Chromium can replace/recreate its live app presenter during the
                # first few compositor frames. The asynchronous late-presenter
                # cleanup used to protect only the source HWND captured when the
                # worker started; a replacement live presenter could therefore be
                # mistaken for an auxiliary window and hidden, leaving DWM mirroring
                # a stale/black source. Keep all plausible live app presenters mapped
                # off-screen and hide only auxiliary presenter classes. Also protect
                # every source handle currently known by the shared session.
                protected_sources = {
                    _hwnd_int(source_hwnd or 0),
                    _hwnd_int(session.get("dwm_thumbnail_source") or 0),
                    _hwnd_int(session.get("dwm_source_hwnd") or 0),
                    _hwnd_int(session.get("embedded_hwnd") or 0),
                }
                is_live_presenter_class = (cls.value == "Chrome_WidgetWin_1")
                if hwnd_i not in protected_sources and not is_live_presenter_class:
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



def _dwm_input_offset_for_crop(crop_left, crop_top, render_offset):
    """Translate DWM destination pixels into the RenderWidgetHost origin.

    The DWM thumbnail can deliberately keep a previously committed crop while
    Chromium is settling on a new native-chrome height.  In that state the
    visible page is shifted inside the thumbnail even though CDP coordinates
    still start at the RenderWidgetHost's (0, 0).  The correction is therefore
    ``source_crop_origin - render_host_origin``.

    This is the exact symptom behind clicks landing *below* the visible target:
    when the renderer starts lower than the active crop, the Y correction is
    negative, so the visible cursor position maps back up to the real DOM point.
    """
    if not render_offset:
        return 0.0, 0.0
    try:
        render_x, render_y = float(render_offset[0]), float(render_offset[1])
        dx = float(crop_left) - render_x
        dy = float(crop_top) - render_y
        # Ignore obviously stale HWND geometry instead of making input unusable.
        if abs(dx) > 240.0 or abs(dy) > 360.0:
            return 0.0, 0.0
        return dx, dy
    except Exception:
        return 0.0, 0.0


def _resize_existing_dwm_thumbnail_fast(session, width: int, height: int):
    """Fast steady-state DWM resize path.

    Once the thumbnail/source/crop contract is established, normal window
    resizes should not repeat the expensive cold attach work (window-tree
    enumeration, presenter parking, crop discovery and compositor flushes).
    Return True on success, None when the caller should fall back to the full
    positioning path.
    """
    if os.name != "nt" or not session or session.get("native_embed_mode") != "dwm-thumbnail":
        return None
    thumb_handle = _hwnd_int(session.get("dwm_thumbnail_handle") or 0)
    source = _hwnd_int(session.get("dwm_thumbnail_source") or session.get("dwm_source_hwnd") or 0)
    destination = _hwnd_int(session.get("dwm_thumbnail_destination") or session.get("dwm_destination_hwnd") or 0)
    if not thumb_handle or not source or not destination:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _typed_user32()
        if not user32.IsWindow(_as_hwnd(source)) or not user32.IsWindow(_as_hwnd(destination)):
            return None

        width, height = max(1, int(width)), max(1, int(height))
        old_contract = tuple(session.get("dwm_thumbnail_pixel_contract") or ())
        if old_contract == (width, height):
            session["dwm_fast_resize_noop_count"] = int(session.get("dwm_fast_resize_noop_count") or 0) + 1
            return True

        nonclient = session.get("dwm_source_nonclient_margins") or (0, 0)
        try:
            nonclient_w, nonclient_h = max(0, int(nonclient[0])), max(0, int(nonclient[1]))
        except Exception:
            nonclient_w = nonclient_h = 0
        chrome_h = max(0, int(session.get("dwm_custom_chrome_height") or 0))
        target_src_w = max(1, width + nonclient_w)
        target_src_h = max(1, height + chrome_h + nonclient_h)
        park_x, park_y = session.get("dwm_source_park_position") or (-32000, -32000)
        cached_target = tuple(session.get("dwm_source_target_size") or ())
        if cached_target != (target_src_w, target_src_h):
            HWND_BOTTOM = 1
            SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(
                _as_hwnd(source), _as_hwnd(HWND_BOTTOM), int(park_x), int(park_y),
                target_src_w, target_src_h, SWP_NOACTIVATE,
            )
            session["dwm_source_target_size"] = (target_src_w, target_src_h)
            session["dwm_fast_source_resize_count"] = int(session.get("dwm_fast_source_resize_count") or 0) + 1

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

        dwmapi.DwmUpdateThumbnailProperties.argtypes = [HTHUMBNAIL, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
        dwmapi.DwmUpdateThumbnailProperties.restype = HRESULT
        DWM_TNP_RECTDESTINATION = 0x00000001
        DWM_TNP_RECTSOURCE = 0x00000002
        props = DWM_THUMBNAIL_PROPERTIES()
        props.dwFlags = DWM_TNP_RECTDESTINATION | DWM_TNP_RECTSOURCE
        props.rcDestination = wintypes.RECT(0, 0, width, height)
        props.rcSource = wintypes.RECT(0, chrome_h, width, chrome_h + height)
        hr = int(dwmapi.DwmUpdateThumbnailProperties(HTHUMBNAIL(thumb_handle), ctypes.byref(props)))
        if hr != 0:
            session["dwm_fast_resize_hresult"] = f"0x{hr & 0xffffffff:08X}"
            return None

        # Intentionally do not DwmFlush() here. DWM property updates are queued
        # to the compositor; synchronously flushing every interactive resize
        # frame turns a cheap geometry update into a CPU/GPU pipeline stall.
        session["dwm_thumbnail_destination_rect"] = (0, 0, width, height)
        session["dwm_thumbnail_source_rect"] = (0, chrome_h, width, chrome_h + height)
        # v10.5.5: keep pointer hit testing anchored to the *actual* renderer
        # origin, not merely to the currently committed crop.  A navigation can
        # temporarily keep an older crop while Chromium reports a new toolbar
        # height; without this correction, clicking a visible input may hit the
        # element below it and only work when the cursor is placed above it.
        cached_render_offset = (
            session.get("dwm_source_render_offset_after_expand")
            or session.get("dwm_source_render_offset")
        )
        session["dwm_input_offset"] = _dwm_input_offset_for_crop(
            0, chrome_h, cached_render_offset
        )
        session["dwm_thumbnail_pixel_contract"] = (width, height)
        session["dwm_fast_resize_count"] = int(session.get("dwm_fast_resize_count") or 0) + 1
        session["dwm_last_resize_path"] = "fast"
        return True
    except Exception as exc:
        session["dwm_fast_resize_error"] = f"{type(exc).__name__}: {exc}"
        return None


def detach_embedded_chromium_dwm_thumbnail():
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


def request_embedded_chromium_dwm_recrop():
    """Force the next DWM resize through the full crop-discovery path."""
    if not _EDGE_SESSION:
        return False
    _EDGE_SESSION["dwm_force_full_recrop"] = True
    return True

def request_embedded_chromium_dwm_reregister():
    """Force a cold DWM thumbnail registration on the next native resize.

    Minimize/restore can leave a numerically valid HTHUMBNAIL whose visual
    composition is no longer attached to the destination.  A cold registration
    plus DwmFlush is the reliable restore boundary.
    """
    if not _EDGE_SESSION:
        return False
    _EDGE_SESSION["dwm_force_full_recrop"] = True
    _EDGE_SESSION["dwm_force_reregister"] = True
    return True

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
            # v9.6: DwmFlush already waits for the compositor to consume the
            # resize; an additional fixed 12 ms sleep only delays first reveal.

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
        source_render_x = None
        source_render_y = None
        if source_render_measurement:
            _, _, _, render, render_w, render_h, source_render_x, source_render_y = source_render_measurement
            session["dwm_navigation_recrop_render_hwnd"] = render
            session["dwm_source_render_hwnd"] = render
            session["dwm_source_render_offset"] = (source_render_x, source_render_y)
            session["dwm_source_render_size"] = (render_w, render_h)
        session["dwm_render_size_before_chrome_expand"] = (render_w, render_h) if render_w and render_h else None

        candidate_chrome_h = previous_chrome_h
        # v10.5.3: Chromium's native UI can be substantially taller than the
        # old 160 px guard on high-DPI systems or when Chromium exposes a full
        # browser-style window instead of the compact app frame.  The old cap
        # rejected a perfectly valid ~180-220 px RenderWidgetHost offset, which
        # made DWM mirror Chromium's tab strip + omnibox inside Tekzite.
        #
        # Keep a conservative sanity ceiling, but derive it from the available
        # viewport and leave room for a real page surface.  _live_render_host_crop
        # already treats top insets up to 360 px as plausible, so use the same
        # upper bound here rather than a conflicting smaller threshold.
        chrome_inset_limit = min(360, max(160, int(height) - 150))
        session["dwm_chrome_inset_limit"] = int(chrome_inset_limit)
        if source_render_y is not None and 0 < int(source_render_y) <= chrome_inset_limit:
            candidate_chrome_h = int(source_render_y)
            session["dwm_chrome_measurement"] = "source-render-offset"
        elif render_h:
            # When the source is already expanded by the locked chrome height,
            # the renderer should match the viewport.  Only infer from a
            # shortfall when we have no established lock yet.
            shortfall = int(height) - int(render_h)
            if previous_chrome_h == 0 and 0 < shortfall <= chrome_inset_limit:
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
            # v9.6: DwmFlush already synchronizes the resize with the compositor.
            # Sleeping another 12 ms here was a fixed cold-start tax.
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
                source_render_x, source_render_y = ox_after, oy_after
        target_src_h = final_target_src_h

        source_crop = (0, int(chrome_h), 0, 0)
        crop_top = int(chrome_h)
        render_offset_for_input = (
            (source_render_x, source_render_y)
            if source_render_x is not None and source_render_y is not None
            else None
        )
        session["dwm_input_render_origin"] = render_offset_for_input
        session["dwm_input_crop_origin"] = (0, crop_top)
        session["dwm_input_offset"] = _dwm_input_offset_for_crop(
            0, crop_top, render_offset_for_input
        )
        session["dwm_input_alignment_mode"] = "crop-minus-render-origin"
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
        now_mono = time.monotonic()
        last_park = float(session.get("dwm_presenter_last_park_at") or 0.0)
        if (not session.get("dwm_thumbnail_handle")) or (now_mono - last_park) >= 1.0:
            _park_chromium_top_level_presenters(session, source, passes=1)
            session["dwm_presenter_last_park_at"] = now_mono

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
        dwmapi.DwmRegisterThumbnail.restype = HRESULT
        dwmapi.DwmUpdateThumbnailProperties.argtypes = [HTHUMBNAIL, ctypes.POINTER(DWM_THUMBNAIL_PROPERTIES)]
        dwmapi.DwmUpdateThumbnailProperties.restype = HRESULT
        dwmapi.DwmUnregisterThumbnail.argtypes = [HTHUMBNAIL]
        dwmapi.DwmUnregisterThumbnail.restype = HRESULT
        dwmapi.DwmFlush.argtypes = []
        dwmapi.DwmFlush.restype = HRESULT

        force_reregister = bool(session.pop("dwm_force_reregister", False))
        old_thumb = session.get("dwm_thumbnail_handle")
        old_source = _hwnd_int(session.get("dwm_thumbnail_source") or 0)
        old_destination = _hwnd_int(session.get("dwm_thumbnail_destination") or 0)
        thumb = None
        if old_thumb and old_source == source and old_destination == destination and not force_reregister:
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
            if force_reregister:
                session["dwm_restore_reregister_count"] = int(session.get("dwm_restore_reregister_count") or 0) + 1

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
        # Only the cold/new-registration path needs a synchronous compositor
        # barrier. Steady-state resizes use _resize_existing_dwm_thumbnail_fast
        # and deliberately avoid DwmFlush() to prevent frame-by-frame stalls.
        if force_reregister or not old_thumb or old_source != source or old_destination != destination:
            dwmapi.DwmFlush()
            session["dwm_cold_register_flush_count"] = int(session.get("dwm_cold_register_flush_count") or 0) + 1
        # v9.6: do not hold first reveal behind three 40 ms presenter-settle
        # passes. An immediate presenter pass already ran above. Late auxiliary
        # Chromium windows are maintenance work and can be parked asynchronously.
        late_park_due = (time.monotonic() - float(session.get("dwm_presenter_last_park_at") or 0.0)) >= 1.0
        if not session.get("dwm_presenter_park_thread_running") and (not old_thumb or late_park_due):
            session["dwm_presenter_park_thread_running"] = True
            def _park_late_presenters():
                try:
                    _park_chromium_top_level_presenters(session, source, passes=3, settle_delay=0.04)
                    session["dwm_presenter_last_park_at"] = time.monotonic()
                except Exception:
                    pass
                finally:
                    session["dwm_presenter_park_thread_running"] = False
            threading.Thread(target=_park_late_presenters, name="tekzite-dwm-presenter-park", daemon=True).start()

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
        session["dwm_full_reflow_count"] = int(session.get("dwm_full_reflow_count") or 0) + 1
        session["dwm_last_resize_path"] = "full"
        return True
    except Exception as exc:
        session["dwm_thumbnail_registered"] = False
        session["dwm_thumbnail_visible"] = False
        session["dwm_thumbnail_error"] = f"{type(exc).__name__}: {exc}"
        session["native_overlay_error"] = session["dwm_thumbnail_error"]
        return False

def _wait_for_live_embed_owner(session, candidate, width, height):
    """Allow a short owner-transition window without embedding an invalid HWND.

    The normal path has exactly one validation and no delay. Retries run on
    the navigation worker, before presentation, and retain the live-host check.
    """
    owner = _validate_embed_owner_before_reparent(session, candidate, width, height)
    session["embed_owner_wait_attempts"] = 1
    if owner:
        session.pop("pre_attach_owner_error", None)
        return owner
    # Re-activate only the intended page, never create a replacement tab/window.
    target = session.get("target_id")
    if target:
        try:
            _browser_cdp_call(session, "Target.activateTarget", {"targetId": target}, timeout=1)
        except Exception as exc:
            session["embed_owner_activation_error"] = str(exc)
    for attempt in range(2, 5):
        process = session.get("process")
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.05)
        owner = _validate_embed_owner_before_reparent(session, candidate, width, height)
        session["embed_owner_wait_attempts"] = attempt
        if owner:
            session.pop("pre_attach_owner_error", None)
            return owner
    return 0


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
    hwnd = _wait_for_live_embed_owner(session, hwnd, width, height)
    if not hwnd:
        raise RuntimeError("Chromium page owner lost its live render host before embedding")

    # v4.48: prime Chromium/DWM while the owner is still a genuine top-level
    # window.  Doing this after WS_CHILD/SetParent is too late on some builds.
    _prime_chromium_compositor_surface(session, width, height)

    # Priming itself can trigger a late Chromium widget/RWH migration. Recheck
    # once more at the last safe point before SetParent(). If ownership moved,
    # prime the newly selected owner instead of carrying a dead compositor into
    # Tekzite.
    verified_hwnd = _wait_for_live_embed_owner(session, hwnd, width, height)
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
    """Load Chromium, using a strict cold-start gate and a fast hot-navigation path.

    v4.40 optionally binds the navigation to a dedicated Chromium target so
    each Tekzite tab can retain a live JS/media page without reloading it.

    Earlier builds attached Chromium before navigation.  That can race the
    compositor and leave Tekzite showing only its gray host until a manual
    title-bar activation.  The helper already starts 32,000 pixels off-screen,
    so it is safe to navigate there first, verify a paintable frame via CDP,
    and only then re-parent it into Tekzite.
    """
    # v9.1: distinguish cold bootstrap from steady-state navigation. Once the
    # native Chromium surface is already attached, a normal navigation must not
    # pay the first-start frame/input/reattach ceremony again. Page.navigate can
    # return as soon as Chromium accepts the navigation and the live DWM surface
    # will paint progressively, which materially improves perceived load time.
    session_was_running = _EDGE_SESSION is not None
    launch_geometry = _initial_chromium_launch_geometry(parent_hwnd, width, height) if attach_native else None
    first_native_bootstrap = bool(attach_native and not target_id and not create_new_target and not session_was_running)
    # v10.5.0: never launch the cold app window directly at an arbitrary site.
    # Redirects/canonicalization can change the URL before Tekzite claims the
    # app target, making strict target matching fail. Claim about:blank first,
    # then perform exactly one normal Page.navigate below.
    bootstrap_launch_url = "about:blank" if first_native_bootstrap else None
    session = _start_persistent_chromium_session(
        launch_geometry=launch_geometry, launch_url=bootstrap_launch_url
    )
    # v10.5.68: these are per-navigation facts, not persistent-session facts.
    # Leaving the hot-reuse marker set after one refresh made a later new-target
    # or recovery navigation inherit the wrong presentation path.
    session["hot_navigation_reused_native_surface"] = False
    session["hot_navigation_surface_probe_suppressed"] = False
    hot_native_navigation = bool(
        attach_native
        and session_was_running
        and target_id
        and not create_new_target
        and session.get("embedded_parent")
        and session.get("presentation_mode") == "native"
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
    session["native_direct_app_launch"] = False
    session["native_blank_bootstrap_launch"] = bool(
        first_native_bootstrap and str(session.get("launch_url") or "").lower() == "about:blank"
    )
    session["native_requested_initial_url"] = str(url or "about:blank") if first_native_bootstrap else None
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
            "about:blank" if first_native_bootstrap else str(url or "about:blank"),
            require_bootstrap=True,
        )

    # v6.5: never mutate document zoom before navigation.  Keep only the saved
    # preference in session state and let the destination document initialize
    # normally.  Zoom is applied after navigation once readyState is no longer
    # ``loading``.
    session["preferences_zoom_pre_navigation_applied"] = False

    # v9.2: native Chromium stays hidden behind the DWM destination while it
    # boots, so a separate *pre-attach* first-frame proof only duplicates work.
    # Attach immediately after Page.navigate and use the single attached-frame
    # gate below. Software presentation still needs the off-screen proof.
    session = navigate_embedded_chromium(
        url, wait_for_first_frame=bool((not attach_native) and (not hot_native_navigation)),
        target_id=target_id, create_new_target=create_new_target,
    )
    # v9.1 hot navigation: do not synchronously invoke the zoom extension while
    # the destination document is just starting. The UI already schedules zoom
    # verification asynchronously; keeping it out of this worker lets the DWM
    # surface start painting immediately after Page.navigate is accepted.
    if hot_native_navigation or preferred_zoom_percent == 100:
        # v9.2/v10.5.81: 100% is Chromium's native default, so synchronously
        # invoking the zoom extension during cold startup is pure latency on
        # every platform. This is especially important for Linux headless mode,
        # where an extension service worker may not wake before first paint.
        # Non-default zoom still applies before reveal; hot navigation remains
        # asynchronous.
        session["preferences_zoom_post_navigation_applied"] = False
        session["hot_navigation_fast_path"] = bool(hot_native_navigation)
    else:
        try:
            set_embedded_chromium_zoom(
                preferred_zoom_percent, target_id=session.get("target_id"), timeout=3
            )
            session["preferences_zoom_post_navigation_applied"] = True
        except Exception:
            session["preferences_zoom_post_navigation_applied"] = False
    if attach_native:
        if hot_native_navigation:
            # The source is already attached and the latency-sensitive CDP lanes
            # are already hot. Reattaching/waiting here only delays navigation.
            session["presentation_mode"] = "native"
            session["embedded_after_first_frame"] = True
            session["hot_navigation_reused_native_surface"] = True
            # v10.5.68: attached/first-frame diagnostics belong to the cold frame
            # gate. This hot path returns the same persistent session dictionary,
            # so leaving those values behind made the UI mistake previous-page
            # evidence for proof about the new renderer and run a premature screen
            # probe during the compositor swap.
            for stale_key in (
                "attached_frame_visual", "attached_frame_text_len",
                "attached_frame_nodes", "first_frame_text_len",
                "visible_surface_blank", "visible_surface_span",
                "visible_surface_dominant_ratio",
            ):
                session.pop(stale_key, None)
            session["hot_navigation_surface_probe_suppressed"] = True
            return session
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
        attached_ready = _wait_for_attached_first_frame(session, timeout=2.0)
        # v10.5.67: the first DWM registration can be valid a fraction before
        # Chromium's replacement RenderWidgetHost reaches its final geometry.
        # A single failed 2 s gate used to fall through and let the UI reveal
        # whatever DComp backing surface happened to exist, which is the same
        # race behind intermittent "Preparing Chromium frame" / black startup.
        # Cold bootstrap is hidden, so one bounded full recrop + readiness retry
        # is safe and far cheaper than exposing a broken frame and recovering
        # after the user can already see it.
        if not attached_ready:
            session["attached_frame_retry_attempted"] = True
            try:
                session["dwm_force_full_recrop"] = True
                resize_embedded_chromium(width, height)
            except Exception as exc:
                session["attached_frame_retry_error"] = type(exc).__name__
            attached_ready = _wait_for_attached_first_frame(session, timeout=2.0)
            session["attached_frame_retry_succeeded"] = bool(attached_ready)
        else:
            session["attached_frame_retry_attempted"] = False
            session["attached_frame_retry_succeeded"] = True
        if attached_ready:
            session["first_frame_ready"] = True
            session["first_frame_committed"] = True
            session["first_frame_generation"] = int(session.get("navigation_generation") or 0)
        # v8.8: warm every latency-sensitive CDP lane while the page is hidden,
        # then prove the *critical input lane* with a real renderer round-trip.
        # A DWM frame can be paintable a few milliseconds before CDP Input is
        # consumable; revealing in that gap creates the "I can see Startpage but
        # my first click does nothing" feeling.  The harmless mouseMoved probe
        # makes first visible frame == first interactive frame.
        # v9.2: only the critical input lane belongs on the reveal path. Scroll
        # and hover sockets are useful, but opening them serially delays the
        # first visible frame. Warm those in the background from the UI after
        # reveal while click/typing readiness remains guaranteed here.
        # v9.3: the frame gate itself opens and retains the critical input lane.
        _wait_for_embedded_chromium_input_ready(
            session, session.get("target_id"), timeout=1.2
        )
        # v10.5.6: DWM source/destination coordinates are native window pixels,
        # while CDP mouse coordinates are CSS viewport pixels.  On a scaled
        # Windows desktop (or any non-1.0 Chromium device scale), treating those
        # as the same space makes the hit point drift downward: a control can
        # only be clicked by aiming above it.  Capture the live renderer/CSS
        # ratio before the first visible frame so pointer mapping is correct on
        # the very first click.
        try:
            _refresh_dwm_input_metrics(
                session, session.get("target_id"), timeout=0.8
            )
        except Exception:
            pass
        # v9.0: make the first visible page immediately typeable as well as
        # clickable. Focus the page's natural search/text control while the
        # DWM source is still hidden, using the already-warmed critical lane.
        if first_native_bootstrap:
            _focus_embedded_chromium_startup_input(
                session, session.get("target_id"), timeout=0.8
            )
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
            force_full = bool(_EDGE_SESSION.pop("dwm_force_full_recrop", False))
            if _EDGE_SESSION.get("native_embed_mode") == "dwm-thumbnail" and not force_full:
                fast_result = _resize_existing_dwm_thumbnail_fast(_EDGE_SESSION, width, height)
                if fast_result is True:
                    return True
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
            dwmapi.DwmFlush.restype = HRESULT
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
            dwmapi.DwmFlush.restype = HRESULT
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


def set_embedded_chromium_presentation(mode: str, target_id: str = None, defer_io: bool = False):
    """Select the authoritative presentation path for the active Chromium tab.

    ``defer_io=True`` is the GUI-thread fast path. It updates the already-live
    Chromium session state without opening CDP channels, clearing metrics or
    starting a helper. The caller can queue a normal call on a worker afterward.
    This keeps Tk responsive during active-tab close/switch handoffs.
    """
    mode = "software" if str(mode).lower() == "software" else "native"
    if defer_io:
        session = _EDGE_SESSION
        if session is not None:
            session["presentation_mode"] = mode
            session["presentation_target_id"] = target_id
            if mode == "native":
                session["device_metrics_clear_deferred"] = True
        return mode

    session = _EDGE_SESSION or _start_persistent_chromium_session()
    session["presentation_mode"] = mode
    session["presentation_target_id"] = target_id
    if mode == "native":
        _clear_embedded_chromium_device_metrics(session, target_id=target_id)
        session["device_metrics_clear_deferred"] = False
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
    applied = _apply_native_chromium_zoom_extension(session, percent, timeout=max(3, timeout))
    if applied and session.get("presentation_mode") == "native":
        try:
            _refresh_dwm_input_metrics(session, target_id=target_id, timeout=min(1.0, max(0.3, float(timeout))))
        except Exception:
            pass
    return applied

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
    """Return live correction from the visible DWM crop to CDP page origin."""
    session = _EDGE_SESSION or {}
    try:
        x, y = session.get("dwm_input_offset") or (0, 0)
        return float(x), float(y)
    except Exception:
        return 0.0, 0.0




def _refresh_dwm_input_metrics(session, target_id=None, timeout: float = 1.0):
    """Cache the live native-pixel -> CSS-pixel transform for DWM input.

    DWM thumbnail rectangles and Win32 RenderWidgetHost geometry are expressed
    in native window pixels. CDP Input.dispatchMouseEvent and elementFromPoint
    are expressed in CSS viewport pixels. Windows display scaling and Chromium
    page zoom can therefore make a visible y=350 correspond to, for example,
    CSS y=280. Using the saved browser-zoom percentage alone cannot recover that
    relationship because it does not include the Windows/Chromium device scale.

    Prefer the ratio measured from the actual RenderWidgetHost dimensions to
    window.innerWidth/innerHeight. devicePixelRatio is retained as a robust
    fallback and diagnostic. No DOM is modified.
    """
    if not session or not session.get("port"):
        return 1.0, 1.0
    target_id = str(target_id or session.get("target_id") or "") or None
    try:
        result = _persistent_page_cdp_call(
            session,
            "Runtime.evaluate",
            {
                "expression": (
                    "(() => ({iw: window.innerWidth || 0, ih: window.innerHeight || 0, "
                    "dpr: window.devicePixelRatio || 1, "
                    "vv: (window.visualViewport && window.visualViewport.scale) || 1}))()"
                ),
                "returnByValue": True,
            },
            target_id=target_id,
            timeout=max(0.25, float(timeout)),
            purpose="input",
        )
        value = dict(((result or {}).get("result") or {}).get("value") or {})
        iw = float(value.get("iw") or 0.0)
        ih = float(value.get("ih") or 0.0)
        dpr = float(value.get("dpr") or 1.0)
        vv = float(value.get("vv") or 1.0)

        # v10.5.70: input must follow the pixels the user can actually see.
        # After maximize, the DWM destination/source crop can already have the
        # new viewport while the cached RenderWidgetHost measurement still
        # describes the pre-maximize window. Using that stale size makes text
        # selection and clicks drift away from the visible cursor. The committed
        # 1:1 DWM thumbnail contract is therefore authoritative for pointer
        # scaling; live render-host geometry remains a diagnostic fallback.
        visible_size = session.get("dwm_thumbnail_pixel_contract")
        render_size = (
            session.get("dwm_render_size_after_chrome_expand")
            or session.get("dwm_source_render_size")
            or session.get("render_host_embedded_size")
        )
        rw = rh = 0.0
        metric_source = "devicePixelRatio"
        for candidate, source_name in (
            (visible_size, "dwm-visible-contract/css-viewport"),
            (render_size, "render-host/css-viewport"),
        ):
            if not candidate:
                continue
            try:
                cw, ch = float(candidate[0]), float(candidate[1])
            except Exception:
                continue
            if cw > 0.0 and ch > 0.0:
                rw, rh = cw, ch
                metric_source = source_name
                break

        sx = (rw / iw) if rw > 0.0 and iw > 0.0 else 0.0
        sy = (rh / ih) if rh > 0.0 and ih > 0.0 else 0.0

        # A sane desktop scale is comfortably inside this range. Reject stale
        # HWND measurements rather than letting one bad geometry sample make
        # the whole page unclickable.
        def sane(v):
            return 0.5 <= float(v) <= 4.0

        if not sane(sx):
            sx = dpr if sane(dpr) else 1.0
        if not sane(sy):
            sy = dpr if sane(dpr) else sx

        # If one native dimension includes a transient compositor decoration,
        # the two ratios can diverge. devicePixelRatio is the browser's own
        # effective CSS/native scale and is safer than an obviously asymmetric
        # pair. Browser zoom is already represented in devicePixelRatio, so it
        # must not be multiplied by the saved zoom percentage again.
        if sane(dpr):
            denom = max(abs(sx), abs(sy), 1e-6)
            if abs(sx - sy) / denom > 0.12:
                sx = sy = dpr

        session["dwm_input_viewport_css"] = (iw, ih)
        session["dwm_input_device_pixel_ratio"] = dpr
        session["dwm_input_visual_viewport_scale"] = vv
        session["dwm_input_render_pixels"] = (rw, rh)
        session["dwm_input_css_scale_x"] = float(sx)
        session["dwm_input_css_scale_y"] = float(sy)
        session["dwm_input_scale_source"] = metric_source if rw and rh and iw and ih else "devicePixelRatio"
        session["dwm_input_metrics_error"] = None
        return float(sx), float(sy)
    except Exception as exc:
        session["dwm_input_metrics_error"] = f"{type(exc).__name__}: {exc}"
        return get_embedded_chromium_input_scale()


def refresh_embedded_chromium_dwm_input_metrics(target_id=None, timeout: float = 0.8):
    """Refresh the DWM native-pixel -> CSS hit-test contract after a viewport jump."""
    session = _EDGE_SESSION or {}
    if not session or session.get("presentation_mode") == "software":
        return get_embedded_chromium_input_scale()
    try:
        return _refresh_dwm_input_metrics(
            session,
            target_id=target_id or session.get("target_id"),
            timeout=max(0.25, float(timeout)),
        )
    except Exception:
        return get_embedded_chromium_input_scale()


def get_embedded_chromium_input_scale():
    """Return cached native-DWM-pixel -> CSS-pixel scale for pointer input."""
    session = _EDGE_SESSION or {}
    try:
        sx = float(session.get("dwm_input_css_scale_x") or 0.0)
        sy = float(session.get("dwm_input_css_scale_y") or 0.0)
        if 0.5 <= sx <= 4.0 and 0.5 <= sy <= 4.0:
            session["dwm_input_zoom_factor"] = (sx + sy) / 2.0
            session["dwm_input_zoom_active"] = abs(sx - 1.0) > 1e-6 or abs(sy - 1.0) > 1e-6
            return sx, sy
    except Exception:
        pass

    # Conservative fallback for an early event that arrives before the first
    # live metrics sample.  This keeps old native-zoom behavior while avoiding
    # speculative DPI scaling.
    try:
        if bool(session.get("native_zoom_extension_loaded")):
            percent = max(50, min(300, int(session.get("default_page_zoom_percent") or 100)))
            factor = float(percent) / 100.0
        else:
            factor = 1.0
    except Exception:
        factor = 1.0
    session["dwm_input_zoom_factor"] = factor
    session["dwm_input_zoom_active"] = abs(factor - 1.0) > 1e-6
    return factor, factor


def get_embedded_chromium_input_zoom_factor():
    """Compatibility scalar for diagnostics and older callers.

    New DWM input uses get_embedded_chromium_input_scale() so X/Y can be mapped
    independently.  Return their mean here to preserve the historical API.
    """
    sx, sy = get_embedded_chromium_input_scale()
    return (float(sx) + float(sy)) / 2.0


def dispatch_embedded_chromium_mouse(event_type: str, x: float, y: float, *,
                                     button: str = "none", buttons: int = None,
                                     delta_x: float = 0.0, delta_y: float = 0.0,
                                     click_count: int = 0, modifiers: int = 0,
                                     target_id: str = None, timeout: int = 3,
                                     purpose: str = "input"):
    """Forward pointer/wheel input over the tab's persistent CDP channel.

    v10.5.7 keeps CDP gesture metadata faithful to Chromium: mouseMoved uses
    clickCount=0, actual presses/releases provide their real single/double/triple
    count, and wheel modifier bits survive the DWM/Tk bridge.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return False
    params = {"type": str(event_type), "x": float(x), "y": float(y)}
    if modifiers:
        params["modifiers"] = int(modifiers)
    if event_type == "mouseWheel":
        params.update({"deltaX": float(delta_x), "deltaY": float(delta_y)})
    else:
        params.update({"button": button, "clickCount": int(click_count)})
        if buttons is not None:
            params["buttons"] = int(buttons)
    _persistent_page_cdp_call(
        session, "Input.dispatchMouseEvent", params,
        target_id=target_id, timeout=timeout, purpose=str(purpose or "input"),
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
        target_id=target_id, timeout=timeout, purpose="cursor",
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
        href: a ? String(a.href || '').slice(0, 32768) : '',
        image_src: img ? String(img.currentSrc || img.src || '').slice(0, 8192) : '',
        selected_text: sel.slice(0, 5000),
        editable: !!(el && (el.isContentEditable || /^(INPUT|TEXTAREA)$/.test(el.tagName || ''))),
        page_url: String(location.href || '').slice(0, 32768),
        page_title: String(document.title || '').slice(0, 1024)
      }};
    }})()"""
    result = _persistent_page_cdp_call(
        session, "Runtime.evaluate",
        {"expression": expr, "returnByValue": True},
        target_id=target_id, timeout=timeout,
    )
    value = (((result or {}).get("result") or {}).get("value"))
    if not isinstance(value, dict):
        return {}
    value["href"] = str(value.get("href") or "")[:MAX_PAGE_URL_CHARS]
    value["image_src"] = str(value.get("image_src") or "")[:MAX_FAVICON_URL_CHARS]
    value["page_url"] = str(value.get("page_url") or "")[:MAX_PAGE_URL_CHARS]
    value["page_title"] = str(value.get("page_title") or "")[:MAX_PAGE_TITLE_CHARS]
    return value


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



def get_embedded_chromium_site_info(*, target_id: str = None, timeout: int = 5):
    """Return privacy/security metadata for the current Chromium target.

    Cookie values are intentionally never returned. The UI receives counts and
    non-secret attributes only, together with origin-scoped storage usage when
    Chromium exposes it through CDP.
    """
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return {}

    expr = r'''(() => {
      let localCount = 0, sessionCount = 0;
      try { localCount = localStorage.length; } catch (_) {}
      try { sessionCount = sessionStorage.length; } catch (_) {}
      return {
        title: String(document.title || '').slice(0, 1024),
        url: String(location.href || '').slice(0, 32768),
        origin: String(location.origin || '').slice(0, 4096),
        scheme: String(location.protocol || '').replace(':', ''),
        host: String(location.hostname || '').slice(0, 1024),
        localStorageEntries: Number(localCount || 0),
        sessionStorageEntries: Number(sessionCount || 0),
        cookieEnabled: !!navigator.cookieEnabled,
        secureContext: !!window.isSecureContext
      };
    })()'''
    result = _persistent_page_cdp_call(
        session, "Runtime.evaluate",
        {"expression": expr, "returnByValue": True},
        target_id=target_id, timeout=timeout, purpose="site-info",
    )
    info = (((result or {}).get("result") or {}).get("value"))
    if not isinstance(info, dict):
        info = {}
    info["title"] = str(info.get("title") or "")[:MAX_PAGE_TITLE_CHARS]
    info["url"] = str(info.get("url") or "")[:MAX_PAGE_URL_CHARS]
    info["origin"] = str(info.get("origin") or "")[:MAX_ORIGIN_CHARS]
    info["host"] = str(info.get("host") or "")[:MAX_HOST_CHARS]

    url = str(info.get("url") or "")
    origin = str(info.get("origin") or "")
    info["cookieCount"] = 0
    info["cookies"] = []
    if url.startswith(("http://", "https://")):
        try:
            cookie_result = _persistent_page_cdp_call(
                session, "Network.getCookies", {"urls": [url]},
                target_id=target_id, timeout=timeout, purpose="site-info",
            )
            cookies = (cookie_result or {}).get("cookies") or []
            if isinstance(cookies, list):
                info["cookieCount"] = len(cookies)
                info["cookies"] = [
                    {
                        "name": str(item.get("name") or ""),
                        "domain": str(item.get("domain") or ""),
                        "secure": bool(item.get("secure")),
                        "httpOnly": bool(item.get("httpOnly")),
                        "sameSite": str(item.get("sameSite") or ""),
                    }
                    for item in cookies[:100] if isinstance(item, dict)
                ]
        except Exception:
            pass

    info["securityState"] = "secure" if str(info.get("scheme")) == "https" else "neutral"
    info["schemeIsCryptographic"] = str(info.get("scheme")) == "https"
    try:
        _persistent_page_cdp_call(
            session, "Security.enable", {}, target_id=target_id,
            timeout=timeout, purpose="site-info",
        )
        security = _persistent_page_cdp_call(
            session, "Security.getSecurityState", {}, target_id=target_id,
            timeout=timeout, purpose="site-info",
        )
        if isinstance(security, dict):
            info["securityState"] = str(security.get("securityState") or info["securityState"])
            info["schemeIsCryptographic"] = bool(
                security.get("schemeIsCryptographic", info["schemeIsCryptographic"])
            )
            explanations = security.get("explanations") or []
            if isinstance(explanations, list):
                info["securityExplanations"] = [
                    str(row.get("summary") or row.get("description") or "")
                    for row in explanations[:10] if isinstance(row, dict)
                ]
    except Exception:
        pass

    info["usageBytes"] = None
    info["quotaBytes"] = None
    info["usageBreakdown"] = []
    if origin.startswith(("http://", "https://")):
        try:
            usage = _persistent_page_cdp_call(
                session, "Storage.getUsageAndQuota", {"origin": origin},
                target_id=target_id, timeout=timeout, purpose="site-info",
            )
            if isinstance(usage, dict):
                info["usageBytes"] = usage.get("usage")
                info["quotaBytes"] = usage.get("quota")
                breakdown = usage.get("usageBreakdown") or []
                if isinstance(breakdown, list):
                    info["usageBreakdown"] = [
                        {"type": str(row.get("storageType") or ""), "bytes": row.get("usage")}
                        for row in breakdown if isinstance(row, dict) and row.get("usage")
                    ]
        except Exception:
            pass
    return info


def clear_embedded_chromium_site_data(*, target_id: str = None, timeout: int = 5):
    """Clear Chromium data for only the current page origin."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    if not session or not session.get("port"):
        return False
    result = _persistent_page_cdp_call(
        session, "Runtime.evaluate",
        {"expression": "String(location.origin || '')", "returnByValue": True},
        target_id=target_id, timeout=timeout, purpose="site-info",
    )
    origin = str((((result or {}).get("result") or {}).get("value")) or "")
    if not origin.startswith(("http://", "https://")):
        return False
    _persistent_page_cdp_call(
        session, "Storage.clearDataForOrigin",
        {"origin": origin, "storageTypes": "all"},
        target_id=target_id, timeout=timeout, purpose="site-info",
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
        title: String(document.title || '').slice(0, 1024),
        url: String(location.href || '').slice(0, 32768),
        readyState: String(document.readyState || '').slice(0, 32),
        favicon: (icon ? String(icon.href || '') : ((location.protocol === 'http:' || location.protocol === 'https:') ? String(new URL('/favicon.ico', location.href)) : '')).slice(0, 8192),
        audible: !!Array.from(document.querySelectorAll('audio,video')).find(m => !m.paused && !m.ended && m.readyState > 1)
      };
    })()'''
    result = _persistent_page_cdp_call(
        session, 'Runtime.evaluate',
        {'expression': expr, 'returnByValue': True},
        target_id=target_id, timeout=timeout, purpose='page-state', internal_source='page-state/metadata',
    )
    value = (((result or {}).get('result') or {}).get('value'))
    if not isinstance(value, dict):
        return {}
    value['title'] = str(value.get('title') or '')[:MAX_PAGE_TITLE_CHARS]
    value['url'] = str(value.get('url') or '')[:MAX_PAGE_URL_CHARS]
    value['favicon'] = str(value.get('favicon') or '')[:MAX_FAVICON_URL_CHARS]
    if include_favicon and value.get('favicon'):
        try:
            raw = fetch_favicon_bytes(value['favicon'])
            if raw:
                value['favicon_b64'] = base64.b64encode(raw).decode('ascii')
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
            url: String(location.href || '').slice(0, 32768), title: String(document.title || '').slice(0, 1024),
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


def close_embedded_chromium(clear_profile=False, graceful=False, timeout=6.0):
    """Serialize shutdown against concurrent Chromium bootstrap/recovery.

    Normal application exit should ask Chromium to close itself so its cookie
    store, local storage and profile preferences are durably flushed.  The old
    unconditional ``taskkill /F`` path could discard a just-completed logout
    and make Google/YouTube appear signed back in on the next launch.  Recovery
    callers keep the historical force-close behavior unless they explicitly
    request ``graceful=True``.
    """
    with _EDGE_SESSION_LOCK:
        if graceful and _EDGE_SESSION:
            session = _EDGE_SESSION
            profile = str(session.get("profile") or "")
            if _close_embedded_chromium_cleanly_for_auth_unlocked(timeout=timeout):
                if clear_profile and profile:
                    removed = bool(remove_profile_tree(profile))
                    try:
                        _COOKIE_JAR.clear()
                        fetch_bytes.cache_clear()
                        fetch_document.cache_clear()
                    except Exception:
                        pass
                    return removed
                return True
            # A truly hung helper must not keep Tekzite alive forever.  Only
            # after the bounded graceful close has failed do we fall back to
            # the existing teardown path.
        return _close_embedded_chromium_unlocked(clear_profile=clear_profile)


def _close_embedded_chromium_unlocked(clear_profile=False):
    """Shut down Chromium; optionally erase all compatibility profile data."""
    global _EDGE_SESSION
    session = _EDGE_SESSION
    _EDGE_SESSION = None
    if session:
        session_loopback_port = session.get("port")
        thumb = session.get("dwm_thumbnail_handle")
        if thumb and os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
                dwmapi.DwmUnregisterThumbnail.argtypes = [wintypes.HANDLE]
                dwmapi.DwmUnregisterThumbnail.restype = HRESULT
                dwmapi.DwmUnregisterThumbnail(wintypes.HANDLE(_hwnd_int(thumb)))
            except Exception:
                pass
        _close_persistent_page_cdp_channels(session)
        _close_persistent_browser_cdp_channel(session)
        process = session.get("process")
        if process is not None and process.poll() is None:
            _terminate_helper_process_tree(process)
        profile = session.get("profile") or ""
        _clear_profile_owner(profile, getattr(process, "pid", None))
        if clear_profile and profile:
            session["profile_cleanup_succeeded"] = bool(remove_profile_tree(profile))
            if not session["profile_cleanup_succeeded"]:
                session["profile_cleanup_error"] = "profile directory remained after retry cleanup"
        if session_loopback_port:
            revoke_loopback_port(session_loopback_port)
    if clear_profile:
        try:
            _COOKIE_JAR.clear()
        except Exception:
            pass
        try:
            fetch_favicon_bytes.cache_clear()
            fetch_bytes.cache_clear()
            fetch_document.cache_clear()
        except Exception:
            pass
        try:
            with _INTERNAL_NETWORK_ACTIVITY_LOCK:
                _INTERNAL_NETWORK_ACTIVITY.clear()
        except Exception:
            pass

def _extract_session_cookies(response, request):
    try:
        _COOKIE_JAR.extract_cookies(response, request)
    except Exception:
        # Test doubles and unusual response wrappers may not expose the full
        # urllib response API; cookie persistence is best-effort there.
        pass


FAVICON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/png,image/x-icon,image/vnd.microsoft.icon,image/jpeg,image/gif,image/webp,*/*;q=0.1",
    "DNT": "1",
    "Sec-GPC": "1",
}
MAX_FAVICON_BYTES = 512 * 1024


def _favicon_target_is_local(host: str) -> bool:
    """Reject page-controlled favicon targets that explicitly name local space."""
    host = str(host or "").strip().rstrip(".").lower()
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".lan", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(not ip.is_global)


@lru_cache(maxsize=256)
def fetch_favicon_bytes(url: str) -> bytes:
    """Fetch a favicon as Tekzite-owned traffic, never as page JavaScript.

    No page/session cookies, Authorization, Origin or Referer are added. Public
    HTTP(S) requests still travel through Tekzite Network. Explicit local/private
    targets are rejected so a page-controlled icon URL cannot become a local
    network probe. Public-name DNS rebinding remains blocked by Tekzite Network.
    """
    url = str(url or "").strip()[:MAX_FAVICON_URL_CHARS]
    if not url:
        return b""
    if url.lower().startswith("data:"):
        try:
            header, separator, payload = url.partition(",")
            if not separator:
                return b""
            raw = base64.b64decode(payload, validate=False) if ";base64" in header.lower() else unquote_to_bytes(payload)
            return raw if 0 < len(raw) <= MAX_FAVICON_BYTES else b""
        except Exception:
            return b""

    try:
        parts = urlsplit(url)
        scheme = str(parts.scheme or "").lower()
        host = str(parts.hostname or "").strip().rstrip(".").lower()
    except Exception:
        return b""
    if scheme not in {"http", "https"} or _favicon_target_is_local(host):
        return b""

    _record_internal_network_activity(url, purpose="Tekzite favicon fetch", resource="Favicon")
    request = Request(url, headers=FAVICON_HEADERS, method="GET")
    try:
        with _network_urlopen(request, timeout=SUBRESOURCE_TIMEOUT) as response:
            final_url = str(response.geturl() or url)
            final = urlsplit(final_url)
            if str(final.scheme or "").lower() not in {"http", "https"} or _favicon_target_is_local(final.hostname or ""):
                return b""
            try:
                declared = int(response.headers.get("Content-Length") or 0)
            except Exception:
                declared = 0
            if declared > MAX_FAVICON_BYTES:
                return b""
            raw = response.read(MAX_FAVICON_BYTES + 1)
            if not raw or len(raw) > MAX_FAVICON_BYTES:
                return b""
            return raw
    except Exception:
        return b""


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


def set_embedded_chromium_permission(origin: str, permission: str, setting: str, *, timeout: int = 4):
    """Apply one site permission to Chromium through the browser DevTools domain.

    Tekzite persists the policy itself; this function only applies it to the
    current Chromium session. ``setting`` is one of granted/denied/prompt.
    """
    origin = str(origin or '').strip()
    permission = str(permission or '').strip()
    setting = str(setting or '').strip().lower()
    if not origin.startswith(('http://', 'https://')):
        raise ValueError('A normal http/https origin is required')
    if setting not in {'granted', 'denied', 'prompt'}:
        raise ValueError('Permission setting must be granted, denied, or prompt')
    allowed = {
        'notifications', 'geolocation', 'audioCapture', 'videoCapture',
        'clipboardReadWrite', 'clipboardSanitizedWrite', 'sensors', 'midi', 'midiSysex',
    }
    if permission not in allowed:
        raise ValueError('Unsupported permission')
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    _browser_cdp_call(
        session, 'Browser.setPermission',
        {'permission': {'name': permission}, 'setting': setting, 'origin': origin},
        timeout=timeout,
    )
    return True


def get_embedded_chromium_process_info(*, timeout: int = 4):
    """Return Chromium process CPU metadata for Tekzite's Task Manager."""
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    result = _browser_cdp_call(session, 'SystemInfo.getProcessInfo', timeout=timeout)
    rows = result.get('processInfo', []) if isinstance(result, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def get_embedded_chromium_target_metrics(target_id: str, *, timeout: int = 3):
    """Return lightweight renderer metrics for one live Tekzite tab target."""
    if not target_id:
        return {}
    session = _EDGE_SESSION or _start_persistent_chromium_session(timeout=min(timeout, 8))
    try:
        _persistent_page_cdp_call(
            session, 'Performance.enable', {}, target_id=target_id,
            timeout=timeout, purpose='task-manager',
        )
    except Exception:
        pass
    result = _persistent_page_cdp_call(
        session, 'Performance.getMetrics', {}, target_id=target_id,
        timeout=timeout, purpose='task-manager',
    )
    metrics = {}
    for item in (result or {}).get('metrics', []):
        if isinstance(item, dict) and item.get('name'):
            metrics[str(item['name'])] = item.get('value')
    return metrics

