from pathlib import Path

import main


def test_release_version_is_10540():
    assert main.BROWSER_VERSION == "10.5.47"


def test_windows_url_activation_parser_ignores_tekzite_switches(tmp_path):
    assert main._requested_launch_target(["--private", "https://example.test/a?b=1"]) == "https://example.test/a?b=1"
    assert main._requested_launch_target(["--profile", "Music", "https://example.test/"]) == "https://example.test/"
    assert main._requested_launch_target(["--profile=Music", "https://example.test/"]) == "https://example.test/"

    html = tmp_path / "local page.html"
    html.write_text("<title>Tekzite</title>", encoding="utf-8")
    assert main._requested_launch_target([str(html)]) == html.resolve().as_uri()


def test_default_browser_registry_plan_has_required_windows_capabilities():
    plan = main._tekzite_default_browser_registry_plan(
        r"C:\Program Files\Tekzite Browser\TekziteBrowser.exe",
        frozen=True,
    )
    values = {(path, name): value for path, name, value in plan}
    capabilities = r"Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities"
    assert values[(r"Software\RegisteredApplications", "Tekzite Browser")] == capabilities
    assert values[(capabilities + r"\URLAssociations", "http")] == "TekziteBrowserURL"
    assert values[(capabilities + r"\URLAssociations", "https")] == "TekziteBrowserURL"
    assert values[(capabilities + r"\FileAssociations", ".htm")] == "TekziteBrowserHTML"
    assert values[(capabilities + r"\FileAssociations", ".html")] == "TekziteBrowserHTML"
    command = values[(r"Software\Classes\TekziteBrowserURL\shell\open\command", "")]
    assert "TekziteBrowser.exe" in command
    assert '"%1"' in command


def test_default_apps_deep_link_targets_per_user_registration():
    assert main._default_apps_settings_uri() == "ms-settings:defaultapps?registeredAppUser=Tekzite%20Browser"


def test_installer_registers_browser_capabilities():
    root = Path(main.__file__).resolve().parent
    iss = (root / "installer" / "TekziteBrowser.iss").read_text(encoding="utf-8")
    assert "ChangesAssociations=yes" in iss
    assert r"Software\RegisteredApplications" in iss
    assert r"Capabilities\URLAssociations" in iss
    assert 'ValueName: "http"' in iss
    assert 'ValueName: "https"' in iss
    assert 'ValueName: ".htm"' in iss
    assert 'ValueName: ".html"' in iss
