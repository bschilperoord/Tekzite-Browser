from pathlib import Path
import ast
import socket
import struct

import pytest
import main
from engine import net
import tekzite_network

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')
PROXY = (ROOT / 'tekzite_network.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FEATURES_JS = (ROOT / 'chromium_zoom_extension' / 'features.js').read_text(encoding='utf-8')
CI = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
BUILD = (ROOT / 'build_windows.ps1').read_text(encoding='utf-8')


def test_release_version():
    assert main.BROWSER_VERSION == '10.5.80'


def test_network_helper_kill_requires_instance_identity():
    assert '--instance-token' in NET
    assert 'secrets.token_hex(16)' in NET
    assert 'def _network_helper_pid_matches_state' in NET
    stop = NET[NET.index('def _stop_network_engine_unlocked'):NET.index('atexit.register(_stop_network_engine)')]
    assert '_network_helper_pid_matches_state(candidate, state)' in stop
    assert '_network_helper_pid_matches_state(final_pid, state)' in stop
    assert '--instance-token' in PROXY


def test_chromium_security_services_are_not_disabled():
    assert '--disable-client-side-phishing-detection' not in NET
    assert '--disable-component-update' not in NET


def test_cdp_websocket_rejects_oversized_frame_before_payload_read():
    ws = object.__new__(net._StdlibWebSocket)
    chunks = iter([
        bytes([0x81, 0x7F]),
        struct.pack('!Q', net.MAX_CDP_WEBSOCKET_FRAME_BYTES + 1),
    ])
    ws._read_exact = lambda size: next(chunks)
    ws._struct = struct
    ws._closed = False
    ws.close = lambda: None
    with pytest.raises(ConnectionError, match='safety limit'):
        ws.recv()


def test_page_metadata_and_favicon_fetch_are_bounded():
    assert "slice(0, 1024)" in NET
    assert "slice(0, 32768)" in NET
    assert "slice(0, 8192)" in NET
    assert "MAX_FAVICON_BYTES = 512 * 1024" in NET
    assert "response.read(MAX_FAVICON_BYTES + 1)" in NET
    assert "declared > MAX_FAVICON_BYTES" in NET
    assert "_favicon_target_is_local" in NET


def test_dangerous_download_open_is_blocked_twice():
    assert 'safeDangerStates' in FEATURES_JS
    assert 'item.state !== "complete"' in FEATURES_JS
    assert 'blocked opening a download' in FEATURES_JS
    browser_features = (ROOT / 'browser_features.py').read_text(encoding='utf-8')
    assert "danger not in {'safe', 'accepted', 'deepScannedSafe'}" in browser_features
    assert 'Tekzite Download Protection' in browser_features


def test_public_dns_name_cannot_rebind_to_private(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 443))
    ])
    with pytest.raises(PermissionError):
        tekzite_network._resolved_upstream_endpoints('public.example', 443)


def test_explicit_lan_name_may_resolve_private(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('192.168.1.10', 443))
    ])
    rows = tekzite_network._resolved_upstream_endpoints('router.lan', 443)
    assert rows[0][3][0] == '192.168.1.10'


def test_build_supply_chain_uses_hashes_and_immutable_actions():
    assert '--require-hashes -r requirements-windows.lock' in BUILD
    assert '--require-hashes -r requirements-build-windows.lock' in BUILD
    assert 'actions/checkout@11d5960a326750d5838078e36cf38b85af677262' in CI
    assert 'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065' in CI
    assert 'actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020' in CI
    runtime_lock = (ROOT / 'requirements-windows.lock').read_text(encoding='utf-8')
    build_lock = (ROOT / 'requirements-build-windows.lock').read_text(encoding='utf-8')
    assert '--hash=sha256:' in runtime_lock
    assert '--hash=sha256:' in build_lock


def test_main_preset_import_and_saved_urls_are_bounded():
    assert 'preset_path.stat().st_size > 1024 * 1024' in MAIN
    assert 'unsupported customization preset format' in MAIN
    assert 'prefs["homepage"] = str(prefs.get("homepage") or START_URL).strip()[:32768]' in MAIN
    assert 'payload["search_url_template"]' in MAIN


def test_main_has_no_dynamic_code_execution_or_shell_subprocesses():
    tree = ast.parse(MAIN)
    banned = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        if name in {"eval", "exec", "compile", "__import__"}:
            banned.append((node.lineno, name))
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            full = f"{func.value.id}.{func.attr}"
            if full in {"os.system", "os.popen"}:
                banned.append((node.lineno, full))
            if full.startswith("subprocess."):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value:
                        banned.append((node.lineno, full + " shell=True"))
    assert not banned

