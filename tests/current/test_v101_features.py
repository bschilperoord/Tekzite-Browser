from pathlib import Path
import json
import os

import main
from engine import net

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
FEATURES = (ROOT / 'browser_features.py').read_text(encoding='utf-8')
NET = (ROOT / 'engine' / 'net.py').read_text(encoding='utf-8')


def test_v101_release_number():
    assert main.BROWSER_VERSION == '10.5.128'


def test_extension_entries_are_normalized_and_deduplicated(tmp_path):
    ext = tmp_path / 'ext'
    ext.mkdir()
    (ext / 'manifest.json').write_text('{}', encoding='utf-8')
    rows = main._normalized_extension_entries([
        {'path': str(ext), 'enabled': True},
        {'path': str(ext), 'enabled': False},
    ])
    assert len(rows) == 1
    assert rows[0]['enabled'] is True
    assert main._enabled_extension_paths({'extensions': rows}) == [rows[0]['path']]


def test_extension_launcher_accepts_manifest_v2_and_v3_only(tmp_path, monkeypatch):
    mv2 = tmp_path / 'mv2'
    mv3 = tmp_path / 'mv3'
    unsupported = tmp_path / 'mv4'
    missing = tmp_path / 'missing'
    for path in (mv2, mv3, unsupported, missing):
        path.mkdir()
    (mv2 / 'manifest.json').write_text('{"manifest_version":2,"name":"Legacy","version":"1"}', encoding='utf-8')
    (mv3 / 'manifest.json').write_text('{"manifest_version":3,"name":"Modern","version":"1"}', encoding='utf-8')
    (unsupported / 'manifest.json').write_text('{"manifest_version":4,"name":"Future","version":"1"}', encoding='utf-8')
    monkeypatch.setenv(
        'TEKZITE_USER_EXTENSIONS',
        json.dumps([str(mv2), str(mv3), str(unsupported), str(missing)]),
    )
    result = net._configured_user_extension_dirs()
    assert result == [mv2.resolve(), mv3.resolve()]


def test_chromium_launch_keeps_mv2_compatibility_flags():
    source = Path(net.__file__).read_text(encoding='utf-8')
    assert 'ExtensionManifestV2Disabled' in source
    assert 'ExtensionManifestV2Unsupported' in source
    assert 'ExtensionsManifestV3Only' in source
    assert 'ExtensionDisableUnsupportedDeveloper' in source
    assert 'DisableLoadExtensionCommandLineSwitch' in source
    assert '--enable-features=AllowLegacyMV2Extensions' in source


def test_private_profile_override(tmp_path, monkeypatch):
    profile = tmp_path / 'private-profile'
    monkeypatch.setenv('TEKZITE_CHROMIUM_PROFILE', str(profile))
    assert Path(net._persistent_chromium_profile_dir()) == profile.resolve()
    assert profile.is_dir()


def test_private_mode_does_not_checkpoint_history_or_session():
    assert "if self._closing or getattr(self, '_private_mode', False)" in FEATURES
    assert "if getattr(self, '_private_mode', False):" in FEATURES
    assert 'if getattr(self, "_private_mode", False):' in MAIN
    checkpoint = FEATURES[FEATURES.index("def _checkpoint_features"):FEATURES.index("def _record_page_visit")]
    assert "privacy_lockdown" not in checkpoint


def test_site_privacy_cdp_is_origin_scoped():
    assert 'def get_embedded_chromium_site_info' in NET
    assert 'Network.getCookies' in NET
    assert 'Storage.getUsageAndQuota' in NET
    assert 'def clear_embedded_chromium_site_data' in NET
    assert 'Storage.clearDataForOrigin' in NET
    assert 'Network.clearBrowserCookies' not in NET


def test_extension_manager_and_private_window_are_wired_to_ui():
    assert 'New Private Window' in MAIN
    assert 'Extension Manager' in MAIN
    assert 'Site Info & Privacy' in MAIN
    assert 'Add unpacked…' in FEATURES

