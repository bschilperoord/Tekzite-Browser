#!/usr/bin/env python3
"""Tekzite Network Engine.

A small loopback-only HTTP/HTTPS CONNECT proxy used by Tekzite Browser.
TLS remains end-to-end: CONNECT tunnels bytes without decrypting HTTPS.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import ipaddress
import select
import socket
import socketserver
from loopback_policy import install as install_loopback_policy
import sys
import threading
import time
from urllib.parse import urlsplit

BUF = 64 * 1024
CONNECT_TIMEOUT = 15.0
IDLE_TIMEOUT = 60.0
MAX_HEADER_BYTES = 64 * 1024
MAX_HEADER_COUNT = 200
MAX_HEADER_LINE = 8 * 1024
MAX_CONCURRENT_CLIENTS = 64
LOG_LEVEL = "off"
ALLOW_BROWSER_TELEMETRY = False
ADBLOCK_ENABLED = True
ADBLOCK_POLICY = None
TRACKER_BLOCKING = True
HTTPS_FIRST = True
PRIVACY_STATS_PATH = None
_PRIVACY_STATS_LOCK = threading.RLock()
_PRIVACY_STATS = {
    "started_at": time.time(),
    "telemetry_blocked": 0,
    "trackers_blocked": 0,
    "ads_blocked": 0,
    "https_upgrades": 0,
}

# v10.5.71: privacy-preserving, current-session connection overview.
# Only destination host/port/protocol and aggregate status live in RAM. URL
# paths, query strings, headers and payloads are intentionally never retained.
INSTANCE_TOKEN = ""
CONNECTION_OVERVIEW_MAX_ROWS = 512
_CONNECTION_OVERVIEW_LOCK = threading.RLock()
_CONNECTION_OVERVIEW_STARTED_AT = time.time()
_CONNECTION_OVERVIEW_ROWS = {}
# Active upstream sockets are kept only in RAM so the browser UI can attach the
# original requested hostname to the exact Windows TCP socket.  This avoids
# misleading PTR names for CDN endpoints and never stores URL paths/content.
_ACTIVE_UPSTREAMS = {}


def _connection_overview_payload():
    with _CONNECTION_OVERVIEW_LOCK:
        rows = sorted(
            (dict(row) for row in _CONNECTION_OVERVIEW_ROWS.values()),
            key=lambda row: (int(row.get("active", 0) or 0) > 0, float(row.get("last_seen", 0) or 0)),
            reverse=True,
        )
        return {
            "started_at": float(_CONNECTION_OVERVIEW_STARTED_AT),
            "updated_at": time.time(),
            "connections": rows[:CONNECTION_OVERVIEW_MAX_ROWS],
            "active_upstreams": [dict(row) for row in _ACTIVE_UPSTREAMS.values()],
        }


def _socket_endpoint_parts(value):
    try:
        address = str(value[0]).split("%", 1)[0]
        port = int(value[1])
        return address, port
    except Exception:
        return "", 0


def _register_active_upstream(sock: socket.socket, host: str, protocol: str, client: socket.socket | None = None):
    """Associate one live helper socket with the requested host, RAM-only.

    When the Chromium-side client socket is available, retain only its endpoint
    tuple too. That lets the Live Socket View tie the localhost CONNECT socket
    to the exact upstream hostname without storing any request URL/content.
    """
    try:
        local_address, local_port = _socket_endpoint_parts(sock.getsockname())
        remote_address, remote_port = _socket_endpoint_parts(sock.getpeername())
    except Exception:
        return None
    client_address = client_port = proxy_address = proxy_port = ""
    if client is not None:
        try:
            client_address, client_port = _socket_endpoint_parts(client.getpeername())
            proxy_address, proxy_port = _socket_endpoint_parts(client.getsockname())
        except Exception:
            client_address, client_port, proxy_address, proxy_port = "", 0, "", 0
    if not local_port or not remote_port:
        return None
    key = (local_address, local_port, remote_address, remote_port)
    row = {
        "host": str(host or "").strip().rstrip(".").lower()[:253],
        "protocol": str(protocol or "TCP").upper()[:16],
        "local_address": local_address[:128],
        "local_port": local_port,
        "remote_address": remote_address[:128],
        "remote_port": remote_port,
        "opened_at": time.time(),
    }
    if client_address and int(client_port or 0):
        row.update({
            "client_address": str(client_address)[:128],
            "client_port": int(client_port),
            "proxy_address": str(proxy_address or "")[:128],
            "proxy_port": int(proxy_port or 0),
        })
    with _CONNECTION_OVERVIEW_LOCK:
        _ACTIVE_UPSTREAMS[key] = row
    return key


def _unregister_active_upstream(key):
    if key is None:
        return
    with _CONNECTION_OVERVIEW_LOCK:
        _ACTIVE_UPSTREAMS.pop(key, None)


def _record_connection(host: str, port: int, protocol: str, status: str, *, active_delta: int = 0, count: bool = True):
    """Record one destination in RAM without retaining URL/content information."""
    host = str(host or "").strip().rstrip(".").lower()[:253]
    if not host:
        return
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 0
    protocol = str(protocol or "TCP").upper()[:16]
    status = str(status or "unknown").lower()[:32]
    key = (host, port, protocol, status)
    now = time.time()
    with _CONNECTION_OVERVIEW_LOCK:
        row = _CONNECTION_OVERVIEW_ROWS.get(key)
        if row is None:
            if len(_CONNECTION_OVERVIEW_ROWS) >= CONNECTION_OVERVIEW_MAX_ROWS:
                inactive = [
                    (k, r) for k, r in _CONNECTION_OVERVIEW_ROWS.items()
                    if int(r.get("active", 0) or 0) <= 0
                ]
                if inactive:
                    oldest_key, _ = min(inactive, key=lambda item: float(item[1].get("last_seen", 0) or 0))
                    _CONNECTION_OVERVIEW_ROWS.pop(oldest_key, None)
            row = {
                "host": host, "port": port, "protocol": protocol, "status": status,
                "count": 0, "active": 0, "first_seen": now, "last_seen": now,
            }
            _CONNECTION_OVERVIEW_ROWS[key] = row
        if count:
            row["count"] = int(row.get("count", 0) or 0) + 1
            row["last_seen"] = now
        if active_delta:
            row["active"] = max(0, int(row.get("active", 0) or 0) + int(active_delta))
            row["last_seen"] = now


def _serve_internal_connection_overview(client: socket.socket, method: str, target: str, headers) -> bool:
    """Serve the RAM-only ledger to Tekzite Python over the existing proxy port.

    The endpoint is loopback-only and authenticated with the helper's random
    per-launch instance token. Chromium/web content never receives that token.
    """
    if str(method or "").upper() != "GET":
        return False
    try:
        parts = urlsplit(str(target or ""))
        host = (parts.hostname or "").lower().rstrip(".")
        path = parts.path or "/"
    except Exception:
        return False
    if host != "tekzite.internal" or path != "/__connections":
        return False
    supplied = _header_value(headers, "X-Tekzite-Instance-Token") or ""
    expected = str(INSTANCE_TOKEN or "")
    if not expected or not hmac.compare_digest(str(supplied), expected):
        client.sendall(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
        return True
    payload = json.dumps(_connection_overview_payload(), separators=(",", ":")).encode("utf-8")
    client.sendall(
        b"HTTP/1.1 200 OK\r\n"
        b"Connection: close\r\n"
        b"Cache-Control: no-store\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        + payload
    )
    return True

# v4.54: browser telemetry is denied in the proxy before DNS or an upstream
# socket is opened.  This list is deliberately limited to browser/vendor
# diagnostics endpoints; arbitrary website analytics are a separate concern.
TELEMETRY_HOSTS = {
    "vortex.data.microsoft.com",
    "settings-win.data.microsoft.com",
    "watson.telemetry.microsoft.com",
    "watson.events.data.microsoft.com",
    "telecommand.telemetry.microsoft.com",
    "oca.telemetry.microsoft.com",
    "sqm.telemetry.microsoft.com",
    "self.events.data.microsoft.com",
    "browser.events.data.msn.com",
}
TELEMETRY_SUFFIXES = (
    ".events.data.microsoft.com",
    ".telemetry.microsoft.com",
)

# v7.6: conservative built-in ad blocking. HTTPS stays end-to-end; Tekzite
# therefore blocks dedicated ad-serving hosts at CONNECT time instead of
# decrypting page traffic or rewriting HTML. Keep this list intentionally
# focused on advertising infrastructure so first-party site functionality is
# much less likely to be damaged.
ADBLOCK_HOSTS = {
    "pagead2.googlesyndication.com",
    "tpc.googlesyndication.com",
    "www.googleadservices.com",
    "googleadservices.com",
    "adservice.google.com",
    "securepubads.g.doubleclick.net",
    "static.doubleclick.net",
    "ads.youtube.com",
}
ADBLOCK_SUFFIXES = (
    ".doubleclick.net",
    ".googlesyndication.com",
    ".googleadservices.com",
    ".adnxs.com",
    ".adnxs-simple.com",
    ".taboola.com",
    ".taboolasyndication.com",
    ".outbrain.com",
    ".criteo.com",
    ".criteo.net",
    ".rubiconproject.com",
    ".pubmatic.com",
    ".openx.net",
    ".adsrvr.org",
    ".casalemedia.com",
    ".smartadserver.com",
    ".yieldmo.com",
    ".sharethrough.com",
    ".lijit.com",
    ".contextweb.com",
    ".bidswitch.net",
    ".advertising.com",
    ".zedo.com",
    ".moatads.com",
    ".media.net",
    ".serving-sys.com",
    ".adform.net",
    ".adform.com",
    ".quantserve.com",
)

# Dedicated analytics/fingerprinting endpoints. This list intentionally avoids
# broad first-party domains such as facebook.com so normal site visits are not
# turned into collateral damage.
TRACKER_HOSTS = {
    "www.google-analytics.com",
    "ssl.google-analytics.com",
    "analytics.google.com",
    "www.googletagmanager.com",
    "googletagmanager.com",
    "stats.g.doubleclick.net",
    "bat.bing.com",
    "www.clarity.ms",
    "clarity.ms",
    "script.hotjar.com",
    "static.hotjar.com",
    "vars.hotjar.com",
    "in.hotjar.com",
    "api.segment.io",
    "cdn.segment.com",
    "api-js.mixpanel.com",
    "api.mixpanel.com",
    "api2.amplitude.com",
    "bam.nr-data.net",
    "js-agent.newrelic.com",
    "browser-intake-datadoghq.com",
    "edge.fullstory.com",
    "rs.fullstory.com",
    "cdn.mouseflow.com",
    "heapanalytics.com",
    "cdn.heapanalytics.com",
    "app-measurement.com",
}
TRACKER_SUFFIXES = (
    ".google-analytics.com",
    ".googletagmanager.com",
    ".hotjar.com",
    ".hotjar.io",
    ".scorecardresearch.com",
    ".segment.io",
    ".mixpanel.com",
    ".amplitude.com",
    ".nr-data.net",
    ".fullstory.com",
    ".mouseflow.com",
    ".heapanalytics.com",
    ".app-measurement.com",
)


def _write_privacy_stats():
    if not PRIVACY_STATS_PATH:
        return
    try:
        path = os.path.abspath(PRIVACY_STATS_PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_PRIVACY_STATS, handle, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass


def _privacy_stat(key: str):
    with _PRIVACY_STATS_LOCK:
        _PRIVACY_STATS[key] = int(_PRIVACY_STATS.get(key, 0) or 0) + 1
        _write_privacy_stats()


def _is_tracker_host(host: str) -> bool:
    if not TRACKER_BLOCKING:
        return False
    host = (host or "").strip().rstrip(".").lower()
    return host in TRACKER_HOSTS or any(host.endswith(suffix) for suffix in TRACKER_SUFFIXES)


def _deny_tracker(client: socket.socket, host: str, method: str, port: int | None = None):
    _privacy_stat("trackers_blocked")
    _record_connection(host, port or (443 if str(method).upper() == "CONNECT" else 80), "HTTPS" if str(method).upper() == "CONNECT" else "HTTP", "blocked-tracker")
    _log("tracker_blocked", host=host, method=method)
    client.sendall(
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Connection: close\r\n"
        b"Content-Length: 0\r\n"
        b"X-Tekzite-Blocked: tracker\r\n\r\n"
    )


def _is_ad_host(host: str) -> bool:
    enabled = ADBLOCK_ENABLED
    if ADBLOCK_POLICY:
        try:
            with open(ADBLOCK_POLICY, encoding="utf-8") as handle:
                policy = json.load(handle)
            if isinstance(policy.get("enabled"), bool):
                enabled = policy["enabled"]
        except (OSError, ValueError, AttributeError):
            pass  # Keep the configured default when the policy is unreadable.
    if not enabled:
        return False
    host = (host or "").strip().rstrip(".").lower()
    return host in ADBLOCK_HOSTS or any(host.endswith(suffix) for suffix in ADBLOCK_SUFFIXES)

def _deny_ad(client: socket.socket, host: str, method: str, port: int | None = None):
    _privacy_stat("ads_blocked")
    _record_connection(host, port or (443 if str(method).upper() == "CONNECT" else 80), "HTTPS" if str(method).upper() == "CONNECT" else "HTTP", "blocked-ad")
    _log("ad_blocked", host=host, method=method)
    client.sendall(
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Connection: close\r\n"
        b"Content-Length: 0\r\n"
        b"X-Tekzite-Blocked: ad\r\n\r\n"
    )


# v6.9: Microsoft websites are no longer globally blocked.
# Privacy filtering is intentionally limited to the explicit browser/vendor
# telemetry endpoints below, so normal Microsoft pages, authentication, Office,
# Outlook, OneDrive, Bing and their required CDN/API traffic can load normally.

def _is_browser_telemetry_host(host: str) -> bool:
    if ALLOW_BROWSER_TELEMETRY:
        return False
    host = (host or "").strip().rstrip(".").lower()
    return host in TELEMETRY_HOSTS or any(host.endswith(suffix) for suffix in TELEMETRY_SUFFIXES)

def _deny_telemetry(client: socket.socket, host: str, method: str, port: int | None = None):
    _privacy_stat("telemetry_blocked")
    _record_connection(host, port or (443 if str(method).upper() == "CONNECT" else 80), "HTTPS" if str(method).upper() == "CONNECT" else "HTTP", "blocked-telemetry")
    _log("telemetry_blocked", host=host, method=method)
    client.sendall(
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Connection: close\r\n"
        b"Content-Length: 0\r\n"
        b"X-Tekzite-Blocked: browser-telemetry\r\n\r\n"
    )



def _log(event: str, **fields):
    if LOG_LEVEL == "off":
        return
    if LOG_LEVEL == "errors" and event not in {"client_error", "upstream_error", "fatal_error"}:
        return
    rec = {"ts": time.time(), "event": event, **fields}
    try:
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    except Exception:
        pass


def _split_host_port(authority: str, default_port: int):
    authority = authority.strip()
    if not authority or any(ch in authority for ch in "\r\n\x00"):
        raise ValueError("invalid empty/control-character authority")
    if authority.startswith("["):
        end = authority.find("]")
        if end < 0:
            raise ValueError("invalid IPv6 authority")
        host = authority[1:end]
        rest = authority[end + 1:]
        port = int(rest[1:]) if rest.startswith(":") else default_port
    elif authority.count(":") == 1:
        host, port_text = authority.rsplit(":", 1)
        port = int(port_text)
    else:
        host, port = authority, default_port
    host = host.strip()
    if not host or any(ch in host for ch in " /\\@\r\n\x00"):
        raise ValueError("invalid authority host")
    port = int(port)
    if not (1 <= port <= 65535):
        raise ValueError("invalid authority port")
    return host, port


def _recv_headers(sock: socket.socket, limit=MAX_HEADER_BYTES):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        remaining = int(limit) - len(data)
        if remaining <= 0:
            raise ValueError("request headers too large")
        chunk = sock.recv(min(BUF, remaining))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) >= limit and b"\r\n\r\n" not in data:
            raise ValueError("request headers too large")
    marker = data.find(b"\r\n\r\n")
    if marker < 0:
        raise ValueError("incomplete request headers")
    return bytes(data[:marker + 4]), bytes(data[marker + 4:])


def _parse_headers(header_blob: bytes):
    text = header_blob.decode("iso-8859-1", "strict")
    lines = text.split("\r\n")
    request_line = lines[0] if lines else ""
    if not request_line or len(request_line) > MAX_HEADER_LINE:
        raise ValueError("invalid/oversized request line")
    raw_headers = [line for line in lines[1:] if line]
    if len(raw_headers) > MAX_HEADER_COUNT:
        raise ValueError("too many request headers")
    headers = []
    token_chars = set("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    for line in raw_headers:
        if len(line) > MAX_HEADER_LINE:
            raise ValueError("request header line too large")
        if line[:1] in {" ", "\t"}:
            raise ValueError("obsolete folded request header rejected")
        if ":" not in line:
            raise ValueError("malformed request header")
        name, value = line.split(":", 1)
        name = name.strip()
        value = value.lstrip()
        if not name or any(ch not in token_chars for ch in name):
            raise ValueError("invalid request header name")
        if any((ord(ch) < 32 and ch != "\t") or ord(ch) == 127 for ch in value):
            raise ValueError("invalid control character in request header")
        headers.append((name, value))
    return request_line, headers


def _header_value(headers, name):
    wanted = name.lower()
    for k, v in headers:
        if k.lower() == wanted:
            return v
    return None


def _relay(a: socket.socket, b: socket.socket):
    """Relay a CONNECT tunnel with explicit backpressure buffering.

    The old relay used ``sendall()`` on non-blocking sockets.  On busy HTTP/2
    sites that can raise WSAEWOULDBLOCK when the destination send buffer is
    temporarily full, which used to tear down the entire tunnel.  Keep both
    ends non-blocking, buffer pending bytes per destination, and only write
    when select() reports that socket writable.
    """
    a.setblocking(False)
    b.setblocking(False)
    peers = {a: b, b: a}
    pending = {a: bytearray(), b: bytearray()}
    read_open = {a: True, b: True}
    write_shutdown = {a: False, b: False}
    max_pending = 4 * 1024 * 1024
    last = time.monotonic()

    while True:
        if (not read_open[a] and not read_open[b] and
                not pending[a] and not pending[b]):
            return
        if time.monotonic() - last >= IDLE_TIMEOUT:
            return

        readable = []
        for src in (a, b):
            if not read_open[src]:
                continue
            dst = peers[src]
            if len(pending[dst]) < max_pending:
                readable.append(src)
        writable = [sock for sock in (a, b) if pending[sock] and not write_shutdown[sock]]

        try:
            ready_r, ready_w, exceptional = select.select(
                readable, writable, [a, b], 1.0
            )
        except (OSError, ValueError):
            return
        if exceptional:
            return

        for src in ready_r:
            dst = peers[src]
            try:
                data = src.recv(BUF)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                read_open[src] = False
                data = b""
            if data:
                pending[dst].extend(data)
                last = time.monotonic()
            else:
                read_open[src] = False

        for dst in ready_w:
            buf = pending[dst]
            if not buf:
                continue
            try:
                sent = dst.send(buf)
            except (BlockingIOError, InterruptedError):
                continue
            except OSError:
                return
            if sent > 0:
                del buf[:sent]
                last = time.monotonic()

        # Preserve half-close semantics: after one source reaches EOF, let all
        # bytes already queued for its peer drain before closing that peer's
        # write side.  The reverse direction may continue independently.
        for src in (a, b):
            if read_open[src]:
                continue
            dst = peers[src]
            if pending[dst] or write_shutdown[dst]:
                continue
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            write_shutdown[dst] = True


def _tune_latency_socket(sock: socket.socket):
    """Favor low latency for Tekzite's loopback/TLS tunnel traffic."""
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass
    return sock


