from pathlib import Path

import loopback_policy
import main
from engine import net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
HELPER = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")


def test_release_version_1036():
    assert main.BROWSER_VERSION == "10.5.54"


def test_strict_python_loopback_is_on_by_default():
    assert main.DEFAULT_PREFERENCES["strict_python_loopback"] is True
    assert 'loopback_policy.install(strict_python_loopback)' in MAIN


def test_loopback_policy_allows_only_registered_destination_ports_when_enabled():
    loopback_policy.set_enabled(True)
    loopback_policy.allow_loopback_port(24681, "test")
    try:
        assert loopback_policy.is_loopback_allowed("127.0.0.1", 24681) is True
        assert loopback_policy.is_loopback_allowed("localhost", 24681) is True
        assert loopback_policy.is_loopback_allowed("::1", 24681) is True
        assert loopback_policy.is_loopback_allowed("127.0.0.1", 24682) is False
        assert loopback_policy.is_loopback_allowed("8.8.8.8", 443) is True
    finally:
        loopback_policy.revoke_loopback_port(24681)
        loopback_policy.set_enabled(False)


def test_required_tekzite_ports_are_registered_before_use():
    assert 'allow_loopback_port(port, "Tekzite Network proxy' in NET
    assert 'allow_loopback_port(port, "Chromium DevTools/CDP' in NET
    assert 'revoke_loopback_port(port)' in NET


def test_network_helper_enforces_loopback_egress_policy_too():
    assert 'install_loopback_policy(strict_loopback)' in HELPER
    assert 'unexpected loopback upstream' not in HELPER  # policy is generic, not host-name special casing


def test_local_ports_diagnostics_explains_ephemeral_source_ports():
    assert 'Local Ports & Loopback' in MAIN
    assert 'def _show_local_ports' in FEATURES
    assert 'temporary client/source ports' in FEATURES
    assert 'Recent blocked Python loopback attempts' in FEATURES

