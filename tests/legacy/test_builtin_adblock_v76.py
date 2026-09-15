import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_network():
    spec = importlib.util.spec_from_file_location("tekzite_network_v76", ROOT / "tekzite_network.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_and_preference_exist():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'BROWSER_VERSION = "7.6"' in main
    assert '"adblock_enabled": True' in main
    assert 'Block ads with Tekzite Adblock' in main


def test_known_ad_hosts_are_blocked():
    n = load_network()
    n.ADBLOCK_ENABLED = True
    for host in [
        "pagead2.googlesyndication.com",
        "securepubads.g.doubleclick.net",
        "ib.adnxs.com",
        "cdn.taboola.com",
        "widgets.outbrain.com",
        "static.criteo.net",
        "ads.pubmatic.com",
    ]:
        assert n._is_ad_host(host), host


def test_normal_sites_are_not_blocked_as_ads():
    n = load_network()
    n.ADBLOCK_ENABLED = True
    for host in [
        "youtube.com",
        "www.youtube.com",
        "google.com",
        "accounts.google.com",
        "microsoft.com",
        "login.microsoftonline.com",
        "www.startpage.com",
    ]:
        assert not n._is_ad_host(host), host


def test_adblock_can_be_disabled_without_disabling_telemetry_filter():
    n = load_network()
    n.ADBLOCK_ENABLED = False
    assert not n._is_ad_host("securepubads.g.doubleclick.net")
    n.ALLOW_BROWSER_TELEMETRY = False
    assert n._is_browser_telemetry_host("vortex.data.microsoft.com")


def test_proxy_checks_ads_for_connect_and_http():
    src = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")
    assert 'if _is_ad_host(host):\n            _deny_ad(client, host, "CONNECT")' in src
    assert 'if _is_ad_host(host):\n            _deny_ad(client, host, method.upper())' in src


def test_network_engine_receives_toggle():
    src = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
    assert 'TEKZITE_ADBLOCK_ENABLED' in src
    assert 'command.append("--disable-adblock")' in src
