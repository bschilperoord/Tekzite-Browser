from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_input_channel_is_prewarmed_before_native_open_returns():
    assert "def warm_embedded_chromium_input_channel" in NET
    assert 'purpose="input"' in NET
    open_block = NET[NET.index("def open_embedded_chromium"):NET.index("def record_embedded_native_recovery")]
    assert 'frame gate itself opens and retains the critical input lane' in open_block


def test_release_version_is_87():
    assert 'BROWSER_VERSION = "10.5.47"' in MAIN

