from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NETWORK = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")

def test_version_is_v69():
    assert 'BROWSER_VERSION = "6.9"' in MAIN

def test_microsoft_global_hard_block_removed():
    assert "MICROSOFT_SUFFIXES" not in NETWORK
    assert "_is_microsoft_host" not in NETWORK
    assert "_deny_microsoft" not in NETWORK
    assert "microsoft-network" not in NETWORK

def test_connect_only_keeps_explicit_telemetry_gate():
    block = NETWORK[NETWORK.index("    def _connect_tunnel"):NETWORK.index("    def _forward_http") ]
    assert "_is_browser_telemetry_host(host)" in block
    assert "microsoft" not in block.lower()

def test_plain_http_only_keeps_explicit_telemetry_gate():
    block = NETWORK[NETWORK.index("    def _forward_http"):]
    assert "_is_browser_telemetry_host(host)" in block
    assert "_deny_microsoft" not in block

def test_telemetry_list_still_contains_microsoft_vendor_endpoints():
    assert '"vortex.data.microsoft.com"' in NETWORK
    assert '".events.data.microsoft.com"' in NETWORK
    assert '".telemetry.microsoft.com"' in NETWORK
