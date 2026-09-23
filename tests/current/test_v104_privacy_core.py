import json
from pathlib import Path

import main
import privacy_core
import tekzite_network
from engine import features, net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
HELPER = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")


def test_v104_defaults_are_privacy_lockdown():
    assert main.BROWSER_VERSION == "10.5.80"
    assert main.DEFAULT_PREFERENCES["privacy_lockdown"] is True
    assert main.DEFAULT_PREFERENCES["tracker_blocking_enabled"] is True
    assert main.DEFAULT_PREFERENCES["strip_tracking_parameters"] is True
    assert main.DEFAULT_PREFERENCES["strip_referrer"] is True
    assert main.DEFAULT_PREFERENCES["https_first"] is True
    assert main.DEFAULT_PREFERENCES["clear_browsing_data_on_exit"] is True
    assert main.DEFAULT_PREFERENCES["restore_tabs"] is False
    assert "startpage.com" in main.DEFAULT_PREFERENCES["search_url_template"]


def test_tracking_parameter_stripping_is_conservative():
    clean, removed = privacy_core.strip_tracking_parameters(
        "https://example.test/page?id=42&utm_source=x&fbclid=abc&keep=yes#frag"
    )
    assert removed == 2
    assert clean == "https://example.test/page?id=42&keep=yes#frag"
    untouched, removed = privacy_core.strip_tracking_parameters("https://example.test/?ref=needed&source=app")
    assert removed == 0
    assert untouched.endswith("?ref=needed&source=app")


def test_https_upgrade_preserves_loopback_but_upgrades_public_http():
    assert privacy_core.upgrade_to_https("http://example.test/a?q=1") == "https://example.test/a?q=1"
    assert privacy_core.upgrade_to_https("http://127.0.0.1:8080/") == "http://127.0.0.1:8080/"
    assert privacy_core.upgrade_to_https("http://localhost:3000/") == "http://localhost:3000/"
    assert privacy_core.upgrade_to_https("http://192.168.25.254/") == "http://192.168.25.254/"


def test_proxy_has_tracker_and_https_first_guards():
    old = tekzite_network.TRACKER_BLOCKING
    try:
        tekzite_network.TRACKER_BLOCKING = True
        assert tekzite_network._is_tracker_host("www.google-analytics.com") is True
        assert tekzite_network._is_tracker_host("example.com") is False
    finally:
        tekzite_network.TRACKER_BLOCKING = old
    assert 'X-Tekzite-Blocked: tracker' in HELPER
    assert '307 Temporary Redirect' in HELPER
    assert '--privacy-stats' in NET


def test_chromium_privacy_boundary_is_explicit():
    for token in (
        '--disable-quic',
        '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
        'DnsOverHttps',
        'BrowsingTopics',
        'SharedStorageAPI',
        'FencedFrames',
        'AttributionReporting',
        '"Sec-GPC": "1"',
        '"DNT": "1"',
    ):
        assert token in NET


def test_bundled_extension_has_privacy_rulesets_and_no_external_messaging():
    manifest = json.loads((ROOT / "chromium_zoom_extension" / "manifest.json").read_text(encoding="utf-8"))
    resources = {row["id"] for row in manifest["declarative_net_request"]["rule_resources"]}
    assert {"ads", "trackers", "privacy_headers"} <= resources
    assert manifest.get("externally_connectable") is None
    assert manifest.get("content_scripts")
    privacy_rules = json.loads((ROOT / "chromium_zoom_extension" / "privacy_headers.json").read_text(encoding="utf-8"))
    assert any(h.get("header") == "referer" and h.get("operation") == "remove"
               for r in privacy_rules for h in r["action"].get("requestHeaders", []))


def test_feature_configuration_carries_privacy_switches():
    features.set_config(True, [], tracker_blocking=False, strip_referrer=False, https_first=False)
    try:
        assert features._CONFIG["tracker_blocking"] is False
        assert features._CONFIG["strip_referrer"] is False
        assert features._CONFIG["https_first"] is False
    finally:
        features.set_config(True, [], tracker_blocking=True, strip_referrer=True, https_first=True)


def test_privacy_shield_is_exposed():
    assert 'Privacy Shield' in MAIN
    assert 'def _show_privacy_shield' in MAIN
    assert 'A website you visit still sees the public IP address' in MAIN


def test_lockdown_uses_temporary_chromium_profile_and_disables_user_extensions():
    assert 'tempfile.mkdtemp(prefix=f"Tekzite-Privacy-{os.getpid()}-")' in MAIN
    assert 'user_extension_paths = [] if self.preferences.get("privacy_lockdown", True)' in MAIN
    assert 'or self.preferences.get("privacy_lockdown", True)' in MAIN

