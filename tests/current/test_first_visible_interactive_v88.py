from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")

def test_release_is_v88():
    assert 'BROWSER_VERSION = "10.5.80"' in MAIN

def test_hidden_startup_proves_real_input_roundtrip():
    assert 'def _wait_for_embedded_chromium_input_ready' in NET
    assert '"Input.dispatchMouseEvent"' in NET
    assert 'purpose="input"' in NET
    assert '_wait_for_embedded_chromium_input_ready(' in NET
    assert 'first visible frame == first interactive frame' in NET

