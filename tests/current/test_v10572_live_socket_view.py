from pathlib import Path

import engine.net as net
import main
import tekzite_network as proxy

ROOT = Path(__file__).resolve().parents[2]
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
PROXY = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.80"  # sync_version updates this pin


def test_proxy_exposes_exact_active_upstream_hostname_without_content(monkeypatch):
    class Sock:
        def getsockname(self):
            return ("192.168.25.100", 53123)
        def getpeername(self):
            return ("104.18.32.7", 443)

    monkeypatch.setattr(proxy, "_ACTIVE_UPSTREAMS", {})
    key = proxy._register_active_upstream(Sock(), "Guru3D.com.", "HTTPS")
    data = proxy._connection_overview_payload()
    assert data["active_upstreams"] == [{
        "host": "guru3d.com",
        "protocol": "HTTPS",
        "local_address": "192.168.25.100",
        "local_port": 53123,
        "remote_address": "104.18.32.7",
        "remote_port": 443,
        "opened_at": data["active_upstreams"][0]["opened_at"],
    }]
    assert "url" not in str(data).lower()
    assert "header" not in str(data).lower()
    proxy._unregister_active_upstream(key)
    assert proxy._connection_overview_payload()["active_upstreams"] == []


def test_live_socket_snapshot_includes_all_owned_tcp_udp_and_marks_direct(monkeypatch):
    class Proc:
        def __init__(self, pid):
            self.pid = pid
        def poll(self):
            return None

    processes = {
        100: {"pid": 100, "ppid": 1, "exe": "TekziteBrowser.exe"},
        200: {"pid": 200, "ppid": 100, "exe": "TekziteNetwork.exe"},
        300: {"pid": 300, "ppid": 100, "exe": "chromium.exe"},
        301: {"pid": 301, "ppid": 300, "exe": "chromium.exe"},
        999: {"pid": 999, "ppid": 1, "exe": "other.exe"},
    }
    sockets = [
        {"pid": 300, "protocol": "TCP", "family": "IPv4", "local_address": "127.0.0.1", "local_port": 50000,
         "remote_address": "127.0.0.1", "remote_port": 17890, "state": "ESTABLISHED"},
        {"pid": 200, "protocol": "TCP", "family": "IPv4", "local_address": "192.168.25.100", "local_port": 53123,
         "remote_address": "104.18.32.7", "remote_port": 443, "state": "ESTABLISHED"},
        {"pid": 301, "protocol": "TCP", "family": "IPv4", "local_address": "192.168.25.100", "local_port": 53124,
         "remote_address": "1.1.1.1", "remote_port": 443, "state": "ESTABLISHED"},
        {"pid": 100, "protocol": "TCP", "family": "IPv4", "local_address": "127.0.0.1", "local_port": 40000,
         "remote_address": "0.0.0.0", "remote_port": 0, "state": "LISTEN"},
        {"pid": 300, "protocol": "UDP", "family": "IPv6", "local_address": "::", "local_port": 5353,
         "remote_address": "", "remote_port": 0, "state": "ENDPOINT"},
        {"pid": 999, "protocol": "TCP", "family": "IPv4", "local_address": "10.0.0.5", "local_port": 1,
         "remote_address": "8.8.8.8", "remote_port": 53, "state": "ESTABLISHED"},
    ]

    monkeypatch.setattr(net.os, "name", "nt")
    monkeypatch.setattr(net.os, "getpid", lambda: 100)
    monkeypatch.setattr(net, "_windows_process_snapshot", lambda: processes)
    monkeypatch.setattr(net, "_windows_socket_rows", lambda: sockets)
    monkeypatch.setattr(net, "_NETWORK_ENGINE", {"process": Proc(200), "port": 17890})
    monkeypatch.setattr(net, "_EDGE_SESSION", {"process": Proc(300), "port": 9222})
    monkeypatch.setattr(net, "ensure_udp_peer_monitor", lambda _owned: {"status": "running", "reason": "", "peers": []})
    monkeypatch.setattr(net, "connection_overview", lambda **_kwargs: {
        "active_upstreams": [{
            "host": "guru3d.com", "protocol": "HTTPS",
            "local_address": "192.168.25.100", "local_port": 53123,
            "remote_address": "104.18.32.7", "remote_port": 443,
        }]
    })

    snapshot = net.live_socket_snapshot()
    assert snapshot["supported"] is True
    rows = snapshot["sockets"]
    assert len(rows) == 5
    assert all(row["pid"] != 999 for row in rows)

    upstream = next(row for row in rows if row["pid"] == 200)
    assert upstream["hostname"] == "guru3d.com"
    assert upstream["path"] == "Tekzite Network upstream"

    proxy_link = next(row for row in rows if row["pid"] == 300 and row["protocol"] == "TCP")
    assert proxy_link["hostname"] == "Tekzite Network"
    assert proxy_link["path"] == "Via Tekzite Network"

    direct = next(row for row in rows if row["pid"] == 301)
    assert direct["path"] == "Direct external"

    udp = next(row for row in rows if row["protocol"] == "UDP")
    assert udp["path"] == "UDP endpoint"
    assert udp["remote_address"] == ""


def test_windows_socket_monitor_uses_builtin_owner_tables_not_psutil():
    assert "GetExtendedTcpTable" in NET
    assert "GetExtendedUdpTable" in NET
    assert "Toolhelp32Snapshot" in NET
    assert "psutil" not in NET


def test_live_socket_ui_has_hostnames_paths_and_fast_updates():
    assert "def _show_network_connections" in FEATURES
    assert "Live Socket View" in FEATURES
    assert "features.net.live_socket_snapshot(include_proxy_names=True, extra_pids=extra_pids)" in FEATURES
    assert "Resolve hostnames (PTR)" in FEATURES
    assert "Direct external" in FEATURES
    assert "250 ms snapshots" in FEATURES
    assert "UDP remote peers are correlated from live Kernel-Network ETW events" in FEATURES
