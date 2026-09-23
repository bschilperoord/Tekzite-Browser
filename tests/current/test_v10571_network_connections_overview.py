import json
from pathlib import Path

import engine.net as net
import main
import tekzite_network as proxy

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
PROXY = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.73"  # sync_version updates this pin


def test_proxy_connection_ledger_is_ram_only_and_tracks_lifecycle(monkeypatch):
    monkeypatch.setattr(proxy, "_CONNECTION_OVERVIEW_ROWS", {})
    monkeypatch.setattr(proxy, "_CONNECTION_OVERVIEW_STARTED_AT", 123.0)

    proxy._record_connection("Example.COM.", 443, "https", "allowed", active_delta=1)
    proxy._record_connection("example.com", 443, "HTTPS", "allowed", active_delta=-1, count=False)
    proxy._record_connection("ads.example", 443, "HTTPS", "blocked-ad")

    data = proxy._connection_overview_payload()
    rows = data["connections"]
    assert any(row["host"] == "example.com" and row["status"] == "allowed" and row["count"] == 1 and row["active"] == 0 for row in rows)
    assert any(row["host"] == "ads.example" and row["status"] == "blocked-ad" for row in rows)
    encoded = json.dumps(data)
    assert "https://" not in encoded
    assert "?" not in encoded
    assert "header" not in encoded.lower()


def test_internal_overview_endpoint_requires_random_instance_token(monkeypatch):
    class Client:
        def __init__(self):
            self.data = b""
        def sendall(self, value):
            self.data += value

    monkeypatch.setattr(proxy, "INSTANCE_TOKEN", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(proxy, "_CONNECTION_OVERVIEW_ROWS", {})
    proxy._record_connection("cdn.example.com", 443, "HTTPS", "allowed")

    denied = Client()
    assert proxy._serve_internal_connection_overview(
        denied, "GET", "http://tekzite.internal/__connections",
        [("Host", "tekzite.internal"), ("X-Tekzite-Instance-Token", "wrong")],
    )
    assert denied.data.startswith(b"HTTP/1.1 404")

    allowed = Client()
    assert proxy._serve_internal_connection_overview(
        allowed, "GET", "http://tekzite.internal/__connections",
        [("Host", "tekzite.internal"), ("X-Tekzite-Instance-Token", "0123456789abcdef0123456789abcdef")],
    )
    assert allowed.data.startswith(b"HTTP/1.1 200")
    body = allowed.data.split(b"\r\n\r\n", 1)[1]
    assert json.loads(body)["connections"][0]["host"] == "cdn.example.com"


def test_engine_reads_and_sanitizes_loopback_overview(monkeypatch):
    payload = json.dumps({
        "started_at": 10,
        "updated_at": 11,
        "connections": [{
            "host": "cdn.example.com", "port": 443, "protocol": "HTTPS",
            "status": "allowed", "count": 3, "active": 1,
            "first_seen": 10.1, "last_seen": 10.9,
            "url": "https://cdn.example.com/secret?token=nope",
        }],
    }).encode("utf-8")
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + payload

    class Proc:
        def poll(self):
            return None

    class FakeSocket:
        def __init__(self):
            self.sent = b""
            self.raw = raw
            self.done = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def settimeout(self, _timeout):
            pass
        def sendall(self, value):
            self.sent += value
        def recv(self, _size):
            if self.done:
                return b""
            self.done = True
            return self.raw

    fake = FakeSocket()
    monkeypatch.setattr(net, "_NETWORK_ENGINE", {
        "process": Proc(), "host": "127.0.0.1", "port": 17890,
        "instance_token": "0123456789abcdef0123456789abcdef",
    })
    monkeypatch.setattr(net.socket, "create_connection", lambda *_args, **_kwargs: fake)
    snapshot = net.connection_overview(start=False)
    assert snapshot["connections"] == [{
        "host": "cdn.example.com", "port": 443, "protocol": "HTTPS",
        "status": "allowed", "count": 3, "active": 1,
        "first_seen": 10.1, "last_seen": 10.9,
    }]
    assert b"X-Tekzite-Instance-Token: 0123456789abcdef0123456789abcdef" in fake.sent


def test_overview_never_creates_a_persistent_connection_history_file():
    assert "CONNECTION_OVERVIEW_PATH" not in PROXY
    assert "--connection-overview" not in NET
    assert "tekzite.internal" in PROXY and "/__connections" in PROXY
    assert "tekzite.internal/__connections" in NET
    assert "INSTANCE_TOKEN" in PROXY


def test_browser_exposes_live_network_connections_dialog():
    assert '("Network Connections", self._show_network_connections, "")' in MAIN
    assert "def _show_network_connections" in FEATURES
    assert "Live Socket View" in FEATURES
    assert "features.net.live_socket_snapshot(include_proxy_names=True, extra_pids=extra_pids)" in FEATURES
    assert "Resolve hostnames (PTR)" in FEATURES
    assert "Direct external" in FEATURES


def test_proxy_tracks_allowed_blocked_upgrade_and_failed_outcomes():
    for status in (
        '"allowed"', '"blocked-ad"', '"blocked-tracker"',
        '"blocked-telemetry"', '"https-upgraded"', '"failed"',
    ):
        assert status in PROXY
