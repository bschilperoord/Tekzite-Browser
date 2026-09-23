from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")

def test_version_v93():
    assert 'BROWSER_VERSION = "10.5.73"' in MAIN

def test_frame_gate_reuses_persistent_input_lane():
    block = NET[NET.index("def _wait_for_attached_first_frame"):NET.index("def navigate_embedded_chromium")]
    assert 'purpose="input"' in block
    assert '_persistent_page_cdp_call' in block
    assert '_open_devtools_websocket' not in block
    assert 'Page.enable' not in block
    assert 'Runtime.enable' not in block

def test_latency_lanes_skip_network_domain_setup():
    block = NET[NET.index("def _get_persistent_page_cdp_channel"):NET.index("def _persistent_page_cdp_call")]
    assert 'latency_only_purposes = {"input", "scroll", "hover", "cursor"}' in block
    assert 'network_setup_skipped_for_latency' in block

def test_frame_proof_is_reused_for_input_ready():
    block = NET[NET.index("def _wait_for_embedded_chromium_input_ready"):NET.index("def _focus_embedded_chromium_startup_input")]
    assert 'input_ready_reused_frame_proof' in block
    assert 'attached-semantic-geometry' in block

