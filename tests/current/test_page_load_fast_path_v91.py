from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
PROXY = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")


def test_hot_navigation_skips_cold_readiness_gate():
    block = NET[NET.index("def open_embedded_chromium"):NET.index("def record_embedded_native_recovery")]
    assert "hot_native_navigation = bool(" in block
    assert "wait_for_first_frame=bool((not attach_native) and (not hot_native_navigation))" in block
    assert "hot_navigation_reused_native_surface" in block
    assert "return session" in block


def test_dns_prefetch_not_globally_disabled():
    launch = NET[NET.index("command = [", NET.index("def _start_persistent_chromium_session")):NET.index("effective_flags =", NET.index("def _start_persistent_chromium_session"))]
    assert "--dns-prefetch-disable" not in launch
    assert "DnsOverHttps" in launch


def test_proxy_uses_low_latency_tcp_and_larger_backlog():
    assert "TCP_NODELAY" in PROXY
    assert "_tune_latency_socket(client)" in PROXY
    assert "_tune_latency_socket(upstream)" in PROXY
    assert "request_queue_size = 128" in PROXY