def _is_local_network_host(host: str) -> bool:
    value = (host or "").strip().strip("[]").lower()
    if value in {"localhost", "127.0.0.1", "::1"} or value.endswith((".local", ".lan", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(value)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return False


def _explicit_private_target(host: str) -> bool:
    """Return True only when the URL itself clearly names a local/private target."""
    value = (host or "").strip().strip("[]").rstrip(".").lower()
    if value in {"localhost"} or value.endswith((".local", ".lan", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not ip.is_global


def _resolved_upstream_endpoints(host: str, port: int):
    """Resolve once and reject public-name -> private-address DNS rebinding.

    A public-looking DNS name is allowed to connect only when *all* A/AAAA
    answers are globally routable. Explicit IP literals and conventional local
    names (.local/.lan/.home.arpa) may target private LAN space. Returning the
    exact getaddrinfo sockaddr also avoids resolving the name a second time
    between validation and connect.
    """
    explicit_private = _explicit_private_target(host)
    infos = socket.getaddrinfo(host, int(port), 0, socket.SOCK_STREAM)
    endpoints = []
    seen = set()
    for family, socktype, proto, canonname, sockaddr in infos:
        if not sockaddr:
            continue
        address = str(sockaddr[0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if not explicit_private and not ip.is_global:
            _log("dns_rebind_blocked", host=host, address=address, port=int(port))
            raise PermissionError(f"public hostname resolved to non-global address: {address}")
        # Never permit unspecified or multicast endpoints, even when supplied
        # literally. They are not useful browser destinations.
        if ip.is_unspecified or ip.is_multicast:
            raise PermissionError(f"unsafe upstream address: {address}")
        key = (family, socktype, proto, sockaddr)
        if key in seen:
            continue
        seen.add(key)
        endpoints.append((family, socktype, proto, sockaddr))
    if not endpoints:
        raise OSError(f"no usable addresses for {host}:{port}")
    return endpoints


def _open_upstream_connection(host: str, port: int, timeout=CONNECT_TIMEOUT):
    last_error = None
    for family, socktype, proto, sockaddr in _resolved_upstream_endpoints(host, port):
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            try:
                sock.close()
            except Exception:
                pass
    if last_error:
        raise last_error
    raise OSError(f"could not connect to {host}:{port}")


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client: socket.socket = self.request
        _tune_latency_socket(client)
        client.settimeout(CONNECT_TIMEOUT)
        try:
            header_blob, already = _recv_headers(client)
            if not header_blob:
                return
            request_line, headers = _parse_headers(header_blob)
            try:
                method, target, version = request_line.split(" ", 2)
            except ValueError:
                return
            token_chars = set("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
            if not method or any(ch not in token_chars for ch in method):
                raise ValueError("invalid HTTP method")
            if version not in {"HTTP/1.0", "HTTP/1.1"}:
                raise ValueError("unsupported HTTP version")
            if not target or len(target) > 16384 or any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
                raise ValueError("invalid HTTP request target")
            method_upper = method.upper()
            if _serve_internal_connection_overview(client, method_upper, target, headers):
                return
            if method_upper == "CONNECT":
                self._connect_tunnel(client, target)
            else:
                self._forward_http(client, method, target, version, headers, already)
        except Exception as exc:
            _log("client_error", client=str(self.client_address), error=repr(exc))
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except Exception:
                pass

    def _connect_tunnel(self, client, target):
        host, port = _split_host_port(target, 443)
        if _is_browser_telemetry_host(host):
            _deny_telemetry(client, host, "CONNECT", port)
            return
        if _is_tracker_host(host):
            _deny_tracker(client, host, "CONNECT", port)
            return
        if _is_ad_host(host):
            _deny_ad(client, host, "CONNECT", port)
            return
        _log("connect", host=host, port=port)
        try:
            upstream = _open_upstream_connection(host, port, timeout=CONNECT_TIMEOUT)
        except Exception:
            _record_connection(host, port, "HTTPS", "failed")
            raise
        _record_connection(host, port, "HTTPS", "allowed", active_delta=1)
        upstream_key = _register_active_upstream(upstream, host, "HTTPS", client=client)
        _tune_latency_socket(upstream)
        try:
            client.sendall(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: Tekzite-Network/1\r\n\r\n")
            _relay(client, upstream)
        finally:
            _unregister_active_upstream(upstream_key)
            _record_connection(host, port, "HTTPS", "allowed", active_delta=-1, count=False)
            try:
                upstream.close()
            except Exception:
                pass

    def _forward_http(self, client, method, target, version, headers, already):
        parts = urlsplit(target)
        if parts.scheme and parts.hostname:
            host = parts.hostname
            port = parts.port or (443 if parts.scheme == "https" else 80)
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
        else:
            host_header = _header_value(headers, "Host")
            if not host_header:
                raise ValueError("missing Host header")
            host, port = _split_host_port(host_header, 80)
            path = target or "/"

        if _is_browser_telemetry_host(host):
            _deny_telemetry(client, host, method.upper(), port)
            return
        if _is_tracker_host(host):
            _deny_tracker(client, host, method.upper(), port)
            return
        if _is_ad_host(host):
            _deny_ad(client, host, method.upper(), port)
            return
        if HTTPS_FIRST and int(port) == 80 and not _is_local_network_host(host):
            _privacy_stat("https_upgrades")
            _record_connection(host, port, "HTTP", "https-upgraded")
            location_host = host
            if ":" in host and not host.startswith("["):
                location_host = f"[{host}]"
            location = f"https://{location_host}{path}"
            encoded = location.encode("iso-8859-1", "replace")
            client.sendall(
                b"HTTP/1.1 307 Temporary Redirect\r\n"
                b"Connection: close\r\n"
                b"Cache-Control: no-store\r\n"
                b"Location: " + encoded + b"\r\n"
                b"Content-Length: 0\r\n\r\n"
            )
            return
        _log("http", method=method.upper(), host=host, port=port, path=path[:512])
        protocol = "HTTPS" if int(port) == 443 else "HTTP"
        try:
            upstream = _open_upstream_connection(host, port, timeout=CONNECT_TIMEOUT)
        except Exception:
            _record_connection(host, port, protocol, "failed")
            raise
        _record_connection(host, port, protocol, "allowed", active_delta=1)
        upstream_key = _register_active_upstream(upstream, host, protocol, client=client)
        _tune_latency_socket(upstream)
        upstream.settimeout(IDLE_TIMEOUT)
        try:
            outgoing = [f"{method} {path} {version}"]
            saw_host = False
            content_length = 0
            for name, value in headers:
                lower = name.lower()
                if lower in {"proxy-connection", "connection"}:
                    continue
                if lower == "host":
                    saw_host = True
                if lower == "content-length":
                    try:
                        content_length = int(value)
                    except Exception:
                        content_length = 0
                outgoing.append(f"{name}: {value}")
            if not saw_host:
                outgoing.append(f"Host: {host}" + (f":{port}" if port != 80 else ""))
            outgoing.append("Connection: close")
            payload = ("\r\n".join(outgoing) + "\r\n\r\n").encode("iso-8859-1")
            upstream.sendall(payload)

            if already:
                upstream.sendall(already)
            remaining = max(0, content_length - len(already))
            while remaining:
                chunk = client.recv(min(BUF, remaining))
                if not chunk:
                    break
                upstream.sendall(chunk)
                remaining -= len(chunk)

            while True:
                chunk = upstream.recv(BUF)
                if not chunk:
                    break
                client.sendall(chunk)
        finally:
            _unregister_active_upstream(upstream_key)
            _record_connection(host, port, protocol, "allowed", active_delta=-1, count=False)
            try:
                upstream.close()
            except Exception:
                pass


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128
    block_on_close = True

    def __init__(self, *args, **kwargs):
        self._client_slots = threading.BoundedSemaphore(MAX_CONCURRENT_CLIENTS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._client_slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
            except Exception:
                pass
            try:
                request.close()
            except Exception:
                pass
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._client_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._client_slots.release()


def main(argv=None):
    global LOG_LEVEL, ALLOW_BROWSER_TELEMETRY, ADBLOCK_ENABLED, ADBLOCK_POLICY
    global TRACKER_BLOCKING, HTTPS_FIRST, PRIVACY_STATS_PATH, _PRIVACY_STATS
    global INSTANCE_TOKEN, _CONNECTION_OVERVIEW_STARTED_AT, _CONNECTION_OVERVIEW_ROWS, _ACTIVE_UPSTREAMS
    # The helper accepts Chromium on loopback, but it never needs to initiate
    # a loopback connection itself. Its public upstream TCP connections remain
    # unaffected by this process-local policy.
    strict_loopback = str(os.environ.get("TEKZITE_STRICT_PYTHON_LOOPBACK", "1")).strip().lower() not in {"0", "false", "no", "off"}
    os.environ["TEKZITE_LOOPBACK_ROLE"] = "network-helper"
    install_loopback_policy(strict_loopback)
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=17890)
    ap.add_argument("--ready-file")
    ap.add_argument("--instance-token", default="")
    ap.add_argument("--log-level", choices=("off", "errors", "full"), default="off")
    ap.add_argument("--allow-browser-telemetry", action="store_true")
    ap.add_argument("--disable-adblock", action="store_true")
    ap.add_argument("--disable-tracker-blocking", action="store_true")
    ap.add_argument("--disable-https-first", action="store_true")
    ap.add_argument("--adblock-policy")
    ap.add_argument("--privacy-stats")
    args = ap.parse_args(argv)
    if args.instance_token and (len(args.instance_token) < 16 or not all(ch in "0123456789abcdefABCDEF" for ch in args.instance_token)):
        raise SystemExit("invalid Tekzite Network instance token")
    LOG_LEVEL = args.log_level
    ALLOW_BROWSER_TELEMETRY = bool(args.allow_browser_telemetry)
    ADBLOCK_ENABLED = not bool(args.disable_adblock)
    TRACKER_BLOCKING = not bool(args.disable_tracker_blocking)
    HTTPS_FIRST = not bool(args.disable_https_first)
    ADBLOCK_POLICY = args.adblock_policy
    PRIVACY_STATS_PATH = args.privacy_stats
    INSTANCE_TOKEN = str(args.instance_token or "")
    _CONNECTION_OVERVIEW_STARTED_AT = time.time()
    _CONNECTION_OVERVIEW_ROWS = {}
    _ACTIVE_UPSTREAMS = {}
    _PRIVACY_STATS = {
        "started_at": time.time(),
        "telemetry_blocked": 0,
        "trackers_blocked": 0,
        "ads_blocked": 0,
        "https_upgrades": 0,
    }
    _write_privacy_stats()
    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("Tekzite Network Engine only binds to loopback")

    with ThreadedTCPServer((args.host, args.port), ProxyHandler) as server:
        actual_host, actual_port = server.server_address[:2]
        if args.ready_file:
            with open(args.ready_file, "w", encoding="utf-8") as f:
                json.dump({"host": actual_host, "port": actual_port, "pid": os.getpid()}, f)
        _log("ready", host=actual_host, port=actual_port, pid=os.getpid())
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
