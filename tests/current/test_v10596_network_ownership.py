from pathlib import Path

import engine.net as net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


class Proc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def test_network_connections_ownership_rejects_foreign_descendants(monkeypatch):
    processes = {
        100: {"pid": 100, "ppid": 1, "exe": "TekziteBrowser.exe"},
        200: {"pid": 200, "ppid": 100, "exe": "tekzite-network.exe"},
        201: {"pid": 201, "ppid": 200, "exe": "powershell.exe"},
        300: {"pid": 300, "ppid": 100, "exe": "chromium.exe"},
        301: {"pid": 301, "ppid": 300, "exe": "chrome.exe"},
        302: {"pid": 302, "ppid": 300, "exe": "notepad.exe"},
        400: {"pid": 400, "ppid": 100, "exe": "Discord.exe"},
        500: {"pid": 500, "ppid": 1, "exe": "chrome.exe"},
        501: {"pid": 501, "ppid": 500, "exe": "calc.exe"},
        600: {"pid": 600, "ppid": 1, "exe": "Spotify.exe"},
    }

    monkeypatch.setattr(net.os, "getpid", lambda: 100)
    monkeypatch.setattr(net, "_NETWORK_ENGINE", {"process": Proc(200)})
    monkeypatch.setattr(net, "_CHROMIUM_SESSION", {"process": Proc(300)})

    owned, _ = net._windows_owned_processes(processes, extra_roots=[500, 600])

    assert owned == {100, 200, 300, 301, 500}
    assert 201 not in owned
    assert 302 not in owned
    assert 400 not in owned
    assert 501 not in owned
    assert 600 not in owned


def test_most_visited_card_title_has_metadata_spacing():
    assert "card_height = 134" in MAIN
    assert "x1 + 22, y1 + 80, text=host_display" in MAIN
    assert "x1 + 22, y1 + 106," in MAIN
