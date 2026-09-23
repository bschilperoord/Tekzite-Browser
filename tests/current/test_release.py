from pathlib import Path
import json

import main
import tekzite_network

ROOT = Path(__file__).resolve().parents[2]
NET = (ROOT / "engine" / "net.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_current_version():
    assert main.BROWSER_VERSION == "10.5.73"


def test_zoom_normalization():
    assert main._normalized_zoom_percent("150%") == 150
    assert main._normalized_zoom_percent(10) == 50
    assert main._normalized_zoom_percent(999) == 300


def test_chromium_only_runtime_files():
    removed = {"html_parser.py", "layout.py", "painter.py", "tinyjs.py"}
    assert not any((ROOT / "engine" / name).exists() for name in removed)
    assert main.DEFAULT_PREFERENCES["renderer"] == "chromium"


def test_native_dwm_presentation_is_present():
    assert "DwmRegisterThumbnail" in NET
    assert "DwmUpdateThumbnailProperties" in NET
    assert 'native_embed_mode' in NET


def test_fast_target_activation_path_is_present():
    assert "Target.activateTarget" in NET
    assert "tab_switch_fast_path_count" in MAIN or "tab_switch_fast_path_count" in NET


def test_native_zoom_bridge_is_minimally_privileged():
    manifest = json.loads((ROOT / "chromium_zoom_extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert set(manifest.get("permissions", [])) <= {"tabs", "storage", "downloads", "downloads.open", "declarativeNetRequest"}
    assert set(manifest.get("host_permissions", [])) == {"http://*/*", "https://*/*"}
    assert manifest.get("content_scripts")
    assert not manifest.get("externally_connectable")
    bridge = (ROOT / "chromium_zoom_extension" / "background.js").read_text(encoding="utf-8")
    assert "chrome.tabs.setZoom" in bridge
    assert 'mode: "automatic"' in bridge


def test_input_mapping_accounts_for_native_zoom():
    assert "get_embedded_chromium_input_zoom_factor" in MAIN
    assert "dwm_input_zoom_factor" in NET


def test_builtin_adblock_blocks_ad_hosts_but_not_first_party():
    assert tekzite_network._is_ad_host("securepubads.g.doubleclick.net")
    assert tekzite_network._is_ad_host("ads.example.adnxs.com")
    assert not tekzite_network._is_ad_host("youtube.com")
    assert not tekzite_network._is_ad_host("www.startpage.com")
    assert not tekzite_network._is_ad_host("login.microsoftonline.com")


def test_telemetry_policy_is_narrow():
    assert tekzite_network._is_browser_telemetry_host("vortex.data.microsoft.com")
    assert not tekzite_network._is_browser_telemetry_host("microsoft.com")
    assert not tekzite_network._is_browser_telemetry_host("login.microsoftonline.com")


def test_https_helper_is_connect_tunnel_not_mitm():
    source = (ROOT / "tekzite_network.py").read_text(encoding="utf-8")
    assert "CONNECT" in source
    assert "ssl.wrap_socket" not in source
    assert "SSLContext" not in source


def test_github_repo_metadata_exists():
    for relative in (
        ".gitignore",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
        ".github/workflows/ci.yml",
    ):
        assert (ROOT / relative).is_file(), relative

