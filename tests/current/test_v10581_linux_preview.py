from __future__ import annotations

import os
from pathlib import Path

import main
from engine import net


ROOT = Path(__file__).resolve().parents[2]


def test_linux_state_root_uses_xdg(monkeypatch, tmp_path):
    if os.name == "nt":
        return
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert main._state_root_for_profile("Default") == tmp_path / "tekzite-browser"
    assert main._state_root_for_profile("Studio") == tmp_path / "tekzite-browser" / "profiles" / "Studio"


def test_linux_proc_address_and_endpoint_decoding():
    assert net._linux_proc_endpoint("0100007F:1F90", "IPv4") == ("127.0.0.1", 8080)
    assert net._linux_proc_address("00000000000000000000000001000000", "IPv6") == "::1"


def test_linux_owned_processes_follows_descendant_closure():
    root = 41000
    processes = {
        root: {"pid": root, "ppid": 1, "exe": "TekziteBrowser"},
        root + 1: {"pid": root + 1, "ppid": root, "exe": "chromium"},
        root + 2: {"pid": root + 2, "ppid": root + 1, "exe": "chromium"},
        999: {"pid": 999, "ppid": 1, "exe": "unrelated"},
    }
    owned, _ = net._linux_owned_processes(processes, extra_roots=[root])
    assert root in owned
    assert root + 1 in owned
    assert root + 2 in owned
    assert 999 not in owned


def test_linux_proc_socket_row_maps_inode_to_owned_pid(tmp_path):
    if not os.sys.platform.startswith("linux"):
        return
    pid = 42420
    (tmp_path / "net").mkdir()
    for name in ("tcp6", "udp", "udp6"):
        (tmp_path / "net" / name).write_text("  sl  local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n")
    (tmp_path / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
        "   0: 0100007F:C350 0100007F:01BB 01 00000000:00000000 00:00000000 00000000 1000 0 987654\n"
    )
    fd = tmp_path / str(pid) / "fd"
    fd.mkdir(parents=True)
    (fd / "7").symlink_to("socket:[987654]")
    rows = net._linux_socket_rows({pid}, proc_root=str(tmp_path))
    assert rows == [{
        "pid": pid,
        "protocol": "TCP",
        "family": "IPv4",
        "local_address": "127.0.0.1",
        "local_port": 50000,
        "remote_address": "127.0.0.1",
        "remote_port": 443,
        "state": "ESTABLISHED",
    }]


def test_linux_launch_uses_headless_software_backend_source_contract():
    source = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
    assert 'command.extend(["--headless=new", "--disable-gpu-vsync"])' in source
    assert 'if callable(geteuid) and int(geteuid()) == 0:' in source
    assert 'command.append("--no-sandbox")' in source
    assert 'start_new_session=(os.name != "nt")' in source
    assert 'blank_document_allowed = target_url in {"about:blank", "chrome://newtab/"}' in source


def test_linux_browser_shell_forces_software_and_uses_tekzite_frameless_chrome():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'self.root.overrideredirect(True)' in source
    assert 'self.root.overrideredirect(os.name == "nt")' not in source
    assert 'if os.name != "nt":\n            return True' in source
    assert 'self.edge_host.bind("<Button-4>", self._on_chromium_surface_linux_wheel)' in source
    assert 'self._executor.submit(self._apply_chromium_zoom_to_all_tabs)' in source
