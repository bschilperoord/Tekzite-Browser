from pathlib import Path
import os
import tempfile

import pytest

import main
import tekzite_network
from engine import net

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
BUILD = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_release_version():
    assert main.BROWSER_VERSION == "10.5.32"


def test_stale_pid_requires_profile_chromium_verification():
    block = NET[NET.index("def _terminate_stale_profile_owner"):NET.index("def _profile_chromium_pids")]
    assert "pid in set(_profile_chromium_pids(profile_dir))" in block
    assert block.index("_profile_chromium_pids") < block.index('["taskkill", "/PID"')


def test_cdp_uses_chromium_ephemeral_port_and_no_wildcard_origin():
    assert '"--remote-debugging-port=0"' in NET
    assert "--remote-allow-origins=*" not in NET
    assert "DevToolsActivePort" in NET
    assert "_validate_devtools_ws_url" in NET


def test_devtools_ws_validation_rejects_non_loopback_and_wrong_port():
    assert net._validate_devtools_ws_url("ws://127.0.0.1:4567/devtools/browser/test", 4567)
    with pytest.raises(RuntimeError):
        net._validate_devtools_ws_url("ws://example.com:4567/devtools/browser/test", 4567)
    with pytest.raises(RuntimeError):
        net._validate_devtools_ws_url("ws://127.0.0.1:4568/devtools/browser/test", 4567)
    with pytest.raises(RuntimeError):
        net._validate_devtools_ws_url("wss://127.0.0.1:4567/devtools/browser/test", 4567)


def test_devtools_active_port_parser_is_strict():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "DevToolsActivePort"
        p.write_text("4567\n/devtools/browser/abc\n", encoding="utf-8")
        assert net._read_devtools_active_port(td) == (4567, "/devtools/browser/abc")
        p.write_text("4567\n/not-devtools/abc\n", encoding="utf-8")
        assert net._read_devtools_active_port(td) is None


def test_private_profile_scavenger_protects_live_and_removes_dead():
    with tempfile.TemporaryDirectory() as td:
        live = Path(td) / f"Tekzite-Private-{os.getpid()}-live"
        dead = Path(td) / "Tekzite-Private-999999-dead"
        live.mkdir()
        dead.mkdir()
        result = net.cleanup_abandoned_temporary_profiles(td, minimum_orphan_age=0)
        assert live.exists()
        assert not dead.exists()
        assert str(live) in result["skipped_live"]


def test_favicon_decode_has_format_and_pixel_limits():
    block = MAIN[MAIN.index("def _decode_favicon_photo"):MAIN.index("def _poll_one_tab_state")]
    assert 'len(raw) > 524288' in block
    assert '{"PNG", "ICO", "JPEG", "GIF", "WEBP"}' in block
    assert "width > 2048 or height > 2048" in block
    assert "width * height > 4_194_304" in block
    assert 'warnings.simplefilter("error", Image.DecompressionBombWarning)' in block


def test_proxy_limits_headers_and_concurrency():
    assert tekzite_network.MAX_HEADER_BYTES == 64 * 1024
    assert tekzite_network.MAX_CONCURRENT_CLIENTS == 64
    with pytest.raises(ValueError):
        tekzite_network._parse_headers(b"GET / HTTP/1.1\r\n bad: folded\r\n\r\n")
    with pytest.raises(ValueError):
        tekzite_network._split_host_port("bad host:80", 80)


def test_dependency_and_build_hardening_present():
    assert (ROOT / "requirements.txt").read_text().strip() == "Pillow==12.3.0"
    assert (ROOT / "requirements-build.txt").read_text().strip() == "pyinstaller==6.22.3"
    dev = (ROOT / "requirements-dev.txt").read_text()
    assert "bandit==1.9.4" in dev
    assert "pip-audit==2.10.1" in dev
    assert "TEKZITE_SIGN_CERT_SHA1" in BUILD
    assert "signtool sign" in BUILD


def test_security_policy_matches_real_extension_boundary():
    assert "declarativeNetRequest" in SECURITY
    assert "http://*/*" in SECURITY and "https://*/*" in SECURITY
    assert "--remote-debugging-port=0" in SECURITY
    assert "--remote-allow-origins=*` is not used" in SECURITY
