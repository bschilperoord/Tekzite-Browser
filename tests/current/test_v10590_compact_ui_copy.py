from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
FEATURES = (ROOT / "browser_features.py").read_text(encoding="utf-8")


def test_settings_copy_is_compact():
    for text in (
        "Browser settings.",
        "Local suggestions only.",
        "Restore tabs on restart",
        "Quiet mode",
        "Reuse open tab for the same URL",
        "Sleep inactive tabs",
        "Native: GPU • Software: diagnostics",
        "Privacy Core active",
        "Site permissions default: blocked",
        "Windows confirmation required.",
    ):
        assert text in MAIN

    for old in (
        "Uses bookmarks, open tabs, session history and Tekzite history only.",
        "Windows requires your confirmation. Tekzite asks the Windows Shell",
        "Blocks dedicated advertising hosts before Chromium connects to them.",
        "Allows only Tekzite Network proxy + Chromium DevTools/CDP destinations.",
    ):
        assert old not in MAIN


def test_privacy_shield_keeps_state_but_drops_manual_sized_prose():
    block = MAIN[MAIN.index("def _show_privacy_shield"):MAIN.index("def _make_tekzite_default_browser")]
    assert '"TEKZITE PRIVACY"' in block
    assert '"Live privacy status."' in block
    assert '"Sites still see your public IP unless you use an upstream privacy layer."' in block
    assert "Tekzite minimizes browser leakage; it does not claim network anonymity by itself." not in block
    assert "DNS route ................ Your Windows/router resolver" not in block


def test_site_info_and_history_are_compact():
    assert "Cookie values hidden." in FEATURES
    assert "DNT + GPC on • third-party cookies restricted • site permissions blocked" in FEATURES
    assert "Search history. Exit clearing removes it." in FEATURES
    assert "Notifications, location, camera, microphone and sensors: blocked by Tekzite defaults" not in FEATURES


def test_network_diagnostics_keep_data_but_remove_text_walls():
    assert "Live Tekzite + Chromium sockets • UDP peers: Kernel-Network ETW • hostnames: Tekzite Network • attribution: RAM-only CDP." in FEATURES
    assert "Strong / likely / probable = decreasing attribution confidence; reused = existing Chromium connection." in FEATURES
    assert "Hostnames: Tekzite Network • attribution: RAM-only CDP • script source: on demand • PTR may query DNS." in FEATURES
    assert "Strong opener = exact requested hostname + socket-open timing" not in FEATURES
    assert "Exact site hostnames come from Tekzite Network. Purpose/resource/script attribution" not in FEATURES


def test_source_inspector_privacy_copy_is_short():
    for text in (
        "Source analyzed in memory; external maps are not fetched.",
        "No JavaScript caller was captured.",
        "Full source is memory-only and discarded after analysis.",
        "CDP caller coordinates are authoritative.",
        "Analysis complete; source discarded.",
    ):
        assert text in FEATURES
