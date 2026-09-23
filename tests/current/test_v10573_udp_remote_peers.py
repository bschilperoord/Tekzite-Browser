from pathlib import Path
import socket
import struct

import main
import engine.net as net
from engine import udp_peer_etw

ROOT = Path(__file__).resolve().parents[2]
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")
ETW = (ROOT / "engine" / "udp_peer_etw.py").read_text(encoding="utf-8")


def _ipv4_payload(pid, size, daddr, saddr, dport, sport):
    return (
        struct.pack("<II", pid, size)
        + socket.inet_pton(socket.AF_INET, daddr)
        + socket.inet_pton(socket.AF_INET, saddr)
        + struct.pack("!HH", dport, sport)
        + struct.pack("<II", 7, 9)
    )


def _ipv6_payload(pid, size, daddr, saddr, dport, sport):
    return (
        struct.pack("<II", pid, size)
        + socket.inet_pton(socket.AF_INET6, daddr)
        + socket.inet_pton(socket.AF_INET6, saddr)
        + struct.pack("!HH", dport, sport)
        + struct.pack("<II", 7, 9)
    )


def test_release_version_is_current():
    assert main.BROWSER_VERSION == "10.5.73"  # sync_version updates this pin


def test_kernel_network_udp_ipv4_send_and_receive_map_remote_peer_correctly():
    payload = _ipv4_payload(300, 1234, "1.1.1.1", "192.168.25.100", 443, 53000)
    sent = udp_peer_etw._parse_udp_kernel_network_event(42, payload)
    assert sent == {
        "pid": 300, "family": "IPv4",
        "local_address": "192.168.25.100", "local_port": 53000,
        "remote_address": "1.1.1.1", "remote_port": 443,
        "direction": "send", "size": 1234,
    }

    received_payload = _ipv4_payload(300, 500, "192.168.25.100", "8.8.8.8", 53000, 3478)
    received = udp_peer_etw._parse_udp_kernel_network_event(43, received_payload)
    assert received["local_address"] == "192.168.25.100"
    assert received["local_port"] == 53000
    assert received["remote_address"] == "8.8.8.8"
    assert received["remote_port"] == 3478
    assert received["direction"] == "receive"


def test_kernel_network_udp_ipv6_peer_decoder():
    payload = _ipv6_payload(301, 700, "2606:4700:4700::1111", "2001:db8::25", 443, 54000)
    event = udp_peer_etw._parse_udp_kernel_network_event(58, payload)
    assert event["family"] == "IPv6"
    assert event["local_address"] == "2001:db8::25"
    assert event["local_port"] == 54000
    assert event["remote_address"] == "2606:4700:4700::1111"
    assert event["remote_port"] == 443


def test_udp_peer_ledger_keeps_multiple_remote_peers_and_traffic_counters():
    ledger = udp_peer_etw._PeerLedger(max_age=30, max_rows=16)
    ledger.set_pids({300})
    base = {
        "pid": 300, "family": "IPv4", "local_address": "192.168.25.100",
        "local_port": 53000, "direction": "send", "size": 100,
    }
    assert ledger.add({**base, "remote_address": "1.1.1.1", "remote_port": 443}, now=100.0)
    assert ledger.add({**base, "remote_address": "8.8.8.8", "remote_port": 3478, "size": 200}, now=101.0)
    assert ledger.add({**base, "remote_address": "1.1.1.1", "remote_port": 443, "direction": "receive", "size": 50}, now=102.0)
    rows = ledger.snapshot(now=102.0)
    assert len(rows) == 2
    cf = next(row for row in rows if row["remote_address"] == "1.1.1.1")
    assert cf["tx_packets"] == 1 and cf["tx_bytes"] == 100
    assert cf["rx_packets"] == 1 and cf["rx_bytes"] == 50


def test_live_socket_snapshot_expands_udp_endpoint_into_remote_peer_rows(monkeypatch):
    class Proc:
        def __init__(self, pid): self.pid = pid
        def poll(self): return None

    processes = {
        100: {"pid": 100, "ppid": 1, "exe": "TekziteBrowser.exe"},
        300: {"pid": 300, "ppid": 100, "exe": "chromium.exe"},
    }
    sockets = [{
        "pid": 300, "protocol": "UDP", "family": "IPv4",
        "local_address": "0.0.0.0", "local_port": 53000,
        "remote_address": "", "remote_port": 0, "state": "ENDPOINT",
    }]
    peers = [
        {"pid": 300, "family": "IPv4", "local_address": "192.168.25.100", "local_port": 53000,
         "remote_address": "1.1.1.1", "remote_port": 443, "last_seen": 100.0, "first_seen": 99.0,
         "tx_packets": 3, "rx_packets": 2, "tx_bytes": 1200, "rx_bytes": 900},
        {"pid": 300, "family": "IPv4", "local_address": "192.168.25.100", "local_port": 53000,
         "remote_address": "8.8.8.8", "remote_port": 3478, "last_seen": 101.0, "first_seen": 100.0,
         "tx_packets": 1, "rx_packets": 1, "tx_bytes": 80, "rx_bytes": 90},
    ]

    monkeypatch.setattr(net.os, "name", "nt")
    monkeypatch.setattr(net.os, "getpid", lambda: 100)
    monkeypatch.setattr(net, "_windows_process_snapshot", lambda: processes)
    monkeypatch.setattr(net, "_windows_socket_rows", lambda: sockets)
    monkeypatch.setattr(net, "_NETWORK_ENGINE", None)
    monkeypatch.setattr(net, "_EDGE_SESSION", {"process": Proc(300), "port": 9222})
    monkeypatch.setattr(net, "connection_overview", lambda **_kwargs: {})
    monkeypatch.setattr(net, "ensure_udp_peer_monitor", lambda _owned: {
        "status": "running", "reason": "", "peers": peers,
    })

    snapshot = net.live_socket_snapshot()
    rows = snapshot["sockets"]
    assert len(rows) == 2
    assert {row["remote_address"] for row in rows} == {"1.1.1.1", "8.8.8.8"}
    assert all(row["state"] == "PEER" for row in rows)
    assert all(row["path"] == "Direct UDP external" for row in rows)
    assert all(row["local_address"] == "192.168.25.100" for row in rows)
    assert snapshot["udp_peer_monitor"]["status"] == "running"
    cloudflare = next(row for row in rows if row["remote_address"] == "1.1.1.1")
    assert cloudflare["tx_packets"] == 3 and cloudflare["rx_packets"] == 2


def test_udp_peer_etw_is_native_ram_only_and_ui_surfaces_peer_metadata():
    assert udp_peer_etw.KERNEL_NETWORK_PROVIDER_GUID.lower() in ETW.lower()
    for api in ("StartTraceW", "EnableTraceEx2", "OpenTraceW", "ProcessTrace", "ControlTraceW"):
        assert api in ETW
    assert "UDP_PEER_MAX_AGE = 30.0" in ETW
    assert "payload is captured or stored" in ETW.lower()
    assert "UDP remote peers are correlated from live Kernel-Network ETW events" in FEATURES
    assert "Traffic" in FEATURES and "Seen" in FEATURES
    assert "Direct UDP external" in (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
    assert "stop_live_socket_peer_monitor" in FEATURES
