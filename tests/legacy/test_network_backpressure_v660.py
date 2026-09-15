from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NET = (ROOT / 'tekzite_network.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_version_v660():
    assert 'BROWSER_VERSION = "6.6"' in MAIN


def test_relay_uses_buffered_nonblocking_writes():
    assert 'pending = {a: bytearray(), b: bytearray()}' in NET
    assert 'ready_r, ready_w, exceptional = select.select' in NET
    assert 'sent = dst.send(buf)' in NET


def test_relay_does_not_use_sendall_in_connect_loop():
    relay = NET.split('def _relay(a: socket.socket, b: socket.socket):', 1)[1].split('\n\nclass ProxyHandler', 1)[0]
    assert '.sendall(' not in relay


def test_relay_has_backpressure_limit_and_half_close():
    assert 'max_pending = 4 * 1024 * 1024' in NET
    assert 'dst.shutdown(socket.SHUT_WR)' in NET
