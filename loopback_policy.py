"""Process-local loopback egress policy for Tekzite's Python processes.

The main Tekzite process needs only two classes of outbound loopback TCP
connections: the Tekzite Network proxy and Chromium's DevTools/CDP endpoint.
All other Python-originated loopback connects can be denied without touching
Chromium's own networking or ordinary public-internet traffic.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import ipaddress
import sys
import os
import subprocess
import threading
import time

_LOCK = threading.RLock()
_ALLOWED = {}
_BLOCKED = deque(maxlen=64)
_ENABLED = False
_INSTALLED = False


def _loopback_host(host) -> bool:
    text = str(host or "").strip().strip("[]").lower()
    if text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def allow_loopback_port(port, purpose, *, owner="Tekzite"):
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if not (1 <= port <= 65535):
        return False
    with _LOCK:
        _ALLOWED[port] = {
            "port": port,
            "purpose": str(purpose or "Tekzite local service"),
            "owner": str(owner or "Tekzite"),
            "registered_at": time.time(),
        }
    return True


def revoke_loopback_port(port):
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    with _LOCK:
        return _ALLOWED.pop(port, None) is not None


def set_enabled(enabled=True):
    global _ENABLED
    with _LOCK:
        _ENABLED = bool(enabled)
    return _ENABLED


def is_enabled():
    with _LOCK:
        return bool(_ENABLED)


def is_loopback_allowed(host, port):
    if not _loopback_host(host):
        return True
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    with _LOCK:
        return (not _ENABLED) or port in _ALLOWED


def _record_block(host, port):
    row = {
        "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "host": str(host),
        "port": int(port) if str(port).isdigit() else str(port),
        "thread": threading.current_thread().name,
        "pid": os.getpid(),
        "role": str(os.environ.get("TEKZITE_LOOPBACK_ROLE", "python")),
    }
    with _LOCK:
        _BLOCKED.appendleft(row)
    log_path = str(os.environ.get("TEKZITE_LOOPBACK_AUDIT_LOG", "")).strip()
    if log_path:
        try:
            import json
            from pathlib import Path
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            if path.stat().st_size > 65536:
                tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-128:]
                path.write_text("\n".join(tail) + ("\n" if tail else ""), encoding="utf-8")
        except Exception:
            pass


def _audit_hook(event, args):
    if event != "socket.connect" or not is_enabled():
        return
    try:
        address = args[1]
        if not isinstance(address, tuple) or len(address) < 2:
            return
        host, port = address[0], address[1]
        if not _loopback_host(host):
            return
        if is_loopback_allowed(host, port):
            return
        _record_block(host, port)
        raise PermissionError(
            f"Tekzite blocked unexpected Python loopback connection to {host}:{port}"
        )
    except PermissionError:
        raise
    except Exception:
        # The policy must never break unrelated socket families because an
        # address shape was unfamiliar.
        return


def install(enabled=True):
    global _INSTALLED
    with _LOCK:
        if not _INSTALLED:
            sys.addaudithook(_audit_hook)
            _INSTALLED = True
        set_enabled(enabled)
    return True


def snapshot():
    with _LOCK:
        allowed = [dict(value) for _, value in sorted(_ALLOWED.items())]
        blocked = [dict(row) for row in _BLOCKED]
        return {
            "enabled": bool(_ENABLED),
            "installed": bool(_INSTALLED),
            "allowed": allowed,
            "blocked": blocked,
        }


def purpose_for_port(port):
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    with _LOCK:
        row = _ALLOWED.get(port)
        return dict(row) if row else None


def _split_endpoint(value):
    text = str(value or "").strip()
    if text.startswith("[") and "]:" in text:
        host, port = text[1:].rsplit("]:", 1)
    elif ":" in text:
        host, port = text.rsplit(":", 1)
    else:
        return text, None
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = None
    return host, port


def live_windows_loopback_connections(pids=None):
    """Return current Windows TCP rows involving loopback for selected PIDs.

    This is diagnostics only and intentionally uses Windows' own netstat rather
    than adding a resident network-monitoring dependency.
    """
    if os.name != "nt":
        return []
    wanted = {int(pid) for pid in (pids or []) if pid}
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, timeout=3, creationflags=flags,
            check=False,
        )
    except Exception:
        return []
    rows = []
    for raw in (result.stdout or "").splitlines():
        parts = raw.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, remote, state, pid_text = parts[1], parts[2], parts[3], parts[4]
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if wanted and pid not in wanted:
            continue
        local_host, local_port = _split_endpoint(local)
        remote_host, remote_port = _split_endpoint(remote)
        if not (_loopback_host(local_host) or _loopback_host(remote_host)):
            continue
        rows.append({
            "pid": pid,
            "local": local,
            "remote": remote,
            "state": state,
            "local_port": local_port,
            "remote_port": remote_port,
            "local_purpose": purpose_for_port(local_port),
            "remote_purpose": purpose_for_port(remote_port),
        })
    return rows


def shared_blocked_events(limit=64):
    path = str(os.environ.get("TEKZITE_LOOPBACK_AUDIT_LOG", "")).strip()
    if not path:
        return []
    try:
        import json
        from pathlib import Path
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit)):]
    except Exception:
        return []
    rows = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows
